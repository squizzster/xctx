"""Additional framework hardening coverage from the code review pass."""

from __future__ import annotations

import copy

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.release, pytest.mark.timeout(60)]


def test_discover_domain_scope_rejects_ignored_extra_arguments() -> None:
    rc, payload = run_runtime_json(["discover", "stock_intelligence_hub", "nonsense"])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "discovery arguments require a scoped agent_subdomain target: stock_intelligence_hub"
    assert payload["next_moves"] == [{"run_cmd": "./xctx discover stock_intelligence_hub::<agent_subdomain>"}]


def test_observe_domain_scope_rejects_configured_options_before_they_are_ignored() -> None:
    rc, payload = run_runtime_json(["observe", "stock_intelligence_hub", "--bars", "5"])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "configured observe options require a scoped observe target: stock_intelligence_hub"
    assert payload["next_moves"] == [
        {"run_cmd": "./xctx observe stock_intelligence_hub::<agent_subdomain> --id <id>"}
    ]


def test_ambiguous_domain_affordance_resolution_fails_closed() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.discovery import discover_payload  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain = store["agent_domains"]["stock_intelligence_hub"]
    domain["_subdomains"]["market_data_gateway"]["actions"]["search_entity_instrument"][
        "domain_action_name"
    ] = "duplicate_route"
    domain["_subdomains"]["equity_filing"]["actions"]["search_forms"]["domain_action_name"] = "duplicate_route"

    with pytest.raises(XctxError, match="ambiguous domain affordance") as raised:
        discover_payload(store, "stock_intelligence_hub::duplicate_route", ["AAPL"])
    assert raised.value.next_moves == ["./xctx audit stock_intelligence_hub"]


def test_live_audit_checks_are_normalised_fail_closed() -> None:
    ensure_libs_path()
    from xctx.domain.audit import _normalise_live_audit_checks  # noqa: PLC0415

    malformed = _normalise_live_audit_checks(
        "demo_domain",
        "demo_subdomain",
        {"checks": {"status": "pass"}},
    )
    assert malformed == [
        {
            "id": "audit:demo_domain:demo_subdomain:live_adapter_contract",
            "status": "fail",
            "message": "live adapter checks must be a list",
        }
    ]

    invalid_item = _normalise_live_audit_checks(
        "demo_domain",
        "demo_subdomain",
        {"checks": ["not-a-check", {"id": "x", "status": "PASS"}]},
    )
    assert invalid_item[0]["status"] == "fail"
    assert invalid_item[1] == {"id": "x", "status": "pass"}

    error_without_checks = _normalise_live_audit_checks(
        "demo_domain",
        "demo_subdomain",
        {"object_type": "demo_error"},
    )
    assert error_without_checks[0]["status"] == "fail"


def test_audit_status_treats_malformed_checks_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx.commands import audit as audit_command  # noqa: PLC0415

    monkeypatch.setattr(
        audit_command,
        "audit_payload",
        lambda _store, _scope: {"summary": {}, "checks": ["not-a-check"], "findings": []},
    )

    rc, payload = run_runtime_json(["audit", "root"])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["results"]["checks"] == ["not-a-check"]


def test_connector_redaction_masks_common_secret_shapes() -> None:
    ensure_libs_path()
    from xctx_connectors.runtime import redact_preview  # noqa: PLC0415

    text = "api_key=abc123 secret: xyz Authorization=Bearer token123 bearer abc.def password = pass123"
    redacted = redact_preview(text)

    assert "abc123" not in redacted
    assert "xyz" not in redacted
    assert "token123" not in redacted
    assert "abc.def" not in redacted
    assert "pass123" not in redacted
    assert redacted.count("<redacted>") >= 5


def test_connector_run_external_missing_executable_returns_structured_failure() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    result = runtime.run_external(
        ["/definitely/not/a/real/xctx-review-command"],
        timeout=0.1,
        max_output_bytes=1024,
    )

    assert result["ok"] is False
    assert result["timed_out"] is False
    assert result["exit_code"] is None
    assert result["error"]


def test_connector_supervisor_compact_flag_only_consumes_trailing_middleware_flag() -> None:
    ensure_libs_path()
    from xctx_connectors.middleware import _take_flag  # noqa: PLC0415

    present, args = _take_flag(["discover", "--compact", "query", "--compact"], "--compact")

    assert present is True
    assert args == ["discover", "--compact", "query"]


def test_external_command_error_text_is_redacted() -> None:
    ensure_libs_path()
    from xctx.ports.external_command import _adapter_error_message_from_text  # noqa: PLC0415

    message = _adapter_error_message_from_text(1, "", "api_key=abc123 bearer token456", "adapter.py")

    assert "abc123" not in message
    assert "token456" not in message
    assert message.count("<redacted>") == 2


def test_connector_run_external_empty_argv_returns_structured_failure() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    result = runtime.run_external([], timeout=1, max_output_bytes=1024)

    assert result["ok"] is False
    assert result["exit_code"] is None
    assert "argv" in result["error"]


def test_audit_converts_live_adapter_errors_to_failure_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain import audit as audit_domain  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    def boom(_store: dict, _subdomain: dict, _args: list[str]) -> dict:
        raise XctxError("adapter audit failed")

    monkeypatch.setattr(audit_domain, "call_external_command", boom)

    payload = audit_domain.audit_payload(load_store(root=ROOT), "stock_intelligence_hub::market_data_gateway")

    assert any(
        check.get("id") == "audit:stock_intelligence_hub:market_data_gateway:live_adapter_contract"
        and check.get("status") == "fail"
        and "adapter audit failed" in check.get("message", "")
        for check in payload["checks"]
    )
