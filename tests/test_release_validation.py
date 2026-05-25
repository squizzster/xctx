"""Pytest release gate for the xctx proof-of-concept workspace."""

from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

import pytest


ROOT = Path(__file__).resolve().parents[1]
RELEASE_GATE_PATTERNS = (
    "connector_supervisor.py",
    "legacy_connector.py",
    "market_data_gateway.py",
    "equity_filings.py",
    "tests/smoke_protocol.py",
    "tests/protocol_pressure_pro.py",
    "tests/protocol_connector_supervisor.py",
    "tests/protocol_observe_discover_boundary.py",
    "xctx_release_gate_detached_child",
)


class ProcessRow(NamedTuple):
    pid: int
    ppid: int
    pgid: int
    cmd: str


def process_rows() -> list[ProcessRow]:
    proc = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,pgid=,args="],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    rows: list[ProcessRow] = []
    for raw_line in proc.stdout.splitlines():
        parts = raw_line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        try:
            rows.append(ProcessRow(int(parts[0]), int(parts[1]), int(parts[2]), parts[3]))
        except ValueError:
            continue
    return rows


def descendant_rows(root_pid: int, rows: list[ProcessRow]) -> list[ProcessRow]:
    by_parent: dict[int, list[ProcessRow]] = {}
    for row in rows:
        by_parent.setdefault(row.ppid, []).append(row)
    descendants: list[ProcessRow] = []
    stack = list(by_parent.get(root_pid, []))
    while stack:
        row = stack.pop()
        descendants.append(row)
        stack.extend(by_parent.get(row.pid, []))
    return descendants


def release_gate_process_rows(rows: list[ProcessRow] | None = None) -> list[ProcessRow]:
    rows = rows or process_rows()
    current_pid = os.getpid()
    return [
        row
        for row in rows
        if row.pid != current_pid
        and row.ppid != current_pid
        and any(pattern in row.cmd for pattern in RELEASE_GATE_PATTERNS)
    ]


def kill_process_rows(rows: list[ProcessRow]) -> None:
    current_pid = os.getpid()
    current_pgid = os.getpgrp() if hasattr(os, "getpgrp") else None
    for pgid in sorted({row.pgid for row in rows if row.pgid > 1}, reverse=True):
        if current_pgid is not None and pgid == current_pgid:
            continue
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    for row in rows:
        if row.pid in {0, 1, current_pid}:
            continue
        try:
            os.kill(row.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass


def assert_no_release_gate_runaways() -> None:
    runaways = release_gate_process_rows()
    assert not runaways, "release gate left subprocesses running:\n" + "\n".join(
        f"pid={row.pid} ppid={row.ppid} pgid={row.pgid} cmd={row.cmd}" for row in runaways
    )


def run_checked(args: list[str], timeout: int = 120) -> None:
    runtime_parent = ROOT / ".xctx_runtime"
    runtime_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pytest_", dir=runtime_parent) as runtime_dir:
        env = {**os.environ, "XCTX_RUNTIME_DIR": runtime_dir}
        stdout_path = Path(runtime_dir) / "stdout.txt"
        stderr_path = Path(runtime_dir) / "stderr.txt"
        with stdout_path.open("w+", encoding="utf-8") as stdout_file, stderr_path.open(
            "w+",
            encoding="utf-8",
        ) as stderr_file:
            proc = subprocess.Popen(
                args,
                cwd=ROOT,
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                env=env,
            )
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                rows = process_rows()
                kill_process_rows([row for row in rows if row.pid == proc.pid] + descendant_rows(proc.pid, rows))
                kill_process_rows(release_gate_process_rows(process_rows()))
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read()
                stderr = stderr_file.read()
                raise AssertionError(
                    f"command timed out after {timeout}s: {' '.join(args)}\nSTDOUT={stdout}\nSTDERR={stderr}"
                ) from exc
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read()
            stderr = stderr_file.read()

    assert proc.returncode == 0, (
        f"command failed: {' '.join(args)}\n"
        f"returncode={proc.returncode}\nSTDOUT={stdout}\nSTDERR={stderr}"
    )
    assert_no_release_gate_runaways()


def test_yaml_surface_validator() -> None:
    run_checked([sys.executable, ".agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py"])


def test_smoke_protocol() -> None:
    run_checked([sys.executable, "tests/smoke_protocol.py"])


def test_protocol_pressure() -> None:
    run_checked([sys.executable, "tests/protocol_pressure_pro.py"])


def test_protocol_connector_supervisor() -> None:
    run_checked([sys.executable, "tests/protocol_connector_supervisor.py"])


def test_observe_discover_boundary() -> None:
    run_checked([sys.executable, "tests/protocol_observe_discover_boundary.py"])


def test_compileall_release_paths() -> None:
    run_checked(
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "libs",
            "market_data_gateway.py",
            "equity_filings.py",
            "tests",
        ]
    )


def test_release_gate_timeout_cleans_detached_children() -> None:
    child_code = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', "
        "\"import time; print('xctx_release_gate_detached_child', flush=True); time.sleep(60)\"], "
        "start_new_session=True); "
        "time.sleep(60)"
    )
    with pytest.raises(AssertionError, match="command timed out"):
        run_checked([sys.executable, "-c", child_code], timeout=1)
    assert_no_release_gate_runaways()


def test_package_version_matches_project_metadata() -> None:
    sys.path.insert(0, str(ROOT / "libs"))
    import xctx  # noqa: PLC0415

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "4.2.0"' in pyproject
    assert xctx.__version__ == "4.2.0"


def test_no_stale_status_or_identify_guidance() -> None:
    scanned_paths = [
        ROOT / "bin",
        ROOT / "connector_supervisor.py",
        ROOT / "equity_filings.py",
        ROOT / "libs" / "xctx",
        ROOT / "market_data_gateway.py",
        ROOT / "yaml_dynamic_config",
    ]
    stale_fragments = (
        "--system",
        "--agent-domain",
        "--domain",
        "active_system",
        "active_agent_domain",
        "XCTX_ACTIVE_SYSTEM",
        "XCTX_ACTIVE_AGENT_DOMAIN",
        "identity_resolution",
        "next valid move: identify",
        "identify_query_run_cmd",
    )
    for base in scanned_paths:
        paths = [base] if base.is_file() else list(base.rglob("*"))
        for path in paths:
            if path.is_file() and (path.suffix in {".py", ".yaml", ".yml"} or path.parent == ROOT / "bin"):
                text = path.read_text(encoding="utf-8")
                for fragment in stale_fragments:
                    assert fragment not in text, f"{fragment!r} leaked in {path.relative_to(ROOT)}"


def test_command_policy_contract() -> None:
    sys.path.insert(0, str(ROOT / "libs"))
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.accessors import command_map_for_group, configured_command_names  # noqa: PLC0415
    from xctx.protocol.command_policy import hidden_commands, visible_commands  # noqa: PLC0415

    store = load_store(root=ROOT)
    assert visible_commands(store) == {"discover", "observe", "plan", "execute", "audit", "repair"}
    assert hidden_commands(store) == {"other"}
    configured = configured_command_names(store)
    assert "other" in configured
    for rejected_command in ("status", "identify", "doctor", "write", "discovery"):
        assert rejected_command not in configured

    store["protocol"]["command_groups"]["main"].append("status")
    store["commands"]["xctx"]["status"] = {"rejected status command": "[]"}
    assert "status" not in configured_command_names(store)
    assert "status" not in command_map_for_group(store, "xctx", "main")


def test_configured_command_without_handler_fails_closed(monkeypatch) -> None:
    sys.path.insert(0, str(ROOT / "libs"))
    from xctx.process import runtime  # noqa: PLC0415

    original_command_handlers = runtime.command_handlers

    def missing_repair_handler() -> dict:
        handlers = original_command_handlers()
        handlers.pop("repair")
        return handlers

    monkeypatch.setattr(runtime, "command_handlers", missing_repair_handler)

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = runtime.main(["--json", "repair", "offline:macro_intelligence_hub"], root=ROOT)

    assert rc == 1
    assert err.getvalue() == ""
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False
    assert payload["record_type"] == "error"
    assert payload["error"] == "next valid move: command repair is configured but has no production handler"


def test_connector_runtime_sanitizes_env_and_bounds_output() -> None:
    sys.path.insert(0, str(ROOT / "libs"))
    from xctx_connectors import runtime  # noqa: PLC0415

    code = (
        "import os, sys; "
        "sys.stdout.write('secret=' + str(os.environ.get('SECRET_TOKEN')) + '\\n'); "
        "sys.stdout.write('domain=' + str(os.environ.get('XCTX_AGENT_DOMAIN')) + '\\n'); "
        "sys.stdout.write('x' * 5000)"
    )
    result = runtime.run_external(
        [sys.executable, "-c", code],
        timeout=5,
        max_output_bytes=1024,
        env={"SECRET_TOKEN": "should_not_leak", "XCTX_AGENT_DOMAIN": "stock_intelligence_hub"},
    )
    assert result["ok"] is True
    assert len(result["stdout"]) == 1024
    assert "should_not_leak" not in result["stdout"]
    assert "secret=None" in result["stdout"]
    assert "domain=stock_intelligence_hub" in result["stdout"]


def test_connector_runtime_rejects_unsafe_subprocess_limits() -> None:
    sys.path.insert(0, str(ROOT / "libs"))
    from xctx_connectors import runtime  # noqa: PLC0415

    with pytest.raises(ValueError, match="timeout_seconds"):
        runtime.run_external([sys.executable, "-c", "print('ok')"], timeout=0, max_output_bytes=1024)
    with pytest.raises(ValueError, match="max_output_bytes"):
        runtime.run_external([sys.executable, "-c", "print('ok')"], timeout=1, max_output_bytes=10)


def test_sqlite_fixtures_open_read_only() -> None:
    sys.path.insert(0, str(ROOT / "libs"))
    from xctx_live import filings, instruments  # noqa: PLC0415

    for connection in (instruments.connect_market(ROOT), filings.connect(ROOT)):
        try:
            with pytest.raises(Exception):
                connection.execute("CREATE TABLE xctx_write_probe(id INTEGER)")
        finally:
            connection.close()
