#!/usr/bin/env python3
"""PRO pressure checks for xctx v4.2 protocol operability.

This script tests the protocol matrix in-process for speed and stability, then
runs a small real-CLI probe to verify the packaged launcher and persisted plan
ledger behave across separate processes.
"""

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
FILE_MANAGER_README = ROOT / "data" / "file_manager_home" / "README.txt"
if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from xctx.process.capture import capture_process  # noqa: E402
from xctx.process.runtime import main as xctx_main  # noqa: E402


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


def run_cli(args: Iterable[str], code: int = 0) -> dict:
    argv = [str(XCTX), "--json", *list(args)]
    captured = capture_process(argv, cwd=ROOT, timeout=30, max_output_bytes=131072)
    assert not captured.timed_out, f"args={list(args)} timed out\nSTDOUT={captured.stdout}\nSTDERR={captured.stderr}"
    assert captured.returncode == code, (
        f"args={list(args)} rc={captured.returncode}\nSTDOUT={captured.stdout}\nSTDERR={captured.stderr}"
    )
    assert captured.stderr == "", captured.stderr
    lines = [line for line in captured.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, captured.stdout
    return json.loads(lines[0])


def assert_cmd(payload: dict, *, ok: bool = True, record_type: str | None = None, level: str | None = None) -> None:
    assert payload["ok"] is ok, payload
    if record_type:
        assert payload["record_type"] == record_type, payload
    if level:
        assert payload["domain_level"] == level, payload


def assert_root_surface_clean(payload: object) -> None:
    text = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "--bars",
        "--calendar-days",
        "configured_options",
        "root_affordances",
        "search_entity_instrument",
        "search_market_series",
        "search_filing_form",
        "search_forms",
        "list_forms",
        "latest_price",
        "latest-price",
    ):
        assert forbidden not in text, forbidden


def assert_root_universe_command_surface() -> None:
    print("[pressure] root/universe command surface", flush=True)
    universe = run_engine([])
    assert_cmd(universe, record_type="discovery", level="universe")
    surface = universe["results"]["command_surface"]
    assert set(surface["xctx"]) == {"discover", "observe", "plan", "execute", "audit", "repair"}
    assert "extension_lane" not in surface
    assert "xctx_other" not in surface
    assert "aliases" not in surface
    assert "identify" not in surface["xctx"] and "write" not in surface["xctx"] and "status" not in surface["xctx"]
    assert_root_surface_clean(universe)
    help_payload = run_engine(["help"], code=1)
    assert help_payload["error"] == "unknown xctx command"
    assert_root_surface_clean(run_engine(["--version"]))

    root = run_engine(["discover"])
    assert_cmd(root, record_type="discovery", level="root")
    assert_root_surface_clean(root)
    rejected_alias = run_engine(["discovery"], code=1)
    assert rejected_alias["ok"] is False
    assert rejected_alias["error"] == "unknown xctx command"
    assert "configured_options" not in root["results"]
    assert "root_affordances" not in root["results"]
    assert root["results"]["next_moves"] == [
        {
            "desc": "Discover configured agent domains in this universe.",
            "run_cmd": "./xctx discover",
        },
        {
            "desc": "Audit loaded configuration, live adapters, and offline/maintenance findings.",
            "run_cmd": "./xctx audit root",
        },
    ]
    assert root["results"]["next_move_context"]["agent_domain_scope_template"] == "./xctx discover {{agent_domain_id}}::"
    assert root["results"]["next_move_context"]["examples"] == [
        "./xctx discover stock_intelligence_hub::",
        "./xctx discover file_manager::",
    ]
    root_domains = {item["id"] for item in root["results"]["agent_domains"]}
    assert root_domains == {
        "stock_intelligence_hub",
        "file_manager",
        "guess_the_number_game",
        "macro_intelligence_hub",
        "crypto_intelligence_hub",
        "options_intelligence_hub",
    }
    for domain_id in root_domains:
        assert_cmd(run_engine(["discover", domain_id]), record_type="discovery", level="agent_domain")
    for bare_target in (
        "GOOG",
        "AAPL",
        "10-K",
        "README.txt",
        "file:README.txt",
        "market_data_gateway",
        "equity_filing",
        "home_directory",
        "latest_price",
        "search_entity_instrument",
        "list_files",
        "::market_data_gateway",
        "::market_data_gateway::search_entity_instrument",
    ):
        bare = run_engine(["discover", bare_target], code=1)
        assert_cmd(bare, ok=False, record_type="error")
        assert "next " + "valid move:" not in bare["error"]
        assert all(isinstance(move, dict) and "run_cmd" in move for move in bare["next_moves"])
        assert "free_text_discovery_routed_to_configured_fallback" not in json.dumps(bare, sort_keys=True)
    for core_rel in (
        "libs/xctx/process/parser.py",
        "libs/xctx/commands/observe.py",
        "libs/xctx/domain/core.py",
        "libs/xctx/domain/routing.py",
        "libs/xctx/domain/discovery.py",
        "libs/xctx/domain/observation.py",
        "libs/xctx/domain/audit.py",
        "libs/xctx/domain/repair.py",
        "libs/xctx/domain/planning.py",
        "libs/xctx/commands/discover.py",
        "libs/xctx/protocol/command_policy.py",
        "libs/xctx/protocol/option_encoding.py",
        "libs/xctx/protocol/option_specs.py",
        "libs/xctx/protocol/option_surface.py",
    ):
        text = (ROOT / core_rel).read_text(encoding="utf-8")
        for forbidden_literal in (
            "--bars",
            "--calendar-days",
            "search_entity_instrument",
            "search_filing_form",
            "list_forms",
            "latest_price",
            "latest-price",
            "ticker",
            "symbol",
            "file_manager",
            "home_directory",
            "list_files",
            "list_directories",
            "directory:",
        ):
            assert forbidden_literal not in text, (core_rel, forbidden_literal)

def assert_domain_subdomain_discovery() -> None:
    print("[pressure] domain/subdomain discovery", flush=True)
    root = run_engine(["discover"])
    root_domains = {item["id"]: item for item in root["results"]["agent_domains"]}
    assert root_domains["file_manager"]["status"] == "online"
    domain = run_engine(["--more", "discover", "stock_intelligence_hub::"])
    assert_cmd(domain, record_type="discovery", level="agent_domain")
    subdomains = {item["id"]: item for item in domain["results"]["agent_subdomains"]}
    assert subdomains["market_data_gateway"]["status"] == "online"
    assert subdomains["equity_filing"]["status"] == "online"
    assert subdomains["fundamentals_gateway"]["terminal_reason"] == "down_for_maintenance"
    assert "no bundled fundamentals adapter" in subdomains["fundamentals_gateway"]["offline_reason"]
    assert "latest_price" in domain["results"]["domain_affordances"]
    assert "search_filing_form" in domain["results"]["domain_affordances"]

    macro = run_engine(["discover", "macro_intelligence_hub::"])
    assert macro["results"]["status"] == "offline"
    assert macro["results"]["repair_cmd"] == "./xctx repair offline:macro_intelligence_hub"
    assert macro["results"]["next_moves"] == [{"run_cmd": "./xctx repair offline:macro_intelligence_hub"}]
    crypto = run_engine(["discover", "crypto_intelligence_hub::"])
    assert crypto["results"]["status"] == "down_for_maintenance"
    assert crypto["results"]["repair_path"] is None

    filings = run_engine(["--more", "discover", "stock_intelligence_hub::equity_filing"])
    assert filings["results"]["live_data"]["stats"]["total_lookup_filings"] == 412
    assert filings["results"]["projection"] == "compact"
    assert "configured_action_index" in filings["results"]
    assert "configured_actions" not in filings["results"]
    filing_mode_ids = {item["id"] for item in filings["results"]["live_data"]["discoverable_modes"]}
    assert "search_forms" in filing_mode_ids
    assert "list_forms" in filing_mode_ids
    filings_full = run_engine(["discover", "stock_intelligence_hub::equity_filing", "--projection", "full"])
    assert filings_full["results"]["projection"] == "full"
    assert "modes" in filings_full["results"]["live_data"]
    market = run_engine(["--max", "discover", "stock_intelligence_hub::market_data_gateway"])
    assert market["results"]["live_data"]["stats"]["canonical_instruments"] >= 100
    assert market["results"]["projection"] == "compact"
    configured_observe_options = market["results"]["configured_options"]["observe"]
    assert [item["flags"][0] for item in configured_observe_options] == ["--bars", "--calendar-days", "--export"]
    assert configured_observe_options[0]["source"]["kind"] == "agent_subdomain_action"
    market_full = run_engine(["discover", "stock_intelligence_hub::market_data_gateway", "--projection", "full"])
    assert market_full["results"]["projection"] == "full"
    sample_series_ids = [item["market_series_id"] for item in market_full["results"]["live_data"]["sample_market_series"]]
    assert len(sample_series_ids) == len(set(sample_series_ids)), sample_series_ids
    assert all("latest_bar" not in item for item in market_full["results"]["live_data"]["sample_market_series"])

    file_domain = run_engine(["discover", "file_manager::"])
    assert_cmd(file_domain, record_type="discovery", level="agent_domain")
    assert file_domain["results"]["agent_subdomains"][0]["id"] == "home_directory"
    file_subdomain = run_engine(["--max", "discover", "file_manager::home_directory"])
    assert file_subdomain["results"]["projection"] == "compact"
    assert file_subdomain["results"]["live_data"]["connector"]["kind"] == "external_command"
    file_full = run_engine(["--max", "discover", "file_manager::home_directory", "--projection", "full"])
    assert file_full["results"]["projection"] == "full"
    assert file_full["results"]["live_data"]["external_commands"]["list"] == "ls -lt"

def assert_scoped_filing_affordance_routing() -> None:
    print("[pressure] scoped filing affordance routing", flush=True)
    invalid_unscoped = run_engine(["discover", "search_filing_family", "annual"], code=1)
    assert_cmd(invalid_unscoped, ok=False, record_type="error")
    assert invalid_unscoped["error"] == "unscoped discovery target: search_filing_family"
    assert invalid_unscoped["next_moves"] == [
        {"run_cmd": "./xctx discover stock_intelligence_hub::search_filing_family"}
    ]

    family = run_engine(["discover", "stock_intelligence_hub::search_filing_family", "annual"])
    assert any(item["id"] == "family:ANNUAL_REPORT" for item in family["results"]["live_data"]["matches"])
    assert len(family["results"]["live_data"]["matches"]) > 1
    priority = run_engine(["discover", "stock_intelligence_hub::search_priority_bucket", "critical"])
    assert priority["results"]["agent_subdomain_id"] == "stock_intelligence_hub::equity_filing"
    assert priority["results"]["agent_subdomain"]["subdomain_id"] == "equity_filing"
    assert priority["results"]["live_data"]["matches"][0]["id"] == "priority:critical_always"

    form_mode = run_engine(["discover", "stock_intelligence_hub::equity_filing::search_forms"])
    assert form_mode["results"]["object_type"] == "xctx_action_discovery_interface"
    assert form_mode["results"]["argument_patterns"]
    form_mode_alt = run_engine(["discover", "stock_intelligence_hub::equity_filing", "search_forms"], code=1)
    assert form_mode_alt["error"].startswith("non-canonical subdomain action form:")
    list_forms = run_engine(["discover", "stock_intelligence_hub::equity_filing::list_forms"])
    assert list_forms["results"]["live_data"]["object_type"] == "equity_filing_form_list"
    assert list_forms["results"]["live_data"]["projection"] == "compact"
    assert list_forms["results"]["live_data"]["forms"][0]["run_cmd"].startswith("./xctx observe ")
    list_forms_full = run_engine(["discover", "stock_intelligence_hub::equity_filing::list_forms", "--limit", "2", "--projection", "full"])
    assert list_forms_full["results"]["live_data"]["pagination"]["returned_count"] == 2
    assert "run_cmd" in list_forms_full["results"]["live_data"]["forms"][0]
    exact_10k = run_engine(["discover", "stock_intelligence_hub::equity_filing::search_forms", "10-K"])
    exact_10k_ids = [item["id"] for item in exact_10k["results"]["live_data"]["matches"]]
    assert exact_10k_ids == ["form:10-K", "form:10-K/A"]
    exact_8k = run_engine(["discover", "stock_intelligence_hub::search_filing_form", "8-K"])
    exact_8k_ids = [item["id"] for item in exact_8k["results"]["live_data"]["matches"]]
    assert exact_8k_ids == ["form:8-K", "form:8-K/A"]
    exact_family = run_engine(["discover", "stock_intelligence_hub::equity_filing::search_families", "ANNUAL_REPORT"])
    assert [item["id"] for item in exact_family["results"]["live_data"]["matches"]] == ["family:ANNUAL_REPORT"]


def assert_scoped_market_list_affordance() -> None:
    print("[pressure] scoped market list affordance", flush=True)
    instruments = run_engine(["discover", "stock_intelligence_hub::market_data_gateway::list_instruments", "--limit", "2"])
    assert instruments["results"]["live_data"]["projection"] == "compact"
    assert instruments["results"]["live_data"]["pagination"]["next_cursor"] == "2"


def assert_scoped_file_affordance_routing() -> None:
    print("[pressure] scoped file affordance routing", flush=True)
    file_list = run_engine(["discover", "file_manager::home_directory::list_files", "--limit", "2"])
    assert file_list["results"]["live_data"]["object_type"] == "external_command_filesystem_file_list"
    assert "connector" not in file_list["results"]["live_data"]
    assert file_list["results"]["live_data"]["files"][0]["id"] == "file:README.txt"
    assert file_list["results"]["live_data"]["pagination"]["returned_count"] == 1
    assert "external_command" not in file_list["results"]["live_data"]
    assert "command_status" not in file_list["results"]["live_data"]
    assert "This is a bundled file-manager demo fixture" not in json.dumps(file_list["results"]["live_data"])
    file_list_full = run_engine(["--max", "discover", "file_manager::home_directory::list_files", "--limit", "1", "--projection", "full"])
    assert file_list_full["results"]["live_data"]["pagination"]["returned_count"] == 1
    assert file_list_full["results"]["live_data"]["connector"]["payload_contract"]["failure_payload"] == "xctx_connector_error"
    assert file_list_full["results"]["live_data"]["command_status"]["argv"][0] == "ls"
    discovered_file = run_engine(["discover", "file_manager::home_directory", "file:README.txt"])
    assert discovered_file["results"]["live_data"]["object_type"] == "external_command_filesystem_file_discovery"
    assert "connector" not in discovered_file["results"]["live_data"]
    expected_readme_bytes = len(FILE_MANAGER_README.read_bytes())
    assert discovered_file["results"]["live_data"]["type"] == "ASCII text"
    assert discovered_file["results"]["live_data"]["size_bytes"] == expected_readme_bytes
    assert "file_id" not in discovered_file["results"]["live_data"]
    assert "file_type" not in discovered_file["results"]["live_data"]
    assert "external_commands" not in discovered_file["results"]["live_data"]
    assert "command_status" not in discovered_file["results"]["live_data"]
    assert "content" not in discovered_file["results"]["live_data"]
    assert "configured_action_index" not in discovered_file["results"]
    assert "This is a bundled file-manager demo fixture" not in json.dumps(discovered_file["results"]["live_data"])
    directory_list = run_engine(["discover", "file_manager::home_directory::list_directories"])
    assert "directory:docs" in {item["id"] for item in directory_list["results"]["live_data"]["directories"]}


def assert_market_identity_search() -> None:
    print("[pressure] market identity search", flush=True)
    market_mode = run_engine(["discover", "stock_intelligence_hub::market_data_gateway::search_entity_instrument"])
    assert market_mode["results"]["object_type"] == "xctx_action_discovery_interface"
    apple = run_engine(["discover", "stock_intelligence_hub::market_data_gateway::search_entity_instrument", "Apple"])
    live = apple["results"]["live_data"]
    assert live["matches_returned"] == 1
    assert live["matches"][0]["instrument_id"] == "instrument:aapl"
    assert "related_market_series" not in live
    assert any(move["run_cmd"].endswith("search_market_series AAPL") for move in live["matches"][0]["next_moves"])
    name_shortcut = run_engine(["discover", "--name", "Apple"], code=1)
    assert_cmd(name_shortcut, ok=False, record_type="error")
    assert "unrecognized arguments: --name" in name_shortcut["error"]
    apple_punct = run_engine(["discover", "stock_intelligence_hub::market_data_gateway::search_entity_instrument", "Apple, Inc."])
    assert apple_punct["results"]["live_data"]["matches"][0]["resolver_match"]["reason"] == "normalized_name_exact"
    apple_cik = run_engine(["discover", "stock_intelligence_hub::search_entity_instrument", "issuer:cik:0000320193"])
    assert apple_cik["results"]["live_data"]["matches"][0]["resolver_match"]["reason"] == "exact_cik"
    fb = run_engine(["discover", "stock_intelligence_hub::search_entity_instrument", "FB"])
    assert fb["results"]["live_data"]["matches_returned"] == 1
    assert fb["results"]["live_data"]["matches"][0]["ticker"] == "META"

    ticker_a = run_engine(["discover", "stock_intelligence_hub::market_data_gateway::search_entity_instrument", "A"])
    live_a = ticker_a["results"]["live_data"]
    assert live_a["total_matches"] >= 50
    assert live_a["matches_returned"] == 10
    assert live_a["matches"][0]["ticker"] == "A"
    assert live_a["matches"][0]["instrument_id"] == "instrument:a"

    series = run_engine(["discover", "stock_intelligence_hub::search_market_series", "AAPL"])
    assert series["results"]["live_data"]["matches"][0]["market_series_id"] == "market_series:aapl:daily"
    assert "latest_bar" not in series["results"]["live_data"]["matches"][0]
    series_by_cik = run_engine(["discover", "stock_intelligence_hub::search_market_series", "320193"])
    assert series_by_cik["results"]["live_data"]["matches"][0]["market_series_id"] == "market_series:aapl:daily"
    assert "latest_bar" not in series_by_cik["results"]["live_data"]["matches"][0]
    msft_series = run_engine(["discover", "stock_intelligence_hub::search_market_series", "MSFT"])
    assert msft_series["results"]["live_data"]["matches"] == []
    assert "Known instrument MSFT was resolved" in msft_series["results"]["live_data"]["empty_result_guidance"]
    latest = run_engine(["discover", "stock_intelligence_hub::latest_price", "AAPL"])
    assert latest["results"]["live_data"]["object_type"] == "market_data_gateway_latest_price_discovery"
    assert latest["results"]["live_data"]["observe_cmd"] == "./xctx observe stock_intelligence_hub::market_data_gateway AAPL"
    assert "latest_available_price" not in latest["results"]["live_data"]
    msft_latest = run_engine(["discover", "stock_intelligence_hub::latest_price", "MSFT"])
    assert msft_latest["results"]["live_data"]["found"] is False
    assert "Known instrument MSFT was resolved" in msft_latest["results"]["live_data"]["empty_result_guidance"]
    broad_series = run_engine(["discover", "stock_intelligence_hub::market_data_gateway::search_market_series", "A"])
    broad_ids = [item["market_series_id"] for item in broad_series["results"]["live_data"]["matches"]]
    assert len(broad_ids) == len(set(broad_ids)), broad_ids

def assert_market_observe_range_semantics() -> None:
    print("[pressure] market observe/range semantics", flush=True)
    observed = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "instrument:aapl"])
    assert_cmd(observed, record_type="observation", level="agent_subdomain")
    assert observed["results"]["live_data"]["instrument_id"] == "instrument:aapl"
    assert "market_series" not in observed["results"]["live_data"]
    assert "latest_available_price" not in observed["results"]["live_data"]
    observed_more = run_engine(["--more", "observe", "stock_intelligence_hub::market_data_gateway", "instrument:aapl"])
    assert observed_more["results"]["live_data"]["latest_available_price"]["is_live_quote"] is False
    observed_former = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "FB"])
    assert observed_former["results"]["live_data"]["ticker"] == "META"
    assert observed_former["results"]["live_data"]["market_series_available"] is False
    observed_series = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "market_series:a:daily"])
    series_live = observed_series["results"]["live_data"]
    assert series_live["latest_bar"] == series_live["sample_bars_last_5"][-1]
    sample_dates = [bar["date"] for bar in series_live["sample_bars_last_5"]]
    assert len(sample_dates) == len(set(sample_dates)), sample_dates
    ranged_small = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "market_series:aapl:daily", "--bars", "5"])
    small_live = ranged_small["results"]["live_data"]
    assert small_live["returned_bars"] == 5
    assert small_live["bars_inline"] is True
    assert len(small_live["bars"]) == 5
    assert small_live["price_summary"]["last_close"] == small_live["bars"][-1]["close"]
    assert "csv" not in small_live
    assert small_live["export"]["csv_written"] is False
    exported = run_engine([
        "observe",
        "stock_intelligence_hub::market_data_gateway",
        "market_series:aapl:daily",
        "--bars",
        "5",
        "--export",
        "csv",
    ])
    exported_live = exported["results"]["live_data"]
    assert re.fullmatch(r"instrument_aapl_5_bars_[0-9a-f]{8}\.csv", Path(exported_live["csv"]["path"]).name)
    assert (ROOT / exported_live["csv"]["path"]).exists()
    ranged_large = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "instrument:aapl", "--bars", "31"])
    assert ranged_large["results"]["live_data"]["bars_inline"] is False
    assert ranged_large["results"]["live_data"]["bars_omitted_from_json"] == 31
    all_calendar = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--calendar-days", "0"])
    assert all_calendar["results"]["live_data"]["request"]["all_available"] is True
    assert all_calendar["results"]["live_data"]["returned_bars"] >= 1000
    calendar_50 = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--calendar-days", "50"])
    assert calendar_50["results"]["live_data"]["request"] == {"unit": "calendar_days", "value": 50, "all_available": False}


def assert_observe_error_and_cross_domain_routes() -> None:
    print("[pressure] observe error and cross-domain routes", flush=True)
    unsupported_range = run_engine(["observe", "stock_intelligence_hub::equity_filing", "form:10-K", "--bars", "5"], code=1)
    assert unsupported_range["error"] == "unsupported option --bars for stock_intelligence_hub::equity_filing observe"
    missing_range_target = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "--bars", "5"], code=1)
    assert missing_range_target["error"] == "missing observation target before configured observe options"
    spaced_form = run_engine(["observe", "stock_intelligence_hub::equity_filing", "form:DEF 14A"])
    assert spaced_form["results"]["agent_subdomain_id"] == "stock_intelligence_hub::equity_filing"
    assert spaced_form["results"]["agent_subdomain"]["subdomain_id"] == "equity_filing"
    assert spaced_form["results"]["live_data"]["id"] == "form:DEF 14A"
    range_conflict = run_engine(
        ["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--bars", "1", "--calendar-days", "1"],
        code=1,
    )
    assert "choose either --bars or --calendar-days" in range_conflict["error"]
    filing_context = run_engine(["observe", "stock_intelligence_hub::equity_filing", "instrument:aapl"])
    assert filing_context["results"]["live_data"]["context_state"] == "with_equity"
    assert filing_context["results"]["live_data"]["issuer_submission_feed_status"] == "offline_not_bundled"
    observed_file = run_engine(["--max", "observe", "file_manager::home_directory", "file:README.txt"])
    assert observed_file["results"]["agent_domain"] == "file_manager"
    assert observed_file["results"]["live_data"]["object_type"] == "external_command_filesystem_file_observation"
    assert observed_file["results"]["live_data"]["connector"]["payload_contract"]["success_payload"] == "domain_object"
    assert observed_file["results"]["live_data"]["content"]["available"] is True
    assert "This is a bundled file-manager demo fixture" in observed_file["results"]["live_data"]["content"]["text"]
    observed_directory = run_engine(["observe", "file_manager::home_directory", "directory:docs"])
    assert observed_directory["results"]["live_data"]["directory_id"] == "directory:docs"
    escaped_file = run_engine(["--max", "observe", "file_manager::home_directory", "file:../README.md"], code=1)
    assert_cmd(escaped_file, ok=False, record_type="observation", level="agent_subdomain")
    assert escaped_file["error"] == "path escapes configured safe root"
    assert escaped_file["results"]["live_data"]["object_type"] == "xctx_connector_error"
    assert escaped_file["results"]["live_data"]["found"] is False
    assert escaped_file["results"]["live_data"]["connector"]["payload_contract"]["failure_payload"] == "xctx_connector_error"


def assert_audit_scope_results() -> None:
    print("[pressure] audit scope results", flush=True)
    audit = run_engine(["--max", "audit", "root"])
    assert_cmd(audit, record_type="audit", level="root")
    assert audit["results"]["summary"]["checks_total"] >= 9
    check_ids = {item["id"] for item in audit["results"]["checks"]}
    assert "audit:xctx:config_fingerprint" in check_ids
    assert "audit:market_data_gateway:aapl_latest_price_resolves" in check_ids
    assert "audit:market_data_gateway:mini_stocks_sqlite_exists" in check_ids
    assert "audit:file_manager:home_directory:external_command:ls" in check_ids
    findings = {item["id"]: item for item in audit["results"]["findings"]}
    assert findings["down_for_maintenance:stock_intelligence_hub::fundamentals_gateway"]["repairable"] is False
    market_audit = run_engine(["--max", "audit", "stock_intelligence_hub::market_data_gateway"])
    assert_cmd(market_audit, record_type="audit", level="agent_subdomain")
    market_check_ids = {item["id"] for item in market_audit["results"]["checks"]}
    assert "audit:market_data_gateway:aapl_latest_price_resolves" in market_check_ids
    file_audit = run_engine(["--max", "audit", "file_manager::home_directory"])
    assert_cmd(file_audit, record_type="audit", level="agent_subdomain")
    file_check_ids = {item["id"] for item in file_audit["results"]["checks"]}
    assert "audit:file_manager:home_directory:external_command:ls" in file_check_ids


def assert_repair_results() -> None:
    print("[pressure] repair results", flush=True)
    repaired = run_engine(["repair", "offline:macro_intelligence_hub"])
    assert_cmd(repaired, record_type="repair_result", level="agent_domain")
    assert repaired["results"]["next_moves"][0]["writes_protocol_ledger"] is True
    assert repaired["results"]["next_moves"][0]["domain_mutation"] is False
    terminal = run_engine(["--max", "repair", "down_for_maintenance:stock_intelligence_hub::fundamentals_gateway"], code=1)
    assert terminal["error"] == "down_for_maintenance"
    assert terminal["results"]["repair_path"] is None


def assert_plan_execute_binding() -> None:
    print("[pressure] plan/execute binding", flush=True)
    random_short = run_engine(["execute", "abcde", "--commit"], code=1)
    assert random_short["error"] == "plan_id_required"
    random_full = run_engine(["execute", "plan:sha256:" + "a" * 64, "--commit"], code=1)
    assert random_full["error"] == "unknown_plan_receipt"

    plan = run_engine(
        [
            "plan",
            "guess_the_number_game::choose_random_number::choose_between_bounds",
            "--minimum",
            "1",
            "--maximum",
            "10",
        ]
    )
    results = plan["results"]
    assert re.fullmatch(r"[0-9a-f]{64}", results["receipt_sha256"])
    assert re.fullmatch(r"[0-9a-f]{5}", results["receipt_sha5"])
    runtime_root = Path(os.environ.get("XCTX_RUNTIME_DIR", ROOT / ".xctx_runtime"))
    assert (runtime_root / "plans" / f"{results['receipt_sha256']}.json").exists()
    no_commit = run_engine(["execute", results["plan_id"]], code=1)
    assert no_commit["error"] == "commit_required"
    execute_full = run_engine(["--max", "execute", results["plan_id"], "--commit"])
    assert execute_full["results"]["planner_binding"]["verified"] is True

def assert_extension_lane_discipline() -> None:
    print("[pressure] extension lane discipline", flush=True)
    for rejected_command in ("d", "identify", "status", "write", "doctor"):
        payload = run_engine([rejected_command], code=1)
        assert_cmd(payload, ok=False, record_type="error")
        assert payload["error"] == "unknown xctx command"
        assert "other" not in payload["error"]
    old_group_as_command = run_engine(["xctx_other", "other", "--topic", "ping"], code=1)
    assert_cmd(old_group_as_command, ok=False, record_type="error")
    assert old_group_as_command["error"] == "unknown xctx command"
    assert "other" not in old_group_as_command["error"]
    other = run_engine(["other", "--topic", "something-new"])
    assert_cmd(other, record_type="extension")
    assert other["results"]["topic"] == "something-new"

def assert_real_cli_launcher_and_ledger_probe() -> None:
    print("[pressure] ledger probe; real CLI launcher is covered by the local gate", flush=True)
    root = run_engine(["discover"])
    assert_cmd(root, record_type="discovery", level="root")
    unknown = run_engine(["execute", "abcde", "--commit"], code=1)
    assert unknown["error"] == "plan_id_required"
    plan = run_engine(
        [
            "plan",
            "guess_the_number_game::choose_random_number::choose_between_bounds",
            "--minimum",
            "1",
            "--maximum",
            "10",
        ]
    )
    executed = run_engine(["--max", "execute", plan["results"]["plan_id"], "--commit"])
    assert executed["results"]["planner_binding"]["verified"] is True

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = xctx_main(["--json", "--yaml", "discover"], root=ROOT)
    assert rc == 1
    assert err.getvalue() == ""
    assert json.loads(out.getvalue())["error"] == "conflicting stdout format flags: --json and --yaml"

def main() -> int:
    assert_root_universe_command_surface()
    assert_domain_subdomain_discovery()
    assert_scoped_filing_affordance_routing()
    assert_scoped_market_list_affordance()
    assert_scoped_file_affordance_routing()
    assert_market_identity_search()
    assert_market_observe_range_semantics()
    assert_observe_error_and_cross_domain_routes()
    assert_audit_scope_results()
    assert_repair_results()
    assert_plan_execute_binding()
    assert_extension_lane_discipline()
    assert_real_cli_launcher_and_ledger_probe()
    print("PRO xctx protocol pressure checks passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
