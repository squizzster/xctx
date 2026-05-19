#!/usr/bin/env python3
"""Protocol smoke checks for the hardened v4.2 xctx proof-of-concept."""

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

import yaml  # noqa: E402
from xctx.process.runtime import main as xctx_main  # noqa: E402


class TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


def parse_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def parse_yaml_stream(text: str) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(text) if doc is not None]


def capture_engine(
    args: Iterable[str],
    env: dict[str, str] | None = None,
    expected_code: int = 0,
    stdout: io.StringIO | None = None,
) -> tuple[str, str]:
    old_env: dict[str, str | None] = {}
    if env:
        for key, value in env.items():
            old_env[key] = os.environ.get(key)
            os.environ[key] = value
    out = stdout or io.StringIO()
    err = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = xctx_main(list(args), root=ROOT)
    finally:
        if env:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    assert code == expected_code, out.getvalue() + err.getvalue()
    assert err.getvalue() == "", err.getvalue()
    return out.getvalue(), err.getvalue()


def run_engine(args: Iterable[str], env: dict[str, str] | None = None, expected_code: int = 0) -> list[dict]:
    out, _err = capture_engine(args, env=env, expected_code=expected_code)
    return parse_jsonl(out)


def run_yaml_engine(
    args: Iterable[str],
    env: dict[str, str] | None = None,
    expected_code: int = 0,
    stdout: io.StringIO | None = None,
) -> list[dict]:
    out, _err = capture_engine(args, env=env, expected_code=expected_code, stdout=stdout)
    assert out.startswith("---\n"), out
    return parse_yaml_stream(out)


def one(args: Iterable[str], env: dict[str, str] | None = None, expected_code: int = 0) -> dict:
    parsed = run_engine(args, env=env, expected_code=expected_code)
    assert len(parsed) == 1, parsed
    return parsed[0]


def assert_no_description_variants(value: object) -> None:
    if isinstance(value, dict):
        assert "basic_description" not in value, value
        assert "full_description" not in value, value
        for child in value.values():
            assert_no_description_variants(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_description_variants(child)


def assert_root_surface_clean(payload: object) -> None:
    text = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "--bars",
        "--calendar-days",
        "configured_options",
        "root_affordances",
        "search_entity_instrument",
        "search_market_series",
        "latest_price",
        "latest-price",
    ):
        assert forbidden not in text, forbidden


def assert_modular_layout() -> None:
    expected = [
        "xctx",
        "bin/xctx",
        "libs/xctx/cli.py",
        "libs/xctx/process/runtime.py",
        "libs/xctx/domain/agent_domains.py",
        "libs/xctx/ports/external_command.py",
        "libs/xctx_live/filings.py",
        "libs/xctx_live/instruments.py",
        "equity_filings.py",
        "equity_instruments.py",
        "market_data_gateway.py",
        "yaml_dynamic_config/protocols/xctx_v4_2.yaml",
        "yaml_dynamic_config/shared/command_sets/core_commands.yaml",
        "yaml_dynamic_config/universe.yaml",
        "yaml_dynamic_config/agent_domains/stock_intelligence_hub/domain.yaml",
        "yaml_dynamic_config/agent_domains/stock_intelligence_hub/subdomains/equity_filing/subdomain.yaml",
        "yaml_dynamic_config/agent_domains/stock_intelligence_hub/subdomains/market_data_gateway/subdomain.yaml",
        "data/edgar_form_reference_taxonomy.sqlite",
        "data/mini_stocks.sqlite",
    ]
    for rel in expected:
        assert (ROOT / rel).exists(), rel
    launcher = (ROOT / "bin" / "xctx").read_text(encoding="utf-8")
    assert "from xctx.cli import main" in launcher


def assert_protocol_is_config_driven() -> None:
    protocol = yaml.safe_load((ROOT / "yaml_dynamic_config" / "protocols" / "xctx_v4_2.yaml").read_text())
    assert protocol["command_groups"]["main"] == ["discover", "observe", "plan", "execute", "audit", "repair"]
    assert protocol["command_groups"]["other"] == ["other"]
    assert protocol["command_aliases"]["discover"] == ["discovery"]
    universe = yaml.safe_load((ROOT / "yaml_dynamic_config" / "universe.yaml").read_text())
    assert "command_shortcuts" not in universe
    assert "root_affordances" not in universe
    assert universe["identity_resolution"]["query_fields"] == ["name", "id", "aliases"]
    market_subdomain = yaml.safe_load((ROOT / "yaml_dynamic_config" / "agent_domains" / "stock_intelligence_hub" / "subdomains" / "market_data_gateway" / "subdomain.yaml").read_text())
    assert market_subdomain["actions"]["search_entity_instrument"]["domain_affordance"] is True
    assert market_subdomain["actions"]["latest_price"]["domain_affordance"] is True
    assert market_subdomain["actions"]["latest_price"]["entrypoint_command"] == "latest-price"
    observe_flags = [option["flags"][0] for option in market_subdomain["actions"]["observe"]["cli_options"]]
    assert observe_flags == ["--bars", "--calendar-days"]
    filing_subdomain = yaml.safe_load((ROOT / "yaml_dynamic_config" / "agent_domains" / "stock_intelligence_hub" / "subdomains" / "equity_filing" / "subdomain.yaml").read_text())
    assert filing_subdomain["actions"]["search_forms"]["domain_affordance"] is True
    assert filing_subdomain["actions"]["search_forms"]["domain_action_name"] == "search_filing_form"

    runtime = (ROOT / "libs" / "xctx" / "domain" / "agent_domains.py").read_text(encoding="utf-8")
    for forbidden_literal in ("stock_intelligence_hub", "market_data_gateway", "equity_filing"):
        assert forbidden_literal not in runtime, forbidden_literal
    for core_rel in (
        "libs/xctx/process/parser.py",
        "libs/xctx/commands/observe.py",
        "libs/xctx/domain/agent_domains.py",
        "libs/xctx/commands/discover.py",
        "libs/xctx/domain/identity.py",
        "libs/xctx/commands/identify.py",
    ):
        text = (ROOT / core_rel).read_text(encoding="utf-8")
        for forbidden_literal in ("--bars", "--calendar-days", "search_entity_instrument", "latest_price", "latest-price", "ticker", "symbol"):
            assert forbidden_literal not in text, (core_rel, forbidden_literal)


def assert_root_domain_subdomain_discovery() -> None:
    universe = one([])
    assert universe["record_type"] == "discovery"
    assert universe["domain_level"] == "universe"
    assert universe["results"]["xctx"]["id"] == "xctx"
    assert "discover" in universe["results"]["command_surface"]["xctx"]
    assert "identify" not in universe["results"]["command_surface"]["xctx"]
    assert universe["results"]["command_surface"]["aliases"]["discover"] == ["discovery"]
    assert_no_description_variants(universe)
    assert_root_surface_clean(universe)

    help_payload = one(["help"])
    assert_root_surface_clean(help_payload)

    version = one(["--version"])
    assert version["record_type"] == "version"
    assert version["ok"] is True
    assert version["results"]["version_xctx"] == "v4.2"
    assert version["results"]["kind"] == "executable_context_protocol"
    assert "description" in version["results"]
    assert_root_surface_clean(version)

    root = one(["discover"])
    assert root["domain_level"] == "root"
    root_results = root["results"]
    assert_root_surface_clean(root)
    assert "configured_options" not in root_results
    assert "root_affordances" not in root_results
    domains = {item["id"]: item for item in root_results["agent_domains"]}
    assert domains["stock_intelligence_hub"]["status"] == "online"
    assert domains["macro_intelligence_hub"]["status"] == "offline"
    assert domains["crypto_intelligence_hub"]["status"] == "down_for_maintenance"
    assert domains["options_intelligence_hub"]["repair_cmd"] == "./xctx repair offline:options_intelligence_hub"
    assert root_results["next_moves"] == ["./xctx discover stock_intelligence_hub::", "./xctx audit root"]

    alias_root = one(["discovery"])
    assert alias_root["domain_level"] == "root"

    domain = one(["discover", "stock_intelligence_hub::"])
    assert domain["domain_level"] == "agent_domain"
    subdomains = {item["id"]: item for item in domain["results"]["agent_subdomains"]}
    assert subdomains["market_data_gateway"]["status"] == "online"
    assert subdomains["equity_filing"]["status"] == "online"
    assert subdomains["fundamentals_gateway"]["terminal_reason"] == "down_for_maintenance"
    assert "latest_price" in domain["results"]["domain_affordances"]
    assert "search_filing_form" in domain["results"]["domain_affordances"]

    domain_without_colons = one(["discover", "stock_intelligence_hub"])
    assert domain_without_colons["domain_level"] == "agent_domain"

    filing = one(["discover", "stock_intelligence_hub::equity_filing"])
    assert filing["domain_level"] == "agent_subdomain"
    filing_live = filing["results"]["live_data"]
    assert filing_live["object_type"] == "equity_filing_discovery"
    assert filing_live["stats"]["total_lookup_filings"] == 412
    assert filing_live["stats"]["canonical_families"] == 41
    assert filing_live["stats"]["priority_buckets"] == 12
    assert filing_live["stats"]["amendment_forms"] == 176

    market = one(["discover", "stock_intelligence_hub::market_data_gateway"])
    assert market["domain_level"] == "agent_subdomain"
    market_live = market["results"]["live_data"]
    assert market_live["object_type"] == "market_data_gateway_discovery"
    assert market_live["stats"]["reference_universe_snapshots"] == 100
    assert market_live["stats"]["canonical_instruments"] >= 100
    observe_options = market["results"]["configured_options"]["observe"]
    assert [item["flags"][0] for item in observe_options] == ["--bars", "--calendar-days"]
    assert observe_options[0]["source"]["agent_subdomain"] == "market_data_gateway"
    sample_series_ids = [item["market_series_id"] for item in market_live["sample_market_series"]]
    assert len(sample_series_ids) == len(set(sample_series_ids)), sample_series_ids


def assert_scoped_affordance_routing() -> None:
    priority = one(["discover", "stock_intelligence_hub::search_priority_bucket", "critical"])
    assert priority["domain_level"] == "agent_subdomain"
    assert priority["results"]["action"] == "search_priority_bucket"
    assert priority["results"]["agent_subdomain"] == "equity_filing"
    assert priority["results"]["live_data"]["matches"][0]["id"] == "priority:critical_always"

    shorthand = one(["stock_intelligence_hub::search_priority_bucket", "critical"])
    assert shorthand["cmdline_arg"] == "stock_intelligence_hub::search_priority_bucket critical"
    assert shorthand["results"]["live_data"]["matches"][0]["id"] == "priority:critical_always"

    unscoped = one(["discover", "search_filing_family", "annual"], expected_code=1)
    assert unscoped["record_type"] == "error"
    assert unscoped["ok"] is False
    assert "./xctx discover stock_intelligence_hub::search_filing_family" in unscoped["error"]

    form = one(["discover", "stock_intelligence_hub::equity_filing", "search_forms", "10-K"])
    assert form["results"]["action"] == "search_forms"
    assert form["results"]["live_data"]["object_type"] == "equity_filing::search_filing_form::result"
    assert form["results"]["live_data"]["matches"][0]["id"] == "form:10-K"

    missing_root_query = one(["discover", "stock_intelligence_hub::search_entity_instrument"])
    assert missing_root_query["ok"] is True
    assert missing_root_query["results"]["object_type"] == "xctx_action_discovery_interface"
    assert missing_root_query["results"]["query_required"] is True
    assert "live_data" not in missing_root_query["results"]

    missing_subdomain_query = one(["discover", "stock_intelligence_hub::market_data_gateway", "search_entity_instrument"])
    assert missing_subdomain_query["ok"] is True
    assert missing_subdomain_query["results"]["object_type"] == "xctx_action_discovery_interface"
    assert missing_subdomain_query["results"]["query_required"] is True
    assert "live_data" not in missing_subdomain_query["results"]

    family = one(["discover", "stock_intelligence_hub::search_filing_family", "annual"])
    assert any(item["id"] == "family:ANNUAL_REPORT" for item in family["results"]["live_data"]["matches"])

    apple_scoped = one(["discover", "stock_intelligence_hub::search_entity_instrument", "Apple"])
    assert apple_scoped["results"]["agent_subdomain"] == "market_data_gateway"
    assert apple_scoped["results"]["live_data"]["matches"][0]["instrument_id"] == "instrument:aapl"

    apple_name_shortcut = one(["discover", "--name", "Apple"], expected_code=1)
    assert apple_name_shortcut["ok"] is False
    assert "use a scoped discovery action" in apple_name_shortcut["error"]

    apple_full = one(["discover", "stock_intelligence_hub::market_data_gateway", "search_entity_instrument", "Apple"])
    live = apple_full["results"]["live_data"]
    assert live["object_type"] == "market_data_gateway::search_entity_instrument::result"
    assert live["query"] == "Apple"
    assert live["matches_returned"] == 1
    assert "related_market_series" not in live
    assert live["matches"][0]["instrument_id"] == "instrument:aapl"
    assert any(move["run_cmd"].endswith("search_market_series AAPL") for move in live["matches"][0]["next_moves"])

    apple_punct = one(["discover", "stock_intelligence_hub::market_data_gateway", "search_entity_instrument", "Apple, Inc."])
    assert apple_punct["results"]["live_data"]["matches"][0]["resolver_match"]["reason"] == "normalized_name_exact"
    assert apple_punct["results"]["live_data"]["matches"][0]["ticker"] == "AAPL"

    apple_cik = one(["discover", "stock_intelligence_hub::search_entity_instrument", "issuer:cik:0000320193"])
    assert apple_cik["results"]["live_data"]["matches"][0]["resolver_match"]["reason"] == "exact_cik"
    assert apple_cik["results"]["live_data"]["matches"][0]["ticker"] == "AAPL"

    apple_cik_unpadded = one(["discover", "stock_intelligence_hub::search_entity_instrument", "320193"])
    assert apple_cik_unpadded["results"]["live_data"]["matches"][0]["ticker"] == "AAPL"

    former_ticker = one(["discover", "stock_intelligence_hub::search_entity_instrument", "FB"])
    assert former_ticker["results"]["live_data"]["matches_returned"] == 1
    assert former_ticker["results"]["live_data"]["matches"][0]["ticker"] == "META"
    assert former_ticker["results"]["live_data"]["matches"][0]["resolver_match"]["reason"] == "exact_alias"

    ticker_a = one(["discover", "stock_intelligence_hub::market_data_gateway", "search_entity_instrument", "A"])
    live_a = ticker_a["results"]["live_data"]
    assert live_a["total_matches"] > 10
    assert live_a["matches_returned"] == 10
    assert live_a["matches"][0]["ticker"] == "A"
    assert live_a["matches"][0]["instrument_id"] == "instrument:a"

    series = one(["discover", "stock_intelligence_hub::search_market_series", "AAPL"])
    assert series["results"]["live_data"]["matches"][0]["market_series_id"] == "market_series:aapl:daily"
    series_by_cik = one(["discover", "stock_intelligence_hub::search_market_series", "issuer:cik:0000320193"])
    assert series_by_cik["results"]["live_data"]["matches"][0]["market_series_id"] == "market_series:aapl:daily"
    latest = one(["discover", "stock_intelligence_hub::latest_price", "AAPL"])
    latest_live = latest["results"]["live_data"]
    assert latest_live["object_type"] == "market_data_gateway_latest_price_observation"
    assert latest_live["found"] is True
    assert latest_live["latest_available_price"]["price"] == latest_live["latest_available_price"]["close"]
    assert latest_live["latest_available_price"]["is_live_quote"] is False
    latest_subdomain = one(["discover", "stock_intelligence_hub::market_data_gateway", "latest_price", "issuer:cik:0000320193"])
    assert latest_subdomain["results"]["live_data"]["ticker"] == "AAPL"
    broad_series = one(["discover", "stock_intelligence_hub::market_data_gateway", "search_market_series", "A"])
    broad_ids = [item["market_series_id"] for item in broad_series["results"]["live_data"]["matches"]]
    assert len(broad_ids) == len(set(broad_ids)), broad_ids


def assert_observe_audit_repair() -> None:
    observed = one(["observe", "instrument:aapl"])
    assert observed["record_type"] == "observation"
    assert observed["results"]["agent_subdomain"] == "market_data_gateway"
    assert observed["results"]["live_data"]["instrument_id"] == "instrument:aapl"
    assert observed["results"]["live_data"]["latest_available_price"]["is_live_quote"] is False

    observed_former = one(["observe", "stock_intelligence_hub::market_data_gateway", "FB"])
    assert observed_former["results"]["live_data"]["ticker"] == "META"
    assert observed_former["results"]["live_data"]["market_series_available"] is False

    observed_series = one(["observe", "stock_intelligence_hub::market_data_gateway", "market_series:a:daily"])
    series_live = observed_series["results"]["live_data"]
    assert series_live["latest_bar"] == series_live["sample_bars_last_5"][-1]

    ranged_small = one(["observe", "stock_intelligence_hub::market_data_gateway", "market_series:aapl:daily", "--bars", "5"])
    small_live = ranged_small["results"]["live_data"]
    assert small_live["object_type"] == "market_data_gateway_market_series_range_observation"
    assert small_live["request"] == {"unit": "bars", "value": 5, "all_available": False}
    assert small_live["returned_bars"] == 5
    assert small_live["bars_inline"] is True
    assert len(small_live["bars"]) == 5
    assert small_live["price_summary"]["last_close"] == small_live["bars"][-1]["close"]
    assert small_live["price_summary"]["first_close"] == small_live["bars"][0]["close"]
    assert re.fullmatch(r"\.xctx_runtime/exports/instrument_aapl_5_bars_[0-9a-f]{8}\.csv", small_live["csv"]["path"])
    assert (ROOT / small_live["csv"]["path"]).exists()

    ranged_large = one(["observe", "stock_intelligence_hub::market_data_gateway", "instrument:aapl", "--bars", "31"])
    large_live = ranged_large["results"]["live_data"]
    assert large_live["returned_bars"] == 31
    assert large_live["bars_inline"] is False
    assert "bars" not in large_live
    assert large_live["bars_omitted_from_json"] == 31

    calendar_window = one(["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--calendar-days", "50"])
    calendar_live = calendar_window["results"]["live_data"]
    assert calendar_live["request"] == {"unit": "calendar_days", "value": 50, "all_available": False}
    assert calendar_live["returned_bars"] >= 30

    unsupported_option = one(["observe", "form:10-K", "--bars", "5"], expected_code=1)
    assert unsupported_option["ok"] is False
    assert "remove unsupported option --bars for stock_intelligence_hub::equity_filing observe" in unsupported_option["error"]

    conflict = one(["observe", "AAPL", "--bars", "1", "--calendar-days", "1"], expected_code=1)
    assert "choose either --bars or --calendar-days" in conflict["error"]

    filing_context = one(["observe", "stock_intelligence_hub::equity_filing", "instrument:aapl"])
    assert filing_context["results"]["live_data"]["context_state"] == "with_equity"
    assert filing_context["results"]["live_data"]["issuer_submission_feed_status"] == "offline_not_bundled"
    assert filing_context["results"]["live_data"]["instrument"]["market_series_run_cmd"].startswith(
        "./xctx observe stock_intelligence_hub::market_data_gateway"
    )

    observed_form = one(["observe", "form:10-K"])
    assert observed_form["results"]["agent_subdomain"] == "equity_filing"
    assert observed_form["results"]["live_data"]["canonical_family"]["code"] == "ANNUAL_REPORT"

    observed_spaced_form = one(["observe", "DEF", "14A"])
    assert observed_spaced_form["results"]["agent_subdomain"] == "equity_filing"
    assert observed_spaced_form["results"]["live_data"]["id"] == "form:DEF 14A"

    missing_range_target = one(["observe", "stock_intelligence_hub::market_data_gateway", "--bars", "5"], expected_code=1)
    assert "provide an observation target before configured observe options" in missing_range_target["error"]

    offline_domain = one(["observe", "macro_intelligence_hub"], expected_code=1)
    assert offline_domain["ok"] is False
    assert offline_domain["error"] == "offline"
    assert offline_domain["results"]["repair_cmd"] == "./xctx repair offline:macro_intelligence_hub"

    maintenance_subdomain = one(["observe", "stock_intelligence_hub::fundamentals_gateway"], expected_code=1)
    assert maintenance_subdomain["ok"] is False
    assert maintenance_subdomain["error"] == "down_for_maintenance"
    assert maintenance_subdomain["results"]["repair_path"] is None

    audit = one(["audit", "root"])
    assert audit["record_type"] == "audit"
    assert audit["results"]["summary"]["checks"] >= 17
    findings = {item["id"]: item for item in audit["results"]["findings"]}
    assert findings["down_for_maintenance:stock_intelligence_hub::fundamentals_gateway"]["repairable"] is False
    assert findings["offline:macro_intelligence_hub"]["repairable"] is True
    assert findings["down_for_maintenance:crypto_intelligence_hub"]["repair_cmd"] is None

    repairable = one(["repair", "offline:macro_intelligence_hub"])
    assert repairable["record_type"] == "repair_result"
    assert repairable["ok"] is True
    assert repairable["results"]["repair_path"]["steps"]

    maintenance = one(["repair", "down_for_maintenance:stock_intelligence_hub::fundamentals_gateway"], expected_code=1)
    assert maintenance["ok"] is False
    assert maintenance["error"] == "down_for_maintenance"
    assert maintenance["results"]["repair_path"] is None
    assert "down for maintenance" in maintenance["results"]["message"]


def assert_plan_execute_other_and_output() -> None:
    plan = one(["plan", "bring_online", "stock_intelligence_hub::market_data_gateway"])
    results = plan["results"]
    assert plan["record_type"] == "plan"
    assert re.fullmatch(r"[0-9a-f]{64}", results["planner_id"])
    assert results["plan_id"] == f"plan:sha256:{results['planner_id']}"
    assert results["receipt_sha256"] == results["planner_id"]
    assert len(results["receipt_sha5"]) == 5

    execute_full = one(["execute", results["plan_id"], "--commit"])
    assert execute_full["record_type"] == "execution_result"
    assert execute_full["ok"] is True
    assert execute_full["results"]["mutations_applied"] == 0

    execute_short = one(["execute", results["receipt_sha5"], "--commit"])
    assert execute_short["ok"] is True
    assert execute_short["results"]["planner_binding"]["verified"] is True
    assert execute_short["results"]["planner_binding"]["receipt_sha256"] == results["receipt_sha256"]

    refused = one(["execute", "not-a-plan", "--commit"], expected_code=1)
    assert refused["ok"] is False
    assert refused["error"] == "invalid_plan_receipt"

    unknown_short_receipt = one(["execute", "abcde", "--commit"], expected_code=1)
    assert unknown_short_receipt["ok"] is False
    assert unknown_short_receipt["error"] == "unknown_plan_receipt"

    no_commit = one(["execute", results["plan_id"]], expected_code=1)
    assert no_commit["ok"] is False
    assert no_commit["error"] == "commit_required"

    unknown_command = one(["something-new"], expected_code=1)
    assert unknown_command["record_type"] == "error"
    assert "./xctx other --topic something-new" in unknown_command["error"]

    other = one(["other", "--topic", "something-new"])
    assert other["record_type"] == "extension"
    assert other["results"]["topic"] == "something-new"

    explicit_yaml = run_yaml_engine(["--yaml", "discover"])
    assert explicit_yaml[0]["domain_level"] == "root"
    tty_yaml = run_yaml_engine(["discover"], stdout=TtyStringIO())
    assert tty_yaml[0]["domain_level"] == "root"

    cli = subprocess.run([str(XCTX), "--json", "discover"], cwd=ROOT, text=True, capture_output=True, check=False, timeout=15)
    assert cli.returncode == 0, cli.stderr + cli.stdout
    assert cli.stderr == ""
    assert json.loads(cli.stdout.splitlines()[0])["domain_level"] == "root"

    conflict = subprocess.run([str(XCTX), "--json", "--yaml", "discover"], cwd=ROOT, text=True, capture_output=True, check=False, timeout=15)
    assert conflict.returncode == 1, conflict.stderr + conflict.stdout
    assert conflict.stderr == ""
    payload = json.loads(conflict.stdout.splitlines()[0])
    assert payload["ok"] is False
    assert "choose either --json or --yaml" in payload["error"]


def main() -> int:
    assert_modular_layout()
    assert_protocol_is_config_driven()
    assert_root_domain_subdomain_discovery()
    assert_scoped_affordance_routing()
    assert_observe_audit_repair()
    assert_plan_execute_other_and_output()
    print("hardened xctx protocol smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
