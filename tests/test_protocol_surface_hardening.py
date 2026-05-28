"""Additional local-gate tests for the hardened xctx protocol surface."""

from __future__ import annotations

import copy
import importlib.util
import sys

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


def test_removed_facade_modules_do_not_reappear() -> None:
    ensure_libs_path()

    removed = {
        "xctx.domain.agent_domains": ROOT / "libs/xctx/domain/agent_domains.py",
        "xctx.protocol.options": ROOT / "libs/xctx/protocol/options.py",
    }
    for module_name, source_path in removed.items():
        sys.modules.pop(module_name, None)
        assert not source_path.exists()
        assert importlib.util.find_spec(module_name) is None


def test_command_surface_audit_fails_closed_on_yaml_leaks() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.accessors import configured_command_names
    from xctx.protocol.command_policy import command_surface_check  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    check = command_surface_check(store)
    assert check["status"] == "pass"
    assert check["visible_commands"] == ["discover", "observe", "plan", "execute", "audit", "repair"]
    assert check["hidden_extension_commands"] == ["other"]

    store["protocol"]["command_groups"]["main"].extend(["status", "other"])
    store["protocol"]["command_groups"]["other"].append("doctor")
    store["commands"].setdefault("xctx", {})["status"] = {"old status command": "[]"}
    store["commands"].setdefault("xctx_other", {})["doctor"] = {"old extension": "[]"}

    leaked = command_surface_check(store)
    assert leaked["status"] == "fail"
    assert "status" in leaked["rejected_main_entries"]
    assert "other" in leaked["rejected_main_entries"]
    assert "doctor" in leaked["rejected_other_entries"]
    assert "status" in leaked["rejected_command_map_entries"]
    assert "doctor" in leaked["rejected_command_map_entries"]
    assert "status" not in configured_command_names(store)
    assert "doctor" not in configured_command_names(store)


def test_discover_id_target_conflict_is_refused() -> None:
    rc, payload = run_runtime_json(["discover", "stock_intelligence_hub", "--id", "file_manager"])
    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "invalid discover arguments: --id must appear before TARGET"
    assert payload["next_moves"] == [{"run_cmd": "./xctx discover TARGET"}, {"run_cmd": "./xctx discover --id ID"}]


def test_removed_name_shortcut_is_not_part_of_parser_contract() -> None:
    rc, payload = run_runtime_json(["discover", "--name", "Apple"])
    assert rc == 1
    assert payload["ok"] is False
    assert "unrecognized arguments: --name" in payload["error"]


def test_observe_id_conflicts_are_refused_before_routing() -> None:
    rc, payload = run_runtime_json(
        ["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--id", "GOOG"]
    )
    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "conflicting observation identifiers: positional ID and --id"

    rc, payload = run_runtime_json(["observe", "instrument:AAPL", "--id", "instrument:GOOG"])
    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "invalid observe arguments: --id requires a scoped target"
    assert payload["next_moves"] == [
        {"run_cmd": "./xctx observe <agent_domain>::<agent_subdomain> --id <id>"}
    ]


def test_observe_id_equals_form_is_supported_for_scoped_targets() -> None:
    rc, payload = run_runtime_json(["observe", "stock_intelligence_hub::market_data_gateway", "--id=instrument:aapl"])

    assert rc == 0
    assert payload["ok"] is True
    assert payload["results"]["live_data"]["object_type"] == "market_data_gateway_instrument_observation"


def test_observe_configured_option_requires_target_before_option() -> None:
    rc, payload = run_runtime_json(["observe", "--bars", "3", "stock_intelligence_hub::market_data_gateway", "AAPL"])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "invalid observe arguments: configured observe options require a scoped target"


def test_result_observation_rejects_extra_arguments(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.store.runtime_artifacts import isoformat_utc, utc_now, write_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    digest = "b" * 64
    write_runtime_artifact(
        store,
        "result",
        digest,
        {
            "result_id": f"result:{digest}",
            "commit_id": f"commit:{digest}",
            "plan_id": f"plan:sha256:{digest}",
            "status": "ready",
            "created_at": isoformat_utc(utc_now()),
            "expires_at": isoformat_utc(utc_now()),
            "heartbeat_at": isoformat_utc(utc_now()),
            "heartbeat": {"phase": "complete", "message": "ready"},
            "payload": {"value": "ok"},
        },
    )

    rc, payload = run_runtime_json(["observe", f"result:{digest}", "--bars", "3"])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "result observation does not accept extra arguments"
