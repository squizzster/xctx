"""Additional release-gate tests for the hardened xctx protocol surface."""

from __future__ import annotations

import copy
import importlib.util
import sys

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.release, pytest.mark.timeout(60)]


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
