"""Pytest release gate for the xctx proof-of-concept workspace."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_checked(args: list[str], timeout: int = 60) -> None:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    assert proc.returncode == 0, (
        f"command failed: {' '.join(args)}\n"
        f"returncode={proc.returncode}\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )


def test_yaml_surface_validator() -> None:
    run_checked([sys.executable, ".agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py"])


def test_smoke_protocol() -> None:
    run_checked([sys.executable, "tests/smoke_protocol.py"])


def test_protocol_pressure() -> None:
    run_checked([sys.executable, "tests/protocol_pressure_pro.py"])


def test_protocol_legacy_connector() -> None:
    run_checked([sys.executable, "tests/protocol_legacy_connector.py"])


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
            "equity_instruments.py",
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
        ROOT / "libs" / "xctx",
        ROOT / "yaml_dynamic_config",
    ]
    stale_fragments = (
        "--system {item.get('id')} status",
        "--system {identity['id']} discover",
        "next valid move: identify",
        "identify_query_run_cmd",
    )
    for base in scanned_paths:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".yaml", ".yml"}:
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
    for legacy in ("status", "identify", "doctor", "write"):
        assert legacy not in configured

    store["protocol"]["command_groups"]["main"].append("status")
    store["commands"]["xctx"]["status"] = {"legacy status command": "[]"}
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
