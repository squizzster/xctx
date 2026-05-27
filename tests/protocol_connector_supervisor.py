#!/usr/bin/env python3
"""Focused tests for xctx middleware connectors and external-command filesystem demo."""

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
from xctx.config.loader import load_store  # noqa: E402
from xctx.errors import XctxError  # noqa: E402
from xctx.ports.external_command import call_external_command  # noqa: E402
from xctx_connectors.middleware import _resolve_workspace_entrypoint  # noqa: E402
from xctx_connectors.domains.file_manager.external_command_adapter import _safe_path  # noqa: E402


DOMAIN_ADAPTER_MODULE = "xctx_connectors.domains.file_manager.external_command_adapter"
MARKET_ADAPTER_ENTRYPOINT = "examples/stock_intelligence_hub/adapters/market_data_gateway.py"
FILE_MANAGER_README = ROOT / "data" / "file_manager_home" / "README.txt"


def assert_payload_contract(connector: dict, *, contract: str, failure_payload: str) -> None:
    guarantee = connector["payload_contract"]
    assert guarantee["contract"] == contract
    assert guarantee["xctx_receives"] == "single_json_object_for_live_data"
    assert guarantee["failure_payload"] == failure_payload
    assert guarantee["raw_external_output"] == "never_returned_unparsed"
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
        [sys.executable, str(ROOT / "connector_supervisor.py"), "observe", "file:README.txt", "--compact"],
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
    assert payload["object_type"] == "xctx_connector_error"
    assert payload["found"] is False
    assert_payload_contract(payload["connector"], contract="always_json_object", failure_payload="xctx_connector_error")
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
        "live_object_type": "external_command_filesystem_discovery",
        "middleware_loaded": False,
        "domain_adapter_loaded": False,
    }


def test_live_entrypoint_must_use_connector_supervisor() -> None:
    store = load_store(root=ROOT)
    subdomain = dict(store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"])
    subdomain["entrypoint"] = {**subdomain["entrypoint"], "file": MARKET_ADAPTER_ENTRYPOINT}
    try:
        call_external_command(store, subdomain, ["discover"])
    except XctxError as exc:
        assert str(exc) == "live subdomain must route through connector_supervisor.py"
    else:  # pragma: no cover - defensive standalone script check
        raise AssertionError("accepted direct live adapter entrypoint")


def test_passthrough_target_entrypoint_stays_inside_workspace() -> None:
    assert _resolve_workspace_entrypoint(ROOT, MARKET_ADAPTER_ENTRYPOINT, label="target_entrypoint") == (
        ROOT / MARKET_ADAPTER_ENTRYPOINT
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


def test_root_audit_does_not_import_scoped_external_command_adapter() -> None:
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
    market = run_engine(["discover", "stock_intelligence_hub::market_data_gateway::search_market_series", "AAPL"])
    live = market["results"]["live_data"]
    assert live["object_type"] == "market_data_gateway::search_market_series::result"
    assert live["matches"][0]["market_series_id"] == "market_series:aapl:daily"

    filing = run_engine(["observe", "stock_intelligence_hub::equity_filing", "form:10-K"])
    filing_live = filing["results"]["live_data"]
    assert filing_live["object_type"] == "filing_form_observation"
    assert filing_live["id"] == "form:10-K"


def test_xctx_native_passthrough_failure_has_payload_contract() -> None:
    env = os.environ.copy()
    env["XCTX_AGENT_DOMAIN"] = "stock_intelligence_hub"
    env["XCTX_AGENT_SUBDOMAIN"] = "market_data_gateway"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "connector_supervisor.py"), "not-a-real-command", "--compact"],
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
    assert_payload_contract(
        payload["connector"],
        contract="pass_through_json_object",
        failure_payload="xctx_native_passthrough_error",
    )


def test_xctx_native_passthrough_failure_hides_argv_until_max_detail() -> None:
    compact = run_engine(
        ["discover", "stock_intelligence_hub::market_data_gateway::list_instruments", "--cursor", "nope"],
        code=1,
    )
    assert compact["ok"] is False
    assert compact["error"] == "--cursor requires an integer"
    compact_live = compact["results"]["live_data"]
    assert compact_live["object_type"] == "xctx_native_passthrough_error"
    assert "command_status" not in compact_live

    full = run_engine(
        [
            "--max",
            "discover",
            "stock_intelligence_hub::market_data_gateway::list_instruments",
            "--cursor",
            "nope",
        ],
        code=1,
    )
    assert full["ok"] is False
    full_live = full["results"]["live_data"]
    assert full_live["object_type"] == "xctx_native_passthrough_error"
    assert full_live["command_status"]["ok"] is False
    assert any(part.endswith(MARKET_ADAPTER_ENTRYPOINT) for part in full_live["command_status"]["argv"])


def test_external_command_filesystem_discovery_and_observation() -> None:
    discovery = run_engine(["--max", "discover", "file_manager::home_directory"])
    live = discovery["results"]["live_data"]
    assert live["object_type"] == "external_command_filesystem_discovery"
    assert live["connector"]["kind"] == "external_command"
    assert live["connector"]["adapter_scope"] == "domain"
    assert_payload_contract(live["connector"], contract="always_json_object", failure_payload="xctx_connector_error")
    assert live["observable_objects"]["file"]["id_pattern"] == "file:<relative_path>"

    files = run_engine(["discover", "file_manager::home_directory::list_files", "--limit", "5"])
    file_live = files["results"]["live_data"]
    assert file_live["object_type"] == "external_command_filesystem_file_list"
    assert "connector" not in file_live
    assert file_live["files"][0]["id"] == "file:README.txt"
    assert file_live["files"][0]["observe_cmd"] == "./xctx observe file_manager::home_directory file:README.txt"
    assert "pagination" not in file_live
    assert "external_command" not in file_live
    assert "command_status" not in file_live
    assert "This is a bundled file-manager demo fixture" not in json.dumps(file_live)

    files_full = run_engine(["--max", "discover", "file_manager::home_directory::list_files", "--limit", "1", "--projection", "full"])
    files_full_live = files_full["results"]["live_data"]
    assert files_full_live["projection"] == "full"
    assert files_full_live["pagination"]["total_count"] == 1
    assert files_full_live["pagination"]["returned_count"] == 1
    assert files_full_live["command_status"]["argv"][0] == "ls"

    discovered_file = run_engine(["discover", "file_manager::home_directory", "file:README.txt"])
    discovered_file_live = discovered_file["results"]["live_data"]
    assert discovered_file_live["object_type"] == "external_command_filesystem_file_discovery"
    assert "connector" not in discovered_file_live
    assert discovered_file_live["id"] == "file:README.txt"
    expected_readme_bytes = len(FILE_MANAGER_README.read_bytes())
    assert discovered_file_live["type"] == "ASCII text"
    assert discovered_file_live["size_bytes"] == expected_readme_bytes
    assert discovered_file_live["observe_cmd"] == "./xctx observe file_manager::home_directory file:README.txt"
    assert "file_id" not in discovered_file_live
    assert "file_type" not in discovered_file_live
    assert "external_commands" not in discovered_file_live
    assert "command_status" not in discovered_file_live
    assert "content" not in discovered_file_live
    assert "This is a bundled file-manager demo fixture" not in json.dumps(discovered_file_live)
    assert "configured_action_index" not in discovered_file["results"]

    discovered_file_full = run_engine(["--max", "discover", "file_manager::home_directory", "file:README.txt", "--projection", "full"])
    discovered_file_full_live = discovered_file_full["results"]["live_data"]
    assert discovered_file_full_live["projection"] == "full"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*\+00:00", discovered_file_full_live["modified_at"])
    assert re.fullmatch(r"[A-Z][a-z]{2} [ 0-9]\d \d{2}:\d{2}", discovered_file_full_live["modified_display"])
    assert discovered_file_full_live["command_status"]["stat_line"]["argv"][0] == "ls"
    assert discovered_file_full_live["command_status"]["type"]["argv"][0] == "file"

    discovered_directory = run_engine(["discover", "file_manager::home_directory", "directory:docs"])
    discovered_directory_live = discovered_directory["results"]["live_data"]
    assert discovered_directory_live["object_type"] == "external_command_filesystem_directory_discovery"
    assert discovered_directory_live["id"] == "directory:docs"
    assert discovered_directory_live["child_count"] == 1

    observed = run_engine(["--max", "observe", "file_manager::home_directory", "file:README.txt"])
    observed_live = observed["results"]["live_data"]
    assert observed["results"]["agent_domain"] == "file_manager"
    assert observed_live["object_type"] == "external_command_filesystem_file_observation"
    assert_payload_contract(observed_live["connector"], contract="always_json_object", failure_payload="xctx_connector_error")
    assert observed_live["command_status"]["ok"] is True
    assert observed_live["file_type"]
    assert observed_live["content"]["available"] is True
    assert observed_live["content"]["bytes_returned"] == expected_readme_bytes
    assert "This is a bundled file-manager demo fixture" in observed_live["content"]["text"]


def test_external_command_filesystem_always_shapes_failures() -> None:
    escaped = run_engine(["--max", "observe", "file_manager::home_directory", "file:../README.md"], code=1)
    assert escaped["ok"] is False
    assert escaped["error"] == "path escapes configured safe root"
    live = escaped["results"]["live_data"]
    assert live["object_type"] == "xctx_connector_error"
    assert live["found"] is False
    assert_payload_contract(live["connector"], contract="always_json_object", failure_payload="xctx_connector_error")
    assert live["command_status"]["ok"] is False
    assert "safe root" in live["command_status"]["error"]

    unknown = run_engine(["--max", "observe", "file_manager::home_directory", "file:missing.txt"])
    assert unknown["ok"] is True
    unknown_live = unknown["results"]["live_data"]
    assert unknown_live["object_type"] == "external_command_filesystem_observation"
    assert_payload_contract(unknown_live["connector"], contract="always_json_object", failure_payload="xctx_connector_error")
    assert unknown_live["found"] is False
    assert unknown_live["status"] == "not_found"
    assert unknown_live["command_status"]["ok"] is True


def main() -> int:
    test_middleware_returns_json_without_xctx_env()
    test_safe_path_blocks_escape()
    test_domain_adapter_import_path_exists()
    test_xctx_invokes_connector_supervisor_out_of_process()
    test_live_entrypoint_must_use_connector_supervisor()
    test_passthrough_target_entrypoint_stays_inside_workspace()
    test_generic_connector_runtime_has_no_file_manager_implementation()
    test_root_audit_does_not_import_scoped_external_command_adapter()
    test_xctx_native_passthrough_stays_transparent()
    test_xctx_native_passthrough_failure_has_payload_contract()
    test_xctx_native_passthrough_failure_hides_argv_until_max_detail()
    test_external_command_filesystem_discovery_and_observation()
    test_external_command_filesystem_always_shapes_failures()

    cli = subprocess.run(
        [str(XCTX), "--json", "discover", "file_manager::home_directory::list_directories"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr + cli.stdout
    assert cli.stderr == "", cli.stderr
    assert json.loads(cli.stdout)["results"]["live_data"]["object_type"] == "external_command_filesystem_directory_list"

    print("connector supervisor middleware checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
