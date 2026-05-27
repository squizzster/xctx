"""Protocol detail-level contract tests."""

from __future__ import annotations

import json

import pytest

from framework_helpers import ensure_libs_path, run_runtime_json

pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False


def test_orientation_surfaces_default_to_more_and_advertise_detail_controls() -> None:
    rc, root = run_runtime_json([])
    assert rc == 0
    assert root["record_type"] == "discovery"
    assert root["detail_level"] == "more"
    assert root["results"]["detail_controls"]["current"] == "more"

    rc, discover = run_runtime_json(["discover"])
    assert rc == 0
    assert discover["detail_level"] == "more"
    assert discover["results"]["detail_controls"]["current"] == "more"

    rc, version = run_runtime_json(["--version"])
    assert rc == 0
    assert version["detail_level"] == "more"
    assert version["results"]["detail_policy"]["levels"] == ["basic", "more", "max"]


def test_scoped_commands_default_to_basic() -> None:
    rc, payload = run_runtime_json(["discover", "stock_intelligence_hub::market_data_gateway"])
    assert rc == 0
    assert payload["detail_level"] == "basic"
    assert payload["results"]["projection"] == "compact"
    assert "configured_action_index" not in payload["results"]


def test_audit_basic_suppresses_forensic_config_and_max_restores_it() -> None:
    rc, basic = run_runtime_json(["audit", "root"])
    assert rc == 0
    assert basic["detail_level"] == "basic"
    assert basic["results"]["checks"] == []
    assert basic["results"]["omitted"]["config_fingerprint"] is True
    assert not any("loaded_config_files" in check for check in basic["results"].get("checks", []))
    assert not _contains_key({k: v for k, v in basic.items() if k != "results"}, "loaded_config_files")
    assert not _contains_key(basic["results"].get("checks", []), "fingerprint")

    rc, max_payload = run_runtime_json(["--max", "audit", "root"])
    assert rc == 0
    assert max_payload["detail_level"] == "max"
    assert _contains_key(max_payload, "loaded_config_files")
    assert _contains_key(max_payload, "fingerprint")


def test_observation_basic_suppresses_connector_diagnostics_and_max_restores_them() -> None:
    rc, basic = run_runtime_json(["observe", "file_manager::home_directory", "file:README.txt"])
    assert rc == 0
    assert basic["detail_level"] == "basic"
    assert not _contains_key(basic, "external_command")
    assert not _contains_key(basic, "command_status")
    assert not _contains_key(basic, "connector")
    assert "<workspace_root>" not in json.dumps(basic, sort_keys=True)

    rc, max_payload = run_runtime_json(["--max", "observe", "file_manager::home_directory", "file:README.txt"])
    assert rc == 0
    assert max_payload["detail_level"] == "max"
    assert _contains_key(max_payload, "external_command")
    assert _contains_key(max_payload, "command_status")
    assert _contains_key(max_payload, "connector")
    assert "<workspace_root>" in json.dumps(max_payload, sort_keys=True)


def test_projection_is_separate_from_detail_level() -> None:
    rc, payload = run_runtime_json([
        "discover",
        "stock_intelligence_hub::market_data_gateway::list_instruments",
        "--limit",
        "2",
        "--projection",
        "full",
    ])
    assert rc == 0
    assert payload["detail_level"] == "basic"
    assert payload["results"]["live_data"]["projection"] == "full"
    assert "connector" not in json.dumps(payload, sort_keys=True)
    first = payload["results"]["live_data"]["instruments"][0]
    assert "issuer_id" in first
    assert "market_series_run_cmd" in first


def test_obsolete_detail_and_shape_flags_are_rejected() -> None:
    rc, obsolete_detail = run_runtime_json(["--detail", "discover"])
    assert rc == 1
    assert obsolete_detail["record_type"] == "error"
    assert obsolete_detail["error"] == "unsupported global option --detail; use --basic, --more, or --max"

    rc, obsolete_shape = run_runtime_json([
        "discover",
        "stock_intelligence_hub::market_data_gateway",
        "--shape",
        "full",
    ])
    assert rc == 1
    assert obsolete_shape["record_type"] == "error"
    assert obsolete_shape["cmdline_arg"].endswith("--shape full")
    assert obsolete_shape["error"] == "unsupported --shape; use --projection compact|full"


def test_plan_execute_and_repair_are_projected_by_detail_level() -> None:
    rc, plan = run_runtime_json(["plan", "bring_online", "macro_intelligence_hub"])
    assert rc == 0
    assert plan["detail_level"] == "basic"
    assert not _contains_key(plan["results"], "planner_ledger")
    plan_id = plan["results"]["plan_id"]

    rc, execute = run_runtime_json(["execute", plan_id, "--commit"])
    assert rc == 0
    assert execute["detail_level"] == "basic"
    assert not _contains_key(execute["results"], "planner_binding")

    rc, repair = run_runtime_json(["repair", "offline:macro_intelligence_hub"])
    assert rc == 0
    assert repair["detail_level"] == "basic"
    assert repair["results"]["repairable"] is True
    assert not _contains_key(repair["results"], "repair_path")

    rc, repair_max = run_runtime_json(["--max", "repair", "offline:macro_intelligence_hub"])
    assert rc == 0
    assert repair_max["detail_level"] == "max"
    assert "repair_path" in repair_max["results"]


def test_redaction_no_longer_truncates_domain_strings() -> None:
    ensure_libs_path()
    from xctx.process.redaction import redact_value  # noqa: PLC0415

    text = "x" * 900
    assert redact_value({"content": {"text": text}})["content"]["text"] == text
