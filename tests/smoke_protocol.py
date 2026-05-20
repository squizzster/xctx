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
        "search_filing_form",
        "search_forms",
        "list_forms",
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
        "legacy_connector.py",
        "libs/xctx_connectors/__init__.py",
        "libs/xctx_connectors/middleware.py",
        "yaml_dynamic_config/protocols/xctx_v4_2.yaml",
        "yaml_dynamic_config/shared/command_sets/core_commands.yaml",
        "yaml_dynamic_config/universe.yaml",
        "yaml_dynamic_config/agent_domains/file_manager/domain.yaml",
        "yaml_dynamic_config/agent_domains/file_manager/subdomains/home_directory/subdomain.yaml",
        "yaml_dynamic_config/agent_domains/stock_intelligence_hub/domain.yaml",
        "yaml_dynamic_config/agent_domains/stock_intelligence_hub/subdomains/equity_filing/subdomain.yaml",
        "yaml_dynamic_config/agent_domains/stock_intelligence_hub/subdomains/market_data_gateway/subdomain.yaml",
        "data/file_manager_home/README.txt",
        "data/file_manager_home/docs/manual.txt",
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
    assert any(item["id"] == "file_manager" for item in universe["agent_domains"])
    file_routes = [route for route in universe["agent_routing"]["observe_routes"] if route["id"] == "file_manager_objects"]
    assert file_routes[0]["agent_domain"] == "file_manager"
    assert file_routes[0]["prefixes"] == ["file:", "directory:"]
    market_subdomain = yaml.safe_load((ROOT / "yaml_dynamic_config" / "agent_domains" / "stock_intelligence_hub" / "subdomains" / "market_data_gateway" / "subdomain.yaml").read_text())
    assert market_subdomain["entrypoint"]["file"] == "legacy_connector.py"
    assert market_subdomain["connector"]["kind"] == "xctx_native_passthrough"
    assert market_subdomain["connector"]["target_entrypoint"] == "market_data_gateway.py"
    assert market_subdomain["actions"]["search_entity_instrument"]["domain_affordance"] is True
    assert market_subdomain["actions"]["latest_price"]["domain_affordance"] is True
    assert market_subdomain["actions"]["latest_price"]["entrypoint_command"] == "latest-price"
    assert market_subdomain["actions"]["discover"]["discovery_shapes"]["default_shape"] == "compact"
    observe_flags = [option["flags"][0] for option in market_subdomain["actions"]["observe"]["cli_options"]]
    assert observe_flags == ["--bars", "--calendar-days"]
    filing_subdomain = yaml.safe_load((ROOT / "yaml_dynamic_config" / "agent_domains" / "stock_intelligence_hub" / "subdomains" / "equity_filing" / "subdomain.yaml").read_text())
    assert filing_subdomain["entrypoint"]["file"] == "legacy_connector.py"
    assert filing_subdomain["connector"]["kind"] == "xctx_native_passthrough"
    assert filing_subdomain["connector"]["target_entrypoint"] == "equity_filings.py"
    assert filing_subdomain["actions"]["search_forms"]["domain_affordance"] is True
    assert filing_subdomain["actions"]["search_forms"]["domain_action_name"] == "search_filing_form"
    assert filing_subdomain["actions"]["discover"]["discovery_shapes"]["default_shape"] == "compact"
    assert filing_subdomain["actions"]["list_forms"]["entrypoint_command"] == "list-forms"
    assert filing_subdomain["actions"]["list_forms"]["query_required"] is False
    assert filing_subdomain["actions"]["list_forms"]["collection"]["default_shape"] == "compact"
    assert filing_subdomain["actions"]["list_forms"]["collection"]["cursor"] == "optional"
    assert market_subdomain["actions"]["list_instruments"]["collection"]["cursor"] == "optional"

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
    assert domains["file_manager"]["status"] == "online"
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
    assert filing["results"]["shape"] == "compact"
    assert filing_live["shape"] == "compact"
    assert "configured_action_index" in filing["results"]
    assert "configured_actions" not in filing["results"]
    assert filing_live["stats"]["total_lookup_filings"] == 412
    assert filing_live["stats"]["canonical_families"] == 41
    assert filing_live["stats"]["priority_buckets"] == 12
    assert filing_live["stats"]["amendment_forms"] == 176
    assert {item["id"] for item in filing_live["discoverable_modes"]} >= {
        "search_forms",
        "list_forms",
        "search_families",
        "list_families",
        "search_priority_buckets",
        "list_priority_buckets",
    }
    assert "./xctx discover stock_intelligence_hub::equity_filing list_forms" in filing_live["next_moves"]
    filing_full = one(["discover", "stock_intelligence_hub::equity_filing", "--shape", "full"])
    filing_full_live = filing_full["results"]["live_data"]
    assert filing_full["results"]["shape"] == "full"
    assert "configured_actions" in filing_full["results"]
    assert filing_full_live["shape"] == "full"
    assert "modes" in filing_full_live
    assert filing_full_live["command_grammar"]["mode_discovery"].endswith("::equity_filing::<mode>")
    bad_shape = one(["discover", "stock_intelligence_hub::equity_filing", "--shape", "wide"], expected_code=1)
    assert "choose --shape compact|full" in bad_shape["error"]

    market = one(["discover", "stock_intelligence_hub::market_data_gateway"])
    assert market["domain_level"] == "agent_subdomain"
    market_live = market["results"]["live_data"]
    assert market_live["object_type"] == "market_data_gateway_discovery"
    assert market["results"]["shape"] == "compact"
    assert market_live["shape"] == "compact"
    assert market_live["stats"]["canonical_instruments"] >= 100
    observe_options = market["results"]["configured_options"]["observe"]
    assert [item["flags"][0] for item in observe_options] == ["--bars", "--calendar-days"]
    assert observe_options[0]["source"]["agent_subdomain"] == "market_data_gateway"
    assert {item["id"] for item in market_live["discoverable_modes"]} >= {
        "search_entity_instrument",
        "search_market_series",
        "latest_price",
        "list_instruments",
    }
    market_full = one(["discover", "stock_intelligence_hub::market_data_gateway", "--shape", "full"])
    market_full_live = market_full["results"]["live_data"]
    assert market_full["results"]["shape"] == "full"
    assert market_full_live["shape"] == "full"
    assert market_full_live["stats"]["reference_universe_snapshots"] == 100
    sample_series_ids = [item["market_series_id"] for item in market_full_live["sample_market_series"]]
    assert len(sample_series_ids) == len(set(sample_series_ids)), sample_series_ids
    assert all("latest_bar" not in item for item in market_full_live["sample_market_series"])

    file_domain = one(["discover", "file_manager::"])
    assert file_domain["domain_level"] == "agent_domain"
    assert file_domain["results"]["agent_subdomains"][0]["id"] == "home_directory"
    file_subdomain = one(["discover", "file_manager::home_directory"])
    assert file_subdomain["domain_level"] == "agent_subdomain"
    file_live = file_subdomain["results"]["live_data"]
    assert file_live["object_type"] == "legacy_connector_filesystem_discovery"
    assert file_live["connector"]["kind"] == "legacy_command"
    assert file_live["observable_objects"]["file"]["id_shape"] == "file:<relative_path>"
    assert {item["id"] for item in file_live["discoverable_modes"]} == {"list_files", "list_directories"}


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
    form_ids = [item["id"] for item in form["results"]["live_data"]["matches"]]
    assert form_ids == ["form:10-K", "form:10-K/A"]
    assert "form:8-K" not in form_ids

    form_affordance = one(["discover", "stock_intelligence_hub::search_filing_form", "10-K"])
    affordance_ids = [item["id"] for item in form_affordance["results"]["live_data"]["matches"]]
    assert affordance_ids == ["form:10-K", "form:10-K/A"]

    eight_k = one(["discover", "stock_intelligence_hub::equity_filing", "search_forms", "8-K"])
    eight_k_ids = [item["id"] for item in eight_k["results"]["live_data"]["matches"]]
    assert eight_k_ids == ["form:8-K", "form:8-K/A"]
    assert "form:10-K" not in eight_k_ids

    form_mode = one(["discover", "stock_intelligence_hub::equity_filing::search_forms"])
    assert form_mode["results"]["object_type"] == "xctx_action_discovery_interface"
    assert form_mode["results"]["action"] == "search_forms"
    assert form_mode["results"]["argument_shapes"]
    assert form_mode["results"]["examples"][0]["run_cmd"].endswith("search_forms 10-K")

    form_mode_alt = one(["discover", "stock_intelligence_hub::equity_filing", "search_forms"])
    assert form_mode_alt["results"]["object_type"] == "xctx_action_discovery_interface"
    assert form_mode_alt["results"]["argument_shapes"] == form_mode["results"]["argument_shapes"]

    list_forms = one(["discover", "stock_intelligence_hub::equity_filing", "list_forms"])
    assert list_forms["results"]["action"] == "list_forms"
    assert list_forms["results"]["live_data"]["object_type"] == "equity_filing_form_list"
    assert list_forms["results"]["live_data"]["returned_count"] > 0
    list_forms_live = list_forms["results"]["live_data"]
    assert list_forms_live["shape"] == "compact"
    assert list_forms_live["pagination"]["has_more"] is True
    assert list_forms_live["forms"][0]["id"].startswith("form:")
    assert "canonical_family" not in list_forms_live["forms"][0]
    assert "priority_bucket" not in list_forms_live["forms"][0]
    assert "run_cmd" not in list_forms_live["forms"][0]

    list_forms_full = one(["discover", "stock_intelligence_hub::equity_filing", "list_forms", "--limit", "2", "--shape", "full"])
    full_live = list_forms_full["results"]["live_data"]
    assert full_live["shape"] == "full"
    assert full_live["pagination"]["returned_count"] == 2
    assert "canonical_family" in full_live["forms"][0]
    assert "run_cmd" in full_live["forms"][0]

    list_forms_page = one(["discover", "stock_intelligence_hub::equity_filing", "list_forms", "--limit", "2", "--cursor", "2"])
    assert list_forms_page["results"]["live_data"]["pagination"]["cursor"] == "2"
    assert list_forms_page["results"]["live_data"]["forms"][0]["id"] != list_forms_live["forms"][0]["id"]

    bad_cursor = one(["discover", "stock_intelligence_hub::equity_filing", "list_priority_buckets", "--cursor", "1"], expected_code=1)
    assert "does not declare cursor support" in bad_cursor["error"]

    exact_family = one(["discover", "stock_intelligence_hub::equity_filing", "search_families", "ANNUAL_REPORT"])
    assert [item["id"] for item in exact_family["results"]["live_data"]["matches"]] == ["family:ANNUAL_REPORT"]

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

    missing_subdomain_query_ref = one(["discover", "stock_intelligence_hub::market_data_gateway::search_entity_instrument"])
    assert missing_subdomain_query_ref["ok"] is True
    assert missing_subdomain_query_ref["results"]["object_type"] == "xctx_action_discovery_interface"
    assert missing_subdomain_query_ref["results"]["query_required"] is True

    family = one(["discover", "stock_intelligence_hub::search_filing_family", "annual"])
    assert any(item["id"] == "family:ANNUAL_REPORT" for item in family["results"]["live_data"]["matches"])
    assert len(family["results"]["live_data"]["matches"]) > 1

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
    assert "latest_bar" not in series["results"]["live_data"]["matches"][0]
    series_by_cik = one(["discover", "stock_intelligence_hub::search_market_series", "issuer:cik:0000320193"])
    assert series_by_cik["results"]["live_data"]["matches"][0]["market_series_id"] == "market_series:aapl:daily"
    assert "latest_bar" not in series_by_cik["results"]["live_data"]["matches"][0]
    latest = one(["discover", "stock_intelligence_hub::latest_price", "AAPL"])
    latest_live = latest["results"]["live_data"]
    assert latest_live["object_type"] == "market_data_gateway_latest_price_discovery"
    assert latest_live["found"] is True
    assert latest_live["observe_cmd"] == "./xctx observe stock_intelligence_hub::market_data_gateway AAPL"
    assert "latest_available_price" not in latest_live
    latest_subdomain = one(["discover", "stock_intelligence_hub::market_data_gateway", "latest_price", "issuer:cik:0000320193"])
    assert latest_subdomain["results"]["live_data"]["ticker"] == "AAPL"
    assert "latest_available_price" not in latest_subdomain["results"]["live_data"]
    instruments_page = one(["discover", "stock_intelligence_hub::market_data_gateway", "list_instruments", "--limit", "2"])
    instruments_live = instruments_page["results"]["live_data"]
    assert instruments_live["shape"] == "compact"
    assert instruments_live["pagination"]["returned_count"] == 2
    assert instruments_live["pagination"]["next_cursor"] == "2"
    assert "run_cmd" not in instruments_live["instruments"][0]
    assert "next_moves" not in instruments_live["instruments"][0]

    instruments_full = one(["discover", "stock_intelligence_hub::market_data_gateway", "list_instruments", "--limit", "2", "--shape", "full"])
    full_instruments_live = instruments_full["results"]["live_data"]
    assert full_instruments_live["shape"] == "full"
    assert "run_cmd" in full_instruments_live["instruments"][0]
    assert "next_moves" in full_instruments_live["instruments"][0]
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
    sample_dates = [bar["date"] for bar in series_live["sample_bars_last_5"]]
    assert len(sample_dates) == len(set(sample_dates)), sample_dates

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


def assert_legacy_connector_middleware() -> None:
    files = one(["discover", "file_manager::home_directory", "list_files", "--limit", "2"])
    live_files = files["results"]["live_data"]
    assert live_files["object_type"] == "legacy_connector_filesystem_file_list"
    assert live_files["connector"]["profile"] == "filesystem_home"
    assert live_files["command_status"]["ok"] is True
    assert "argv" not in live_files["command_status"]
    assert "pagination" not in live_files
    assert live_files["files"][0]["id"] == "file:README.txt"
    assert "This is a bundled file-manager demo fixture" not in json.dumps(live_files)

    full_files = one(["discover", "file_manager::home_directory", "list_files", "--limit", "1", "--shape", "full"])
    full_files_live = full_files["results"]["live_data"]
    assert full_files_live["pagination"]["returned_count"] == 1
    assert full_files_live["command_status"]["argv"][0] == "ls"

    discovered_file = one(["discover", "file_manager::home_directory", "file:README.txt"])
    discovered_file_live = discovered_file["results"]["live_data"]
    assert discovered_file_live["object_type"] == "legacy_connector_filesystem_file_discovery"
    assert discovered_file_live["id"] == "file:README.txt"
    assert discovered_file_live["type"] == "ASCII text"
    assert discovered_file_live["size_bytes"] == 237
    assert "argv" not in discovered_file_live["command_status"]["stat_line"]
    assert "argv" not in discovered_file_live["command_status"]["type"]
    assert "content" not in discovered_file_live
    assert "This is a bundled file-manager demo fixture" not in json.dumps(discovered_file_live)

    directories = one(["discover", "file_manager::home_directory", "list_directories"])
    live_directories = directories["results"]["live_data"]
    directory_ids = {item["id"] for item in live_directories["directories"]}
    assert {"directory:docs", "directory:reports", "directory:archive"} <= directory_ids

    observed_file = one(["observe", "file_manager::home_directory", "file:README.txt"])
    file_live = observed_file["results"]["live_data"]
    assert file_live["object_type"] == "legacy_connector_filesystem_file_observation"
    assert file_live["file_id"] == "file:README.txt"
    assert file_live["command_status"]["ok"] is True
    assert "ASCII text" in file_live["file_type"]
    assert file_live["content"]["available"] is True
    assert "This is a bundled file-manager demo fixture" in file_live["content"]["text"]

    routed_directory = one(["observe", "directory:docs"])
    directory_live = routed_directory["results"]["live_data"]
    assert routed_directory["results"]["agent_domain"] == "file_manager"
    assert routed_directory["results"]["agent_subdomain"] == "home_directory"
    assert directory_live["directory_id"] == "directory:docs"
    assert directory_live["sample_children"][0]["id"] == "file:docs/manual.txt"

    escaped = one(["observe", "file:../README.md"])
    escaped_live = escaped["results"]["live_data"]
    assert escaped_live["object_type"] == "legacy_connector_error"
    assert escaped_live["found"] is False
    assert escaped_live["command_status"]["ok"] is False
    assert "safe root" in escaped_live["command_status"]["error"]


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
    assert_legacy_connector_middleware()
    assert_observe_audit_repair()
    assert_plan_execute_other_and_output()
    print("hardened xctx protocol smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
