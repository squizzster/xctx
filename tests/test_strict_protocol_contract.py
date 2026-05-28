"""Strict negative tests for the current xctx public protocol contract."""

from __future__ import annotations

import json
import re

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


def _text(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def test_help_is_not_a_public_command_or_root_next_move() -> None:
    for args in (["help"], ["--help"], ["-h"]):
        rc, payload = run_runtime_json(args)
        assert rc == 1
        assert payload["record_type"] == "error"
        assert payload["error"] == "unknown xctx command"
        assert all(move["run_cmd"] != "./xctx help" for move in payload["next_moves"])

    for args in ([], ["discover"], ["--version"]):
        rc, payload = run_runtime_json(list(args))
        assert rc == 0
        assert "./xctx help" not in _text(payload)
        assert "help" not in payload["results"].get("record_types", [])


def test_unscoped_observation_ids_are_refused_before_adapter_routing() -> None:
    for target in (
        "directory:docs",
        "file:README.txt",
        "instrument:aapl",
        "issuer:cik:0000320193",
        "market_series:aapl:daily",
        "form:10-K",
        "family:ANNUAL_REPORT",
        "priority:critical_always",
    ):
        rc, payload = run_runtime_json(["observe", target])
        assert rc == 1
        assert payload["record_type"] == "error"
        assert payload["error"] == f"unscoped observe target requires explicit agent_subdomain scope: {target}"
        assert payload["next_moves"] == [{"run_cmd": "./xctx observe <agent_domain>::<agent_subdomain> <id>"}]


def test_explicit_scoped_observation_remains_valid() -> None:
    cases = (
        ["observe", "file_manager::home_directory", "directory:docs"],
        ["observe", "file_manager::home_directory", "file:README.txt"],
        ["observe", "stock_intelligence_hub::market_data_gateway", "instrument:aapl"],
        ["observe", "stock_intelligence_hub::equity_filing", "form:10-K"],
    )
    for args in cases:
        rc, payload = run_runtime_json(list(args))
        assert rc == 0
        assert payload["record_type"] == "observation"
        assert payload["domain_level"] == "agent_subdomain"


def test_bare_scoped_ref_shorthand_is_not_a_command() -> None:
    rc, payload = run_runtime_json(["stock_intelligence_hub::search_priority_bucket", "critical"])
    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["error"] == "unknown xctx command"


def test_subdomain_actions_require_structural_action_refs() -> None:
    rejected = (
        ["discover", "stock_intelligence_hub::equity_filing", "search_forms", "10-K"],
        ["discover", "stock_intelligence_hub::equity_filing", "list_forms"],
        ["discover", "stock_intelligence_hub::market_data_gateway", "search_entity_instrument", "Apple"],
        ["discover", "stock_intelligence_hub::market_data_gateway", "list_instruments"],
        ["discover", "file_manager::home_directory", "list_files"],
    )
    for args in rejected:
        rc, payload = run_runtime_json(list(args))
        assert rc == 1
        assert payload["record_type"] == "error"
        assert payload["error"].startswith("non-canonical subdomain action form:")

    accepted = (
        ["discover", "stock_intelligence_hub::equity_filing::search_forms", "10-K"],
        ["discover", "stock_intelligence_hub::equity_filing::list_forms", "--limit", "1"],
        ["discover", "stock_intelligence_hub::market_data_gateway::search_entity_instrument", "Apple"],
        ["discover", "stock_intelligence_hub::market_data_gateway::list_instruments", "--limit", "1"],
        ["discover", "file_manager::home_directory::list_files", "--limit", "1"],
    )
    for args in accepted:
        rc, payload = run_runtime_json(list(args))
        assert rc == 0
        assert payload["record_type"] == "discovery"


def test_entrypoint_action_token_guidance_uses_canonical_structural_ref() -> None:
    rc, payload = run_runtime_json(["discover", "stock_intelligence_hub::equity_filing", "list-forms"])

    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["error"] == "non-canonical action token for stock_intelligence_hub::equity_filing: list-forms"
    assert payload["next_moves"] == [{"run_cmd": "./xctx discover stock_intelligence_hub::equity_filing::list_forms"}]
    assert "./xctx discover stock_intelligence_hub::equity_filing list_forms" not in _text(payload)


def test_domain_action_name_guidance_uses_canonical_structural_ref() -> None:
    rc, payload = run_runtime_json(["discover", "stock_intelligence_hub::equity_filing", "search_filing_form"])

    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["error"] == (
        "non-canonical action token for stock_intelligence_hub::equity_filing: search_filing_form"
    )
    assert payload["next_moves"] == [{"run_cmd": "./xctx discover stock_intelligence_hub::equity_filing::search_forms"}]
    assert "./xctx discover stock_intelligence_hub::equity_filing search_forms" not in _text(payload)


def test_domain_affordance_shortcuts_are_explicit_mappings() -> None:
    rc, shortcut = run_runtime_json(["discover", "stock_intelligence_hub::search_filing_form", "10-K"])
    assert rc == 0
    assert shortcut["domain_level"] == "agent_subdomain"
    shortcut_results = shortcut["results"]
    assert shortcut_results["action"] == "search_filing_form"
    assert shortcut_results["domain_affordance"] is True
    assert shortcut_results["agent_domain"] == "stock_intelligence_hub"
    assert shortcut_results["agent_subdomain_id"] == "stock_intelligence_hub::equity_filing"
    assert shortcut_results["agent_subdomain"]["subdomain_id"] == "equity_filing"
    assert shortcut_results["implemented_by"] == "stock_intelligence_hub::equity_filing::search_forms"
    assert shortcut_results["implemented_by_run_cmd"] == "./xctx discover stock_intelligence_hub::equity_filing::search_forms"
    assert shortcut_results["implemented_action"] == "search_forms"

    rc, shortcut_interface = run_runtime_json(["discover", "stock_intelligence_hub::search_filing_form"])
    assert rc == 0
    interface_results = shortcut_interface["results"]
    assert interface_results["object_type"] == "xctx_action_discovery_interface"
    assert interface_results["domain_affordance"] is True
    assert interface_results["implemented_by"] == "stock_intelligence_hub::equity_filing::search_forms"
    assert interface_results["implemented_by_run_cmd"] == "./xctx discover stock_intelligence_hub::equity_filing::search_forms"

    rc, direct = run_runtime_json(["discover", "stock_intelligence_hub::equity_filing::search_forms", "10-K"])
    assert rc == 0
    direct_results = direct["results"]
    assert direct_results["action"] == "search_forms"
    assert direct_results["domain_affordance"] is True
    assert direct_results["domain_action_name"] == "search_filing_form"
    assert direct_results["domain_affordance_run_cmd"] == "./xctx discover stock_intelligence_hub::search_filing_form"
    assert direct_results["implemented_by"] == "stock_intelligence_hub::equity_filing::search_forms"

    rc, domain = run_runtime_json(["--max", "discover", "stock_intelligence_hub::"])
    assert rc == 0
    affordance = domain["results"]["domain_affordances"]["search_filing_form"]
    assert affordance["domain_affordance"] is True
    assert affordance["agent_domain"] == "stock_intelligence_hub"
    assert affordance["agent_subdomain"] == "equity_filing"
    assert affordance["implemented_by"] == "stock_intelligence_hub::equity_filing::search_forms"
    assert affordance["implemented_by_run_cmd"] == "./xctx discover stock_intelligence_hub::equity_filing::search_forms"
    assert affordance["run_cmd"].startswith("./xctx discover stock_intelligence_hub::search_filing_form")


def test_scoped_payloads_use_object_agent_subdomain_schema() -> None:
    cases = (
        ["discover", "stock_intelligence_hub::market_data_gateway"],
        ["discover", "stock_intelligence_hub::market_data_gateway::search_entity_instrument"],
        ["discover", "stock_intelligence_hub::search_filing_form"],
        ["observe", "stock_intelligence_hub::market_data_gateway", "instrument:aapl"],
    )
    for args in cases:
        rc, payload = run_runtime_json(list(args))
        assert rc == 0
        results = payload["results"]
        assert isinstance(results["agent_subdomain"], dict)
        assert results["agent_subdomain_id"].startswith(results["agent_domain"] + "::")
        assert results["agent_subdomain"]["id"] == results["agent_subdomain_id"]
        assert results["agent_subdomain"]["domain_id"] == results["agent_domain"]
        assert results["agent_subdomain"]["subdomain_id"]


def test_agent_subdomain_field_is_not_reused_as_string_in_scoped_payloads() -> None:
    for args in (
        ["discover", "file_manager::home_directory::list_files", "--limit", "1"],
        ["observe", "file_manager::home_directory", "file:README.txt"],
    ):
        rc, payload = run_runtime_json(list(args))
        assert rc == 0
        assert not isinstance(payload["results"]["agent_subdomain"], str)


def test_basic_instrument_observation_omits_expanded_market_series_data() -> None:
    rc, basic = run_runtime_json(["observe", "stock_intelligence_hub::market_data_gateway", "instrument:aapl"])
    assert rc == 0
    live = basic["results"]["live_data"]
    assert live["object_type"] == "market_data_gateway_instrument_observation"
    assert live["instrument_id"] == "instrument:aapl"
    assert live["market_series_available"] is True
    assert live["market_series_id"] == "market_series:aapl:daily"
    assert "market_series" not in live
    assert "latest_available_price" not in live

    rc, expanded = run_runtime_json(["--more", "observe", "stock_intelligence_hub::market_data_gateway", "instrument:aapl"])
    assert rc == 0
    expanded_live = expanded["results"]["live_data"]
    assert expanded_live["market_series"]["market_series_id"] == "market_series:aapl:daily"
    assert expanded_live["latest_available_price"]["is_live_quote"] is False


def test_repair_plan_next_move_declares_protocol_ledger_write() -> None:
    rc, payload = run_runtime_json(["repair", "offline:macro_intelligence_hub"])
    assert rc == 0
    moves = payload["results"]["next_moves"]
    assert moves[0] == {
        "run_cmd": "./xctx plan bring_online macro_intelligence_hub",
        "writes_protocol_ledger": True,
        "domain_mutation": False,
    }
    assert moves[1] == {
        "run_cmd": "./xctx audit macro_intelligence_hub",
        "writes_protocol_ledger": False,
        "domain_mutation": False,
    }


def test_generated_guidance_does_not_emit_removed_command_forms() -> None:
    surfaces = (
        [],
        ["discover"],
        ["--version"],
        ["--max", "discover", "file_manager::home_directory"],
        ["--max", "discover", "stock_intelligence_hub::market_data_gateway"],
        ["--max", "discover", "stock_intelligence_hub::equity_filing"],
        ["--max", "discover", "stock_intelligence_hub::equity_filing::list_forms", "--limit", "1"],
        ["--max", "discover", "stock_intelligence_hub::market_data_gateway::list_instruments", "--limit", "1"],
    )
    forbidden_patterns = (
        r"\./xctx help\b",
        r"\./xctx observe (?:file|directory|instrument|issuer:cik|market_series|form|family|priority):",
        r"\./xctx discover file_manager::home_directory (?:list_files|list_directories)\b",
        r"\./xctx discover stock_intelligence_hub::market_data_gateway (?:search_entity_instrument|search_market_series|latest_price|list_instruments)\b",
        r"\./xctx discover stock_intelligence_hub::equity_filing (?:search_forms|search_families|search_priority_buckets|list_forms|list_families|list_priority_buckets)\b",
    )
    for args in surfaces:
        rc, payload = run_runtime_json(list(args))
        assert rc == 0
        text = _text(payload)
        for pattern in forbidden_patterns:
            assert not re.search(pattern, text), f"{pattern!r} leaked from {args}: {text[:500]}"


def test_loaded_yaml_has_no_implicit_root_observe_routing() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415

    store = load_store(root=ROOT)
    assert "agent_routing" not in store["universe"]
