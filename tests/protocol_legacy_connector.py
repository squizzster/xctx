#!/usr/bin/env python3
"""Focused tests for xctx middleware connectors and legacy filesystem demo."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / "libs"
XCTX = ROOT / "xctx"

if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from xctx.process.runtime import main as xctx_main  # noqa: E402
from xctx.commands.registry import command_handlers  # noqa: E402
from xctx.config.loader import load_store  # noqa: E402
from xctx.domain.diagnostics import run_diagnostics  # noqa: E402
from xctx.errors import XctxError  # noqa: E402
from xctx.ports.external_command import call_external_command  # noqa: E402
from xctx_connectors.middleware import _resolve_workspace_entrypoint  # noqa: E402
from xctx_connectors.domains.file_manager.legacy_adapter import _safe_path  # noqa: E402


DOMAIN_ADAPTER_MODULE = "xctx_connectors.domains.file_manager.legacy_adapter"


def assert_shape_guarantee(connector: dict, *, contract: str, failure_shape: str) -> None:
    guarantee = connector["shape_guarantee"]
    assert guarantee["contract"] == contract
    assert guarantee["xctx_receives"] == "single_json_object_for_live_data"
    assert guarantee["failure_shape"] == failure_shape
    assert guarantee["raw_legacy_output"] == "never_returned_unparsed"
    assert guarantee["stdout_stderr"] == "summarized_in_command_status_when_useful"


def run_engine(args: Iterable[str], code: int = 0) -> dict:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = xctx_main(["--json", *list(args)], root=ROOT)
    assert rc == code, f"args={list(args)} rc={rc}\nSTDOUT={out.getvalue()}\nSTDERR={err.getvalue()}"
    assert err.getvalue() == "", err.getvalue()
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1, out.getvalue()
    return json.loads(lines[0])


def test_middleware_returns_json_without_xctx_env() -> None:
    env = os.environ.copy()
    env.pop("XCTX_AGENT_DOMAIN", None)
    env.pop("XCTX_AGENT_SUBDOMAIN", None)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "legacy_connector.py"), "observe", "file:README.txt", "--compact"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert proc.stderr == "", proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["object_type"] == "legacy_connector_error"
    assert payload["found"] is False
    assert_shape_guarantee(payload["connector"], contract="always_json_object", failure_shape="legacy_connector_error")
    assert "XCTX_AGENT_DOMAIN" in payload["command_status"]["error"]


def test_safe_path_blocks_escape() -> None:
    safe_root = ROOT / "data" / "file_manager_home"
    assert _safe_path(safe_root, "docs/manual.txt", expected="file").relative == "docs/manual.txt"
    try:
        _safe_path(safe_root, "../README.md", expected="file")
    except ValueError as exc:
        assert "safe root" in str(exc)
    else:  # pragma: no cover - defensive standalone script check
        raise AssertionError("safe path accepted traversal")


def test_domain_adapter_import_path_exists() -> None:
    adapter = __import__(DOMAIN_ADAPTER_MODULE, fromlist=["run"])
    assert callable(adapter.run)


def test_xctx_invokes_connector_supervisor_out_of_process() -> None:
    code = f"""
import contextlib
import io
import json
import sys
from pathlib import Path

ROOT = Path({str(ROOT)!r})
LIBS = ROOT / "libs"
if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from xctx.process.runtime import main as xctx_main

out = io.StringIO()
err = io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
    rc = xctx_main(["--json", "discover", "file_manager::home_directory"], root=ROOT)

lines = [line for line in out.getvalue().splitlines() if line.strip()]
payload = json.loads(lines[0]) if lines else {{}}

print(json.dumps({{
    "rc": rc,
    "stderr": err.getvalue(),
    "stdout_lines": len(lines),
    "live_object_type": payload.get("results", {{}}).get("live_data", {{}}).get("object_type"),
    "middleware_loaded": "xctx_connectors.middleware" in sys.modules,
    "domain_adapter_loaded": {DOMAIN_ADAPTER_MODULE!r} in sys.modules,
}}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload == {
        "rc": 0,
        "stderr": "",
        "stdout_lines": 1,
        "live_object_type": "legacy_connector_filesystem_discovery",
        "middleware_loaded": False,
        "domain_adapter_loaded": False,
    }


def test_live_entrypoint_must_use_connector_supervisor() -> None:
    store = load_store(root=ROOT)
    subdomain = dict(store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"])
    subdomain["entrypoint"] = {**subdomain["entrypoint"], "file": "market_data_gateway.py"}
    try:
        call_external_command(store, subdomain, ["discover"])
    except XctxError as exc:
        assert "route live subdomain through legacy_connector.py" in str(exc)
    else:  # pragma: no cover - defensive standalone script check
        raise AssertionError("accepted direct live adapter entrypoint")


def test_doctor_rejects_direct_live_adapter_entrypoint() -> None:
    store = load_store(root=ROOT)
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["entrypoint"] = {**subdomain["entrypoint"], "file": "market_data_gateway.py"}
    diagnostics = run_diagnostics(store, set(command_handlers()))
    entrypoint_check = next(item for item in diagnostics if item["id"] == "doctor:external_command_entrypoints_resolve")
    assert entrypoint_check["status"] == "fail"
    assert entrypoint_check["adapter_errors"] == [
        {
            "target": "stock_intelligence_hub::market_data_gateway",
            "reason": "entrypoint must use connector supervisor",
            "entrypoint": "market_data_gateway.py",
        }
    ]


def test_passthrough_target_entrypoint_stays_inside_workspace() -> None:
    assert _resolve_workspace_entrypoint(ROOT, "market_data_gateway.py", label="target_entrypoint") == (
        ROOT / "market_data_gateway.py"
    ).resolve()
    for raw in ("/tmp/outside.py", "../outside.py"):
        try:
            _resolve_workspace_entrypoint(ROOT, raw, label="target_entrypoint")
        except ValueError as exc:
            assert "workspace root" in str(exc)
        else:  # pragma: no cover - defensive standalone script check
            raise AssertionError(f"accepted escaped target_entrypoint: {raw}")


def test_generic_connector_runtime_has_no_file_manager_implementation() -> None:
    forbidden = (
        "filesystem_home",
        "file_manager",
        "home_directory",
        "file:",
        "directory:",
        "ls -lt",
        "file --brief",
        "_safe_path",
        "safe_root",
    )
    for rel in ("libs/xctx_connectors/middleware.py", "libs/xctx_connectors/runtime.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token} leaked into {rel}"


def test_root_audit_does_not_import_scoped_legacy_adapter() -> None:
    code = f"""
import contextlib
import io
import json
import sys
from pathlib import Path

ROOT = Path({str(ROOT)!r})
LIBS = ROOT / "libs"
if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from xctx.process.runtime import main as xctx_main

out = io.StringIO()
err = io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
    rc = xctx_main(["--json", "audit", "root"], root=ROOT)

print(json.dumps({{
    "rc": rc,
    "stderr": err.getvalue(),
    "stdout_lines": len([line for line in out.getvalue().splitlines() if line.strip()]),
    "domain_adapter_loaded": {DOMAIN_ADAPTER_MODULE!r} in sys.modules,
}}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload == {
        "rc": 0,
        "stderr": "",
        "stdout_lines": 1,
        "domain_adapter_loaded": False,
    }


def test_xctx_native_passthrough_stays_transparent() -> None:
    market = run_engine(["discover", "stock_intelligence_hub::market_data_gateway", "search_market_series", "AAPL"])
    live = market["results"]["live_data"]
    assert live["object_type"] == "market_data_gateway::search_market_series::result"
    assert live["matches"][0]["market_series_id"] == "market_series:aapl:daily"

    filing = run_engine(["observe", "form:10-K"])
    filing_live = filing["results"]["live_data"]
    assert filing_live["object_type"] == "filing_form_observation"
    assert filing_live["id"] == "form:10-K"


def test_xctx_native_passthrough_failure_has_shape_guarantee() -> None:
    env = os.environ.copy()
    env["XCTX_AGENT_DOMAIN"] = "stock_intelligence_hub"
    env["XCTX_AGENT_SUBDOMAIN"] = "market_data_gateway"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "legacy_connector.py"), "not-a-real-command", "--compact"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert proc.stderr == "", proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["object_type"] == "xctx_native_passthrough_error"
    assert payload["found"] is False
    assert_shape_guarantee(
        payload["connector"],
        contract="pass_through_json_object",
        failure_shape="xctx_native_passthrough_error",
    )


def test_xctx_native_passthrough_failure_hides_argv_until_full_shape() -> None:
    compact = run_engine(
        ["discover", "stock_intelligence_hub::market_data_gateway", "list_instruments", "--cursor", "nope"],
        code=1,
    )
    assert compact["ok"] is False
    assert compact["error"] == "--cursor requires an integer"
    compact_live = compact["results"]["live_data"]
    assert compact_live["object_type"] == "xctx_native_passthrough_error"
    assert compact_live["command_status"]["ok"] is False
    assert compact_live["command_status"]["error"] == "--cursor requires an integer"
    assert "argv" not in compact_live["command_status"]

    full = run_engine(
        [
            "discover",
            "stock_intelligence_hub::market_data_gateway",
            "list_instruments",
            "--cursor",
            "nope",
            "--shape",
            "full",
        ],
        code=1,
    )
    assert full["ok"] is False
    full_live = full["results"]["live_data"]
    assert full_live["object_type"] == "xctx_native_passthrough_error"
    assert full_live["command_status"]["ok"] is False
    assert full_live["command_status"]["argv"][1].endswith("market_data_gateway.py")


def test_legacy_filesystem_discovery_and_observation() -> None:
    discovery = run_engine(["discover", "file_manager::home_directory"])
    live = discovery["results"]["live_data"]
    assert live["object_type"] == "legacy_connector_filesystem_discovery"
    assert live["connector"]["kind"] == "legacy_command"
    assert live["connector"]["adapter_scope"] == "domain"
    assert_shape_guarantee(live["connector"], contract="always_json_object", failure_shape="legacy_connector_error")
    assert live["observable_objects"]["file"]["id_shape"] == "file:<relative_path>"

    files = run_engine(["discover", "file_manager::home_directory", "list_files", "--limit", "5"])
    file_live = files["results"]["live_data"]
    assert file_live["object_type"] == "legacy_connector_filesystem_file_list"
    assert_shape_guarantee(file_live["connector"], contract="always_json_object", failure_shape="legacy_connector_error")
    assert file_live["files"][0]["id"] == "file:README.txt"
    assert file_live["files"][0]["observe_cmd"] == "./xctx observe file_manager::home_directory file:README.txt"
    assert "pagination" not in file_live
    assert "legacy_command" not in file_live
    assert "command_status" not in file_live
    assert "This is a bundled file-manager demo fixture" not in json.dumps(file_live)

    files_full = run_engine(["discover", "file_manager::home_directory", "list_files", "--limit", "1", "--shape", "full"])
    files_full_live = files_full["results"]["live_data"]
    assert files_full_live["shape"] == "full"
    assert files_full_live["pagination"]["total_count"] == 1
    assert files_full_live["pagination"]["returned_count"] == 1
    assert files_full_live["command_status"]["argv"][0] == "ls"

    discovered_file = run_engine(["discover", "file_manager::home_directory", "file:README.txt"])
    discovered_file_live = discovered_file["results"]["live_data"]
    assert discovered_file_live["object_type"] == "legacy_connector_filesystem_file_discovery"
    assert_shape_guarantee(discovered_file_live["connector"], contract="always_json_object", failure_shape="legacy_connector_error")
    assert discovered_file_live["id"] == "file:README.txt"
    assert discovered_file_live["type"] == "ASCII text"
    assert discovered_file_live["size_bytes"] == 237
    assert discovered_file_live["observe_cmd"] == "./xctx observe file_manager::home_directory file:README.txt"
    assert "file_id" not in discovered_file_live
    assert "file_type" not in discovered_file_live
    assert "legacy_commands" not in discovered_file_live
    assert "command_status" not in discovered_file_live
    assert "content" not in discovered_file_live
    assert "This is a bundled file-manager demo fixture" not in json.dumps(discovered_file_live)
    assert "configured_action_index" not in discovered_file["results"]

    discovered_file_full = run_engine(["discover", "file_manager::home_directory", "file:README.txt", "--shape", "full"])
    discovered_file_full_live = discovered_file_full["results"]["live_data"]
    assert discovered_file_full_live["shape"] == "full"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*\+00:00", discovered_file_full_live["modified_at"])
    assert re.fullmatch(r"[A-Z][a-z]{2} [ 0-9]\d \d{2}:\d{2}", discovered_file_full_live["modified_display"])
    assert discovered_file_full_live["command_status"]["stat_line"]["argv"][0] == "ls"
    assert discovered_file_full_live["command_status"]["type"]["argv"][0] == "file"

    discovered_directory = run_engine(["discover", "file_manager::home_directory", "directory:docs"])
    discovered_directory_live = discovered_directory["results"]["live_data"]
    assert discovered_directory_live["object_type"] == "legacy_connector_filesystem_directory_discovery"
    assert discovered_directory_live["id"] == "directory:docs"
    assert discovered_directory_live["child_count"] == 1

    observed = run_engine(["observe", "file:README.txt"])
    observed_live = observed["results"]["live_data"]
    assert observed["results"]["agent_domain"] == "file_manager"
    assert observed_live["object_type"] == "legacy_connector_filesystem_file_observation"
    assert_shape_guarantee(observed_live["connector"], contract="always_json_object", failure_shape="legacy_connector_error")
    assert observed_live["command_status"]["ok"] is True
    assert observed_live["file_type"]
    assert observed_live["content"]["available"] is True
    assert observed_live["content"]["bytes_returned"] == 237
    assert "This is a bundled file-manager demo fixture" in observed_live["content"]["text"]


def test_legacy_filesystem_always_shapes_failures() -> None:
    escaped = run_engine(["observe", "file:../README.md"], code=1)
    assert escaped["ok"] is False
    assert escaped["error"] == "path escapes configured safe root"
    live = escaped["results"]["live_data"]
    assert live["object_type"] == "legacy_connector_error"
    assert live["found"] is False
    assert_shape_guarantee(live["connector"], contract="always_json_object", failure_shape="legacy_connector_error")
    assert live["command_status"]["ok"] is False
    assert "safe root" in live["command_status"]["error"]

    unknown = run_engine(["observe", "file:missing.txt"], code=1)
    assert unknown["ok"] is False
    unknown_live = unknown["results"]["live_data"]
    assert unknown_live["object_type"] == "legacy_connector_filesystem_observation"
    assert_shape_guarantee(unknown_live["connector"], contract="always_json_object", failure_shape="legacy_connector_error")
    assert unknown_live["found"] is False
    assert unknown_live["command_status"]["ok"] is False


def main() -> int:
    test_middleware_returns_json_without_xctx_env()
    test_safe_path_blocks_escape()
    test_domain_adapter_import_path_exists()
    test_xctx_invokes_connector_supervisor_out_of_process()
    test_live_entrypoint_must_use_connector_supervisor()
    test_doctor_rejects_direct_live_adapter_entrypoint()
    test_passthrough_target_entrypoint_stays_inside_workspace()
    test_generic_connector_runtime_has_no_file_manager_implementation()
    test_root_audit_does_not_import_scoped_legacy_adapter()
    test_xctx_native_passthrough_stays_transparent()
    test_xctx_native_passthrough_failure_has_shape_guarantee()
    test_xctx_native_passthrough_failure_hides_argv_until_full_shape()
    test_legacy_filesystem_discovery_and_observation()
    test_legacy_filesystem_always_shapes_failures()

    cli = subprocess.run(
        [str(XCTX), "--json", "discover", "file_manager::home_directory", "list_directories"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr + cli.stdout
    assert cli.stderr == "", cli.stderr
    assert json.loads(cli.stdout)["results"]["live_data"]["object_type"] == "legacy_connector_filesystem_directory_list"

    print("legacy connector middleware checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
