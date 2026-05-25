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

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_checked(args: list[str], timeout: int = 180) -> None:
    runtime_parent = ROOT / ".xctx_runtime"
    runtime_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pytest_", dir=runtime_parent) as runtime_dir:
        env = {**os.environ, "XCTX_RUNTIME_DIR": runtime_dir}
        proc = subprocess.Popen(
            args,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()
            raise AssertionError(
                f"command timed out after {timeout}s: {' '.join(args)}\nSTDOUT={stdout}\nSTDERR={stderr}"
            ) from exc

    assert proc.returncode == 0, (
        f"command failed: {' '.join(args)}\n"
        f"returncode={proc.returncode}\nSTDOUT={stdout}\nSTDERR={stderr}"
    )


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
