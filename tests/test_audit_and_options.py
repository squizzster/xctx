"""Framework audit-scope and CLI option validation tests."""

from __future__ import annotations

import copy

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


def test_audit_scope_validation_fails_closed() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.audit import audit_domain_level, audit_payload  # noqa: PLC0415
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
    from xctx.protocol.option_surface import option_config_checks  # noqa: PLC0415

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


def test_option_audit_rejects_non_flag_option_names_before_argparse_crash() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.process.parser import build_parser  # noqa: PLC0415
    from xctx.protocol.option_surface import option_config_checks  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain = next(iter(store["agent_domains"].values()))
    subdomain = next(iter(domain["_subdomains"].values()))
    subdomain.setdefault("cli_options", []).append(
        {"flags": ["bad-flag"], "dest": "bad_flag", "commands": ["observe"]}
    )

    checks = option_config_checks(store)
    observe_check = next(check for check in checks if check["id"] == "audit:xctx:cli_options:observe")
    assert observe_check["status"] == "fail"
    assert "flags must start with '-'" in observe_check["error"]

    with pytest.raises(XctxError, match="flags must start with '-'"):
        build_parser(store)


def test_store_false_options_encode_when_present() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.routing import observe_adapter_option_args  # noqa: PLC0415
    from xctx.process.parser import build_parser  # noqa: PLC0415
    from xctx.protocol.option_specs import collect_cli_option_values  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    observe_action = subdomain["actions"]["observe"]
    observe_action.setdefault("cli_options", []).append(
        {
            "flags": ["--no-cache"],
            "dest": "cache",
            "commands": ["observe"],
            "type": "bool",
            "action": "store_false",
            "adapter_arg": "--no-cache",
        }
    )

    parser = build_parser(store)
    args, unknown = parser.parse_known_args(
        ["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--no-cache"]
    )
    values = collect_cli_option_values(store, "observe", args)
    encoded = observe_adapter_option_args(store, subdomain, values)

    assert unknown == []
    assert values["cache"] is False
    assert "--no-cache" in encoded


def test_duplicate_domain_affordances_fail_audit_check() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import domain_affordance_config_check  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain = store["agent_domains"]["stock_intelligence_hub"]
    domain["_subdomains"]["market_data_gateway"]["actions"]["search_entity_instrument"][
        "domain_action_name"
    ] = "duplicate_route"
    domain["_subdomains"]["equity_filing"]["actions"]["search_forms"]["domain_action_name"] = "duplicate_route"

    check = domain_affordance_config_check(store)

    assert check["status"] == "fail"
    assert check["duplicate_affordances"] == [
        {
            "agent_domain": "stock_intelligence_hub",
            "token": "duplicate_route",
            "sources": [
                "stock_intelligence_hub::equity_filing::search_forms",
                "stock_intelligence_hub::market_data_gateway::search_entity_instrument",
            ],
        }
    ]


def test_domain_affordance_collision_with_subdomain_id_fails_audit_check() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import domain_affordance_config_check  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain = store["agent_domains"]["stock_intelligence_hub"]
    domain["_subdomains"]["market_data_gateway"]["actions"]["search_entity_instrument"][
        "domain_action_name"
    ] = "equity_filing"

    check = domain_affordance_config_check(store)

    assert check["status"] == "fail"
    assert {
        "agent_domain": "stock_intelligence_hub",
        "token": "equity_filing",
        "sources": [
            "stock_intelligence_hub::equity_filing",
            "stock_intelligence_hub::market_data_gateway::search_entity_instrument",
        ],
    } in check["duplicate_affordances"]
