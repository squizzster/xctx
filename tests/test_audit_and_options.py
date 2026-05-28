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


def test_framework_audit_scope_never_calls_live_connectors(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain import audit as audit_domain  # noqa: PLC0415

    def forbidden_call(*_args: object, **_kwargs: object) -> dict:
        raise AssertionError("framework audit scope called a live connector")

    monkeypatch.setattr(audit_domain, "call_external_command", forbidden_call)

    payload = audit_domain.audit_payload(load_store(root=ROOT), "root", audit_scope="framework")
    check_ids = {check["id"] for check in payload["checks"]}

    assert payload["audit_scope"] == "framework"
    assert payload["summary"]["audit_scope"] == "framework"
    assert "audit:xctx:config_fingerprint" in check_ids
    assert "audit:xctx:command_surface" in check_ids
    assert not any("mini_stocks_sqlite_exists" in check_id for check_id in check_ids)


def test_live_audit_scope_skips_framework_checks_and_targets_live_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain import audit as audit_domain  # noqa: PLC0415

    calls: list[tuple[str, str, tuple[str, ...]]] = []

    def fake_call(_store: dict, subdomain: dict, args: list[str]) -> dict:
        calls.append((str(subdomain["_domain_id"]), str(subdomain["id"]), tuple(args)))
        return {"checks": [{"id": f"audit:{subdomain['id']}:live_fake", "status": "pass"}]}

    monkeypatch.setattr(audit_domain, "call_external_command", fake_call)

    payload = audit_domain.audit_payload(
        load_store(root=ROOT),
        "stock_intelligence_hub::market_data_gateway",
        audit_scope="live",
    )
    check_ids = {check["id"] for check in payload["checks"]}

    assert payload["audit_scope"] == "live"
    assert payload["findings"] == []
    assert calls == [("stock_intelligence_hub", "market_data_gateway", ("audit",))]
    assert "audit:market_data_gateway:live_fake" in check_ids
    assert "audit:xctx:config_fingerprint" not in check_ids


def test_audit_scope_cli_selects_framework_lane_without_live_checks() -> None:
    rc, payload = run_runtime_json(["--max", "audit", "root", "--scope", "framework"])

    assert rc == 0
    results = payload["results"]
    check_ids = {check["id"] for check in results["checks"]}
    assert results["audit_scope"] == "framework"
    assert results["summary"]["audit_scope"] == "framework"
    assert "audit:xctx:config_fingerprint" in check_ids
    assert not any("aapl_latest_price_resolves" in check_id for check_id in check_ids)
    assert not any("external_command:ls" in check_id for check_id in check_ids)


def test_audit_scope_cli_rejects_unknown_lane() -> None:
    rc, payload = run_runtime_json(["audit", "root", "--scope", "domain"])

    assert rc == 1
    assert payload["record_type"] == "error"
    assert "invalid choice" in payload["error"]


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
    from xctx.protocol.option_surface import option_config_checks  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

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
        parse_target_cli_options(store, subdomain, "observe", ["--bad"])


def test_observe_configured_options_are_not_registered_globally() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.process.parser import build_parser  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain = store["agent_domains"]["stock_intelligence_hub"]
    domain["_subdomains"]["market_data_gateway"]["actions"]["observe"].setdefault("cli_options", []).append(
        {"flags": ["--target-scoped-only"], "dest": "target_scoped_only", "commands": ["observe"]}
    )

    parser = build_parser(store)
    args, unknown = parser.parse_known_args([
        "observe",
        "stock_intelligence_hub::market_data_gateway",
        "AAPL",
        "--target-scoped-only",
        "yes",
    ])

    assert unknown == []
    assert args.observe_args == [
        "stock_intelligence_hub::market_data_gateway",
        "AAPL",
        "--target-scoped-only",
        "yes",
    ]
    assert not hasattr(args, "target_scoped_only")


def test_target_scoped_observe_options_allow_unrelated_flag_reuse() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import subdomain_action_config  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    market = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    filing = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["equity_filing"]
    market["actions"]["observe"].setdefault("cli_options", []).append(
        {"flags": ["--shared"], "dest": "market_shared", "commands": ["observe"]}
    )
    filing.setdefault("cli_options", []).append(
        {"flags": ["--shared"], "dest": "filing_shared", "commands": ["observe"]}
    )
    market_action_name, market_action = subdomain_action_config(market, "observe")

    market_positional, market_values = parse_target_cli_options(
        store,
        market,
        "observe",
        ["AAPL", "--shared", "m"],
        action_name=market_action_name,
        action=market_action,
    )
    filing_positional, filing_values = parse_target_cli_options(store, filing, "observe", ["form:10-k", "--shared", "f"])

    assert market_positional == ["AAPL"]
    assert market_values == {"market_shared": "m"}
    assert filing_positional == ["form:10-k"]
    assert filing_values == {"filing_shared": "f"}


def test_target_scoped_observe_options_reject_same_target_collisions() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import subdomain_action_config  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    market = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    market["actions"]["observe"]["cli_options"] = [
        {"flags": ["--same"], "dest": "first", "commands": ["observe"]},
        {"flags": ["--same"], "dest": "second", "commands": ["observe"]},
    ]
    action_name, action = subdomain_action_config(market, "observe")

    with pytest.raises(XctxError, match="duplicate configured observe options"):
        parse_target_cli_options(
            store,
            market,
            "observe",
            ["AAPL", "--same", "value"],
            action_name=action_name,
            action=action,
        )


def test_store_false_options_encode_when_present() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import subdomain_action_config  # noqa: PLC0415
    from xctx.domain.routing import observe_adapter_option_args  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

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

    action_name, action = subdomain_action_config(subdomain, "observe")
    positional, values = parse_target_cli_options(
        store,
        subdomain,
        "observe",
        ["AAPL", "--no-cache"],
        action_name=action_name,
        action=action,
    )
    encoded = observe_adapter_option_args(store, subdomain, values)

    assert positional == ["AAPL"]
    assert values["cache"] is False
    assert "--no-cache" in encoded


def test_target_scoped_options_parse_inline_values_and_stop_marker() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import subdomain_action_config  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    observe_action = subdomain["actions"]["observe"]
    observe_action.setdefault("cli_options", []).append(
        {"flags": ["--rows"], "dest": "rows", "commands": ["observe"], "type": "int"}
    )
    action_name, action = subdomain_action_config(subdomain, "observe")

    positional, values = parse_target_cli_options(
        store,
        subdomain,
        "observe",
        ["AAPL", "--rows=3", "--", "--literal"],
        action_name=action_name,
        action=action,
    )

    assert positional == ["AAPL", "--literal"]
    assert values == {"rows": 3}


def test_target_scoped_options_reject_unknown_flag_for_resolved_target() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import subdomain_action_config  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    action_name, action = subdomain_action_config(subdomain, "observe")

    with pytest.raises(XctxError, match="unsupported option --not-market-data"):
        parse_target_cli_options(
            store,
            subdomain,
            "observe",
            ["AAPL", "--not-market-data"],
            action_name=action_name,
            action=action,
        )


def test_target_scoped_options_require_values_for_scalar_flags() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import subdomain_action_config  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["actions"]["observe"].setdefault("cli_options", []).append(
        {"flags": ["--rows"], "dest": "rows", "commands": ["observe"], "type": "int"}
    )
    action_name, action = subdomain_action_config(subdomain, "observe")

    with pytest.raises(XctxError, match="missing value for --rows"):
        parse_target_cli_options(
            store,
            subdomain,
            "observe",
            ["AAPL", "--rows"],
            action_name=action_name,
            action=action,
        )


def test_target_scoped_options_reject_boolean_inline_values() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import subdomain_action_config  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["actions"]["observe"].setdefault("cli_options", []).append(
        {"flags": ["--refresh"], "dest": "refresh", "commands": ["observe"], "type": "bool"}
    )
    action_name, action = subdomain_action_config(subdomain, "observe")

    with pytest.raises(XctxError, match="unsupported value for boolean option --refresh"):
        parse_target_cli_options(
            store,
            subdomain,
            "observe",
            ["AAPL", "--refresh=true"],
            action_name=action_name,
            action=action,
        )


def test_target_scoped_required_options_are_enforced_after_resolution() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import subdomain_action_config  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["actions"]["observe"].setdefault("cli_options", []).append(
        {"flags": ["--dataset"], "dest": "dataset", "commands": ["observe"], "required": True}
    )
    action_name, action = subdomain_action_config(subdomain, "observe")

    with pytest.raises(XctxError, match="missing required observe option: --dataset"):
        parse_target_cli_options(
            store,
            subdomain,
            "observe",
            ["AAPL"],
            action_name=action_name,
            action=action,
        )


def test_target_scoped_option_bounds_are_validated_before_adapter_encoding() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import subdomain_action_config  # noqa: PLC0415
    from xctx.domain.routing import observe_adapter_option_args  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["actions"]["observe"].setdefault("cli_options", []).append(
        {
            "flags": ["--rows"],
            "dest": "rows",
            "commands": ["observe"],
            "type": "int",
            "max": 3,
            "adapter_arg": "--rows",
        }
    )
    action_name, action = subdomain_action_config(subdomain, "observe")
    _positional, values = parse_target_cli_options(
        store,
        subdomain,
        "observe",
        ["AAPL", "--rows", "4"],
        action_name=action_name,
        action=action,
    )

    with pytest.raises(XctxError, match="--rows is above maximum 3"):
        observe_adapter_option_args(store, subdomain, values)


def test_target_scoped_option_choices_are_validated_before_adapter_encoding() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.actions import subdomain_action_config  # noqa: PLC0415
    from xctx.domain.routing import observe_adapter_option_args  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.protocol.option_specs import parse_target_cli_options  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["actions"]["observe"].setdefault("cli_options", []).append(
        {
            "flags": ["--mode"],
            "dest": "mode",
            "commands": ["observe"],
            "choices": ["summary", "full"],
            "adapter_arg": "--mode",
        }
    )
    action_name, action = subdomain_action_config(subdomain, "observe")
    _positional, values = parse_target_cli_options(
        store,
        subdomain,
        "observe",
        ["AAPL", "--mode", "raw"],
        action_name=action_name,
        action=action,
    )

    with pytest.raises(XctxError, match="unsupported value for --mode: raw"):
        observe_adapter_option_args(store, subdomain, values)


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
