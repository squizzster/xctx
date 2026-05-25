"""Framework release gate for the xctx protocol runtime."""

from __future__ import annotations

import copy
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
    runtime_parent = ROOT / "experiments_tmp"
    runtime_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xctx_release_gate_", dir=runtime_parent) as runtime_dir:
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


def ensure_libs_path() -> None:
    libs = str(ROOT / "libs")
    if libs not in sys.path:
        sys.path.insert(0, libs)


def run_runtime_json(args: list[str]) -> tuple[int, dict]:
    ensure_libs_path()
    from xctx.process import runtime  # noqa: PLC0415

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = runtime.main(["--json", *args], root=ROOT)
    assert err.getvalue() == ""
    return rc, json.loads(out.getvalue())


def test_yaml_surface_validator() -> None:
    run_checked([sys.executable, ".agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py"])


def test_compileall_release_paths() -> None:
    run_checked(
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "bin",
            "connector_supervisor.py",
            "libs/xctx",
            "libs/xctx_connectors/runtime.py",
            "libs/xctx_connectors/middleware.py",
            "tests/test_release_validation.py",
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
    ensure_libs_path()
    import xctx  # noqa: PLC0415

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "4.2.0"' in pyproject
    assert xctx.__version__ == "4.2.0"


def test_no_stale_status_or_identify_guidance() -> None:
    scanned_paths = [
        ROOT / "bin",
        ROOT / "connector_supervisor.py",
        ROOT / "libs" / "xctx",
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
    ensure_libs_path()
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


def test_framework_cli_command_contract() -> None:
    for command in ("discover", "observe", "plan", "execute", "audit", "repair"):
        rc, payload = run_runtime_json([command])
        if command in {"observe", "execute", "repair"}:
            assert rc == 1
            assert payload["ok"] is False
        elif command == "plan":
            assert rc == 1
            assert payload["ok"] is False
            assert payload["error"] == "next valid move: ./xctx plan <operation> <target>"
        else:
            assert rc == 0
            assert payload["record_type"] in {"discovery", "audit"}

    rc, payload = run_runtime_json(["other", "--topic", "ping"])
    assert rc == 0
    assert payload["record_type"] == "extension"
    assert payload["results"]["topic"] == "ping"

    rc, payload = run_runtime_json(["other"])
    assert rc == 1
    assert payload["ok"] is False

    for rejected_command in ("status", "identify", "doctor", "write", "discovery", "d", "xctx_other"):
        rc, payload = run_runtime_json([rejected_command])
        assert rc == 1
        assert payload["record_type"] == "error"
        assert "other" not in payload["error"]


def test_root_discovery_explains_scoped_next_moves() -> None:
    rc, payload = run_runtime_json(["discover"])
    assert rc == 0
    results = payload["results"]
    assert results["next_move_context"] == {
        "agent_domain_id": "Replace {{agent_domain_id}} with an id from agent_domains.",
        "agent_domain_scope_template": "./xctx discover {{agent_domain_id}}::",
        "examples": [
            "./xctx discover stock_intelligence_hub::",
            "./xctx discover file_manager::",
        ],
    }
    assert results["next_moves"][:2] == [
        "./xctx discover {{agent_domain_id}}::",
        "./xctx audit root",
    ]
    assert "xctx_other" not in json.dumps(results, sort_keys=True)


def test_audit_scope_validation_fails_closed() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.agent_domains import audit_domain_level, audit_payload  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = load_store(root=ROOT)
    domain_id = next(
        domain_id
        for domain_id, domain in sorted(store["agent_domains"].items())
        if domain.get("_subdomains")
    )
    subdomain_id = sorted(store["agent_domains"][domain_id]["_subdomains"])[0]

    assert audit_domain_level(store, "root") == "root"
    assert audit_domain_level(store, domain_id) == "agent_domain"
    assert audit_domain_level(store, f"{domain_id}::{subdomain_id}") == "agent_subdomain"

    with pytest.raises(XctxError, match="known audit scope"):
        audit_payload(store, "not_a_real_domain")
    with pytest.raises(XctxError, match="known audit scope"):
        audit_payload(store, f"{domain_id}::not_a_real_subdomain")

    rc, payload = run_runtime_json(["audit", "not_a_real_domain"])
    assert rc == 1
    assert payload["ok"] is False
    assert "known audit scope" in payload["error"]


def test_option_audit_detects_duplicates_before_dedupe() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.options import option_config_checks  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain = next(iter(store["agent_domains"].values()))
    subdomain = next(iter(domain["_subdomains"].values()))
    subdomain["cli_options"] = [
        {"flags": ["--xctx-duplicate-flag"], "dest": "first_duplicate", "commands": ["observe"]},
        {"flags": ["--xctx-duplicate-flag"], "dest": "second_duplicate", "commands": ["observe"]},
        {"flags": ["--xctx-dest-one"], "dest": "shared_duplicate_dest", "commands": ["observe"]},
        {"flags": ["--xctx-dest-two"], "dest": "shared_duplicate_dest", "commands": ["observe"]},
    ]

    checks = option_config_checks(store)
    observe_check = next(check for check in checks if check["id"] == "audit:xctx:cli_options:observe")
    assert observe_check["status"] == "fail"
    assert "--xctx-duplicate-flag" in observe_check["duplicate_flags"]
    assert "shared_duplicate_dest" in observe_check["duplicate_dests"]


def test_runtime_env_is_propagated_through_framework_connector_layers(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.ports import external_command  # noqa: PLC0415
    from xctx_connectors import runtime as connector_runtime  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", "/tmp/xctx-framework-runtime")
    assert "XCTX_RUNTIME_DIR" in external_command.SAFE_ENV_KEYS
    assert "XCTX_RUNTIME_DIR" in connector_runtime.SAFE_ENV_KEYS
    assert (
        external_command._adapter_env({"_domain_id": "domain", "id": "subdomain"})["XCTX_RUNTIME_DIR"]
        == "/tmp/xctx-framework-runtime"
    )
    assert connector_runtime.sanitized_env({})["XCTX_RUNTIME_DIR"] == "/tmp/xctx-framework-runtime"


def test_protocol_walker_uses_visible_command_surface_only() -> None:
    assert "xctx_other" not in (ROOT / "bin" / "protocol_walker").read_text(encoding="utf-8")


def test_configured_command_without_handler_fails_closed(monkeypatch) -> None:
    ensure_libs_path()
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
    ensure_libs_path()
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
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    with pytest.raises(ValueError, match="timeout_seconds"):
        runtime.run_external([sys.executable, "-c", "print('ok')"], timeout=0, max_output_bytes=1024)
    with pytest.raises(ValueError, match="max_output_bytes"):
        runtime.run_external([sys.executable, "-c", "print('ok')"], timeout=1, max_output_bytes=10)
