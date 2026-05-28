"""Planned-effect smoke contracts for result handles and re-planning."""

from __future__ import annotations

import shlex
from datetime import datetime, timedelta, timezone

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(90)]


def _results(args: list[str]) -> dict:
    rc, payload = run_runtime_json(args)
    assert rc == 0, payload
    assert payload["ok"] is True
    return payload["results"]


def _plan_create_game() -> dict:
    return _results(
        [
            "plan",
            "guess_the_number_game::choose_random_number::choose_between_bounds",
            "--minimum",
            "1",
            "--maximum",
            "1000",
        ]
    )


def _commit(plan_id: str) -> dict:
    return _results(["execute", plan_id, "--commit"])


def _observe(result_id: str) -> dict:
    return _results(["observe", result_id])


def _direct_planned_effect(store: dict) -> dict:
    from xctx.domain.planning import plan_payload  # noqa: PLC0415

    return plan_payload(
        [
            "guess_the_number_game::choose_random_number::choose_between_bounds",
            "--minimum",
            "1",
            "--maximum",
            "1000",
        ],
        store,
    )


def _plan_command_to_args(command: str) -> list[str]:
    parts = shlex.split(command)
    assert parts[:2] == ["./xctx", "plan"]
    return ["plan", *parts[2:]]


def _minimal_materialized_plan(receipt: str) -> dict:
    return {
        "plan_id": f"plan:sha256:{receipt}",
        "receipt_sha256": receipt,
        "master_plan_id": f"master_plan:{receipt}",
        "sub_plan_id": f"sub_plan:{receipt}",
        "expected_commit_id": f"commit:{receipt}",
        "expected_result_id": f"result:{receipt}",
        "materialized_artifacts": {
            "status": "complete",
            "manifest_id": f"plan_manifest:{receipt}",
        },
    }


def test_planning_common_receipt_hash_is_canonical_json_order_independent() -> None:
    ensure_libs_path()
    from xctx.domain.planning_common import receipt_for_payload  # noqa: PLC0415

    assert receipt_for_payload({"b": 2, "a": 1}) == receipt_for_payload({"a": 1, "b": 2})
    assert receipt_for_payload({"a": 1}) != receipt_for_payload({"a": "1"})


def test_read_only_plan_payload_uses_unique_nonce_and_stable_intent_hash(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_read_only import read_only_plan_payload  # noqa: PLC0415
    from xctx.store.plans import read_plan  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    first = read_only_plan_payload(["discover", "root"], store)
    second = read_only_plan_payload(["discover", "root"], store)

    assert first["plan_id"] != second["plan_id"]
    assert first["receipt_sha256"] != second["receipt_sha256"]
    assert first["plan_nonce"] != second["plan_nonce"]
    assert first["canonical_intent_hash"] == second["canonical_intent_hash"]
    assert read_plan(store, first["receipt_sha256"]) == first
    assert read_plan(store, second["receipt_sha256"]) == second


def test_read_only_plan_payload_advertises_only_canonical_execute_handle(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_read_only import read_only_plan_payload  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = read_only_plan_payload(["discover", "root"], store)

    assert plan["status"] == "read_only_surface"
    assert plan["decision"] == "no_state_change_planned"
    assert plan["plan_id"] == f"plan:sha256:{plan['receipt_sha256']}"
    assert plan["accepted_execute_cmd"] == f"./xctx execute {plan['plan_id']} --commit"
    assert "canonical plan_id" in plan["receipt_note"]
    assert plan["receipt_sha5"] == plan["receipt_sha256"][:5]


def test_planning_ledger_plan_is_committed_normalizes_status() -> None:
    ensure_libs_path()
    from xctx.domain.planning_ledger import plan_is_committed  # noqa: PLC0415

    assert plan_is_committed({"execution_status": "committed"}) is True
    assert plan_is_committed({"execution_status": "COMMITTED"}) is True
    assert plan_is_committed({"execution_status": "planned"}) is False
    assert plan_is_committed({}) is False


def test_planning_ledger_context_match_reports_missing_and_stale_context() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_common import plan_context  # noqa: PLC0415
    from xctx.domain.planning_ledger import context_match  # noqa: PLC0415

    store = load_store(root=ROOT)
    current = plan_context(store)["config_sha256"]

    assert context_match(store, None) == (False, None, current)
    assert context_match(store, {"planner_context": {}}) == (False, None, current)
    assert context_match(store, {"planner_context": {"config_sha256": "0" * 64}}) == (False, "0" * 64, current)
    assert context_match(store, {"planner_context": {"config_sha256": current}}) == (True, current, current)


def test_planning_ledger_mark_plan_committed_persists_copy_with_handles(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_ledger import mark_plan_committed  # noqa: PLC0415
    from xctx.domain.planning_read_only import read_only_plan_payload  # noqa: PLC0415
    from xctx.store.plans import read_plan  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = read_only_plan_payload(["discover", "root"], store)
    receipt = plan["receipt_sha256"]
    committed_at = "2026-05-28T00:00:00+00:00"

    mark_plan_committed(
        store,
        plan,
        committed_at=committed_at,
        commit_id=f"commit:{receipt}",
        result_id=f"result:{receipt}",
    )
    persisted = read_plan(store, receipt)

    assert plan["execution_status"] == "planned"
    assert persisted is not None
    assert persisted["execution_status"] == "committed"
    assert persisted["committed_at"] == committed_at
    assert persisted["commit_id"] == f"commit:{receipt}"
    assert persisted["result_id"] == f"result:{receipt}"


def test_planning_intent_contract_accepts_only_planned_effect_markers() -> None:
    ensure_libs_path()
    from xctx.domain.planning_intent import planning_contract  # noqa: PLC0415

    assert planning_contract({"planning": {"planned_effect": True}}) == {"planned_effect": True}
    assert planning_contract({"planning": {"mode": "planned_effect"}}) == {"mode": "planned_effect"}
    assert planning_contract({"planning": {"mode": "read_only"}}) == {}
    assert planning_contract({"planning": []}) == {}
    assert planning_contract({}) == {}


def test_planning_intent_resolves_scoped_planned_action() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_intent import resolve_planned_action  # noqa: PLC0415

    store = load_store(root=ROOT)
    planned = resolve_planned_action(
        store,
        "guess_the_number_game::choose_random_number::choose_between_bounds",
        ["--minimum", "1", "--maximum", "1000"],
    )

    assert planned is not None
    assert planned.domain_id == "guess_the_number_game"
    assert planned.subdomain_id == "choose_random_number"
    assert planned.action_name == "choose_between_bounds"
    assert planned.domain_action_name is None
    assert planned.planning["planned_effect"] is True


def test_planning_intent_ignores_non_planned_or_unscoped_operations() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_intent import resolve_planned_action  # noqa: PLC0415

    store = load_store(root=ROOT)

    assert resolve_planned_action(store, "discover", ["root"]) is None
    assert resolve_planned_action(store, "stock_intelligence_hub::market_data_gateway::list_instruments", []) is None


def test_planning_intent_parse_args_coerces_and_encodes_options() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_intent import parse_planned_action_args, resolve_planned_action  # noqa: PLC0415

    store = load_store(root=ROOT)
    planned = resolve_planned_action(
        store,
        "guess_the_number_game::choose_random_number::choose_between_bounds",
        ["--minimum", "1", "--maximum", "1000"],
    )
    assert planned is not None

    parsed = parse_planned_action_args(store, planned, ["--minimum", "1", "--maximum", "1000"])

    assert parsed.values == {"minimum": 1, "maximum": 1000}
    assert parsed.positional_args == []
    assert parsed.adapter_args == ["--minimum", "1", "--maximum", "1000"]


def test_planning_intent_parse_args_rejects_missing_required_option() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_intent import parse_planned_action_args, resolve_planned_action  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = load_store(root=ROOT)
    planned = resolve_planned_action(
        store,
        "guess_the_number_game::choose_random_number::choose_between_bounds",
        ["--minimum", "1"],
    )
    assert planned is not None

    with pytest.raises(XctxError, match="missing required plan option: --maximum"):
        parse_planned_action_args(store, planned, ["--minimum", "1"])


def test_planning_intent_coerce_option_rejects_boolean_numbers() -> None:
    ensure_libs_path()
    from xctx.domain.planning_intent import coerce_plan_option  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    with pytest.raises(XctxError, match="invalid integer for --limit"):
        coerce_plan_option(True, {"_option_type": "int", "_primary_flag": "--limit"})
    with pytest.raises(XctxError, match="invalid number for --ratio"):
        coerce_plan_option(False, {"_option_type": "float", "_primary_flag": "--ratio"})
    assert coerce_plan_option("false", {"_option_type": "bool", "_primary_flag": "--flag"}) is False


def test_planning_intent_defaults_respect_planning_then_subdomain_then_fallback() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_intent import PlannedAction, planning_default  # noqa: PLC0415

    store = load_store(root=ROOT)
    planned = PlannedAction(
        domain_id="guess_the_number_game",
        subdomain_id="choose_random_number",
        action_name="choose_between_bounds",
        action={},
        planning={"result_ttl_seconds": 123},
    )
    inherited = PlannedAction(
        domain_id="guess_the_number_game",
        subdomain_id="choose_random_number",
        action_name="choose_between_bounds",
        action={},
        planning={},
    )

    assert planning_default(store, planned, "result_ttl_seconds", 300) == 123
    assert planning_default(store, inherited, "result_ttl_seconds", 300) == 900
    assert planning_default(store, inherited, "missing_default", "fallback") == "fallback"


def test_planning_intent_render_template_replaces_longer_keys_first() -> None:
    ensure_libs_path()
    from xctx.domain.planning_intent import render_template  # noqa: PLC0415

    rendered = render_template(
        "{{ id }} -> {{ id_long }} -> {{id_long}} -> {{ missing }}",
        {"id": "A", "id_long": "ALPHA"},
    )

    assert rendered == "A -> ALPHA -> ALPHA -> {{ missing }}"


def test_planned_effect_builder_materializes_plan_bundle_and_ledger(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_intent import resolve_planned_action  # noqa: PLC0415
    from xctx.domain.planning_planned_effects import planned_effect_plan_payload  # noqa: PLC0415
    from xctx.store.plans import read_plan  # noqa: PLC0415
    from xctx.store.runtime_artifacts import read_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    args = [
        "guess_the_number_game::choose_random_number::choose_between_bounds",
        "--minimum",
        "1",
        "--maximum",
        "1000",
    ]
    planned = resolve_planned_action(store, args[0], args[1:])
    assert planned is not None

    payload = planned_effect_plan_payload(args, store, planned)
    receipt = payload["receipt_sha256"]

    assert read_plan(store, receipt) == payload
    assert read_runtime_artifact(store, "master_plan", receipt)["plan_id"] == payload["plan_id"]
    assert read_runtime_artifact(store, "sub_plan", receipt)["planned_effect"] == payload["planned_effect"]
    assert read_runtime_artifact(store, "plan_manifest", receipt)["manifest_id"] == payload["materialization_manifest_id"]


def test_planned_effect_builder_renders_description_and_handle_commands(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_intent import resolve_planned_action  # noqa: PLC0415
    from xctx.domain.planning_planned_effects import planned_effect_plan_payload  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    args = [
        "guess_the_number_game::choose_random_number::choose_between_bounds",
        "--minimum",
        "3",
        "--maximum",
        "8",
    ]
    planned = resolve_planned_action(store, args[0], args[1:])
    assert planned is not None

    payload = planned_effect_plan_payload(args, store, planned)

    assert "between 3 and 8" in payload["description"]
    assert payload["accepted_execute_cmd"] == f"./xctx execute {payload['plan_id']} --commit"
    assert payload["discover_master_plan_cmd"] == f"./xctx discover {payload['master_plan_id']}"
    assert payload["observe_result_cmd"] == f"./xctx observe {payload['expected_result_id']}"
    assert payload["materialized_artifacts"]["manifest_id"] == payload["materialization_manifest_id"]


def test_planned_effect_builder_uses_unique_receipts_for_repeated_same_intent(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_intent import resolve_planned_action  # noqa: PLC0415
    from xctx.domain.planning_planned_effects import planned_effect_plan_payload  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    args = [
        "guess_the_number_game::choose_random_number::choose_between_bounds",
        "--minimum",
        "1",
        "--maximum",
        "1000",
    ]
    planned = resolve_planned_action(store, args[0], args[1:])
    assert planned is not None

    first = planned_effect_plan_payload(args, store, planned)
    second = planned_effect_plan_payload(args, store, planned)

    assert first["plan_id"] != second["plan_id"]
    assert first["receipt_sha256"] != second["receipt_sha256"]
    assert first["planned_effect"]["input_values"] == second["planned_effect"]["input_values"]
    assert first["planned_effect"]["adapter_args"] == second["planned_effect"]["adapter_args"]


def test_planned_number_creation_records_commit_and_result_contract(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    plan = _plan_create_game()

    assert plan["status"] == "planned_effect"
    assert plan["decision"] == "commit_required"
    assert plan["writes_to_db"] is True
    assert plan["can_be_reversed"] is False
    assert plan["can_be_repaired"] is False
    assert plan["materialization_manifest_id"].startswith("plan_manifest:")
    assert plan["master_plan_id"].startswith("master_plan:")
    assert plan["sub_plan_id"].startswith("sub_plan:")
    assert plan["expected_commit_id"].startswith("commit:")
    assert plan["expected_result_id"].startswith("result:")
    assert plan["expected_result_id"].endswith(plan["receipt_sha256"])
    assert plan["materialized_artifacts"]["status"] == "complete"
    assert plan["materialized_artifacts"]["manifest_id"] == plan["materialization_manifest_id"]
    assert "hidden number" in plan["description_of_what_will_happen"]

    manifest_path = tmp_path / "plan_manifest" / f"{plan['receipt_sha256']}.json"
    master_plan_path = tmp_path / "master_plan" / f"{plan['receipt_sha256']}.json"
    sub_plan_path = tmp_path / "sub_plan" / f"{plan['receipt_sha256']}.json"
    assert manifest_path.exists()
    assert master_plan_path.exists()
    assert sub_plan_path.exists()

    manifest = _results(["discover", plan["materialization_manifest_id"]])
    assert manifest["artifact_kind"] == "plan_manifest"
    assert manifest["object_type"] == "plan_materialization_manifest"
    assert manifest["status"] == "complete"
    assert manifest["artifacts"]["master_plan"] == plan["master_plan_id"]
    assert manifest["artifacts"]["sub_plan"] == plan["sub_plan_id"]

    discovered = _results(["discover", plan["master_plan_id"]])
    assert discovered["artifact_kind"] == "master_plan"
    assert discovered["master_plan_id"] == plan["master_plan_id"]
    assert discovered["status"] == "planned"
    assert discovered["execute_plan_cmd"] == plan["accepted_execute_cmd"]

    commit = _commit(plan["plan_id"])
    assert commit["status"] == "committed"
    assert commit["commit_id"] == plan["expected_commit_id"]
    assert commit["result_id"] == plan["expected_result_id"]
    assert commit["mutations_applied"] == 1

    committed_master_plan = _results(["discover", plan["master_plan_id"]])
    assert committed_master_plan["status"] == "committed"
    assert committed_master_plan["execution_status"] == "committed"
    assert committed_master_plan["result_id"] == commit["result_id"]

    observed = _observe(commit["result_id"])
    assert observed["status"] == "ready"
    assert observed["heartbeat"]["phase"] == "game_ready"
    assert observed["payload"]["object_type"] == "guess_the_number_game_created"
    assert observed["payload"]["range"] == {"min": 1, "max": 1000}
    assert "secret_number" not in observed["payload"]
    assert observed["payload"]["next_plan_command"].startswith(
        "./xctx plan guess_the_number_game::guess_number::submit_guess"
    )


def test_guess_plans_replan_until_yes_within_binary_search_bound(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    create = _commit(_plan_create_game()["plan_id"])
    game_result_id = create["result_id"]
    observed_game = _observe(game_result_id)
    next_plan_command = observed_game["payload"]["next_plan_command"]

    turns = 0
    feedback_seen: list[str] = []
    last_payload: dict | None = None
    while next_plan_command:
        turns += 1
        assert turns <= 10
        guess_plan = _results(_plan_command_to_args(next_plan_command))
        assert guess_plan["status"] == "planned_effect"
        assert game_result_id in guess_plan["description_of_what_will_happen"]
        guess_commit = _commit(guess_plan["plan_id"])
        guess_observed = _observe(guess_commit["result_id"])
        last_payload = guess_observed["payload"]
        feedback_seen.append(last_payload["feedback"])
        assert last_payload["feedback"] in {"higher", "lower", "yes"}
        assert "secret_number" not in last_payload
        if last_payload["correct"]:
            assert last_payload["feedback"] == "yes"
            assert last_payload["next_plan_command"] is None
            break
        next_plan_command = last_payload["next_plan_command"]

    assert last_payload is not None
    assert last_payload["correct"] is True
    assert turns <= 10
    assert feedback_seen[-1] == "yes"


def test_reexecuting_committed_plan_is_refused_with_existing_result_guidance(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    plan = _plan_create_game()
    first = _commit(plan["plan_id"])
    rc, second = run_runtime_json(["execute", plan["plan_id"], "--commit"])

    assert rc == 1
    assert first["status"] == "committed"
    assert second["ok"] is False
    assert second["error"] == "plan_already_committed"
    assert second["results"]["result_id"] == first["result_id"]
    assert second["results"]["mutations_applied"] == 0


def test_execute_refuses_unmaterialized_planned_effect_without_adapter_call(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)
    (tmp_path / "master_plan" / f"{plan['receipt_sha256']}.json").unlink()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("adapter should not be invoked for an unmaterialized plan")

    monkeypatch.setattr("xctx.domain.planning.call_external_command", fail_if_called)

    result = execute_payload([plan["plan_id"]], True, store)

    assert result["ok"] is False
    assert result["error"] == "plan_not_materialized"
    assert result["mutations_applied"] == 0


def test_execute_refuses_missing_sub_plan_materialization_without_adapter_call(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)
    (tmp_path / "sub_plan" / f"{plan['receipt_sha256']}.json").unlink()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("adapter should not be invoked for an unmaterialized plan")

    monkeypatch.setattr("xctx.domain.planning.call_external_command", fail_if_called)

    result = execute_payload([plan["plan_id"]], True, store)

    assert result["ok"] is False
    assert result["error"] == "plan_not_materialized"
    assert result["mutations_applied"] == 0


def test_plan_materialization_manifest_published_after_artifacts_before_plan_record(
    tmp_path,
    monkeypatch,
) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain import planning_materialization, planning_planned_effects  # noqa: PLC0415
    from xctx.store.runtime_artifacts import read_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    order: list[str] = []
    original_write_runtime_artifact = planning_materialization.write_runtime_artifact
    original_write_plan = planning_planned_effects.write_plan

    def recording_write_runtime_artifact(store_arg, kind, digest, payload):
        order.append(kind)
        original_write_runtime_artifact(store_arg, kind, digest, payload)

    def checking_write_plan(store_arg, payload):
        order.append("plan_record")
        assert order[:3] == ["master_plan", "sub_plan", "plan_manifest"]
        manifest = read_runtime_artifact(store_arg, "plan_manifest", payload["receipt_sha256"])
        assert manifest is not None
        assert manifest["status"] == "complete"
        assert manifest["plan_id"] == payload["plan_id"]
        original_write_plan(store_arg, payload)

    monkeypatch.setattr(planning_materialization, "write_runtime_artifact", recording_write_runtime_artifact)
    monkeypatch.setattr(planning_planned_effects, "write_plan", checking_write_plan)

    plan = _direct_planned_effect(store)

    assert plan["materialization_manifest_id"].startswith("plan_manifest:")
    assert order == ["master_plan", "sub_plan", "plan_manifest", "plan_record"]


def test_plan_materialization_manifest_contract_is_stable() -> None:
    ensure_libs_path()
    from xctx.domain.planning_materialization import plan_materialization_manifest  # noqa: PLC0415

    receipt = "a" * 64
    manifest = plan_materialization_manifest(
        plan_id=f"plan:sha256:{receipt}",
        receipt=receipt,
        master_plan_id=f"master_plan:{receipt}",
        sub_plan_id=f"sub_plan:{receipt}",
        commit_id=f"commit:{receipt}",
        result_id=f"result:{receipt}",
    )

    assert manifest["object_type"] == "plan_materialization_manifest"
    assert manifest["schema_version"] == "xctx.plan_materialization.v1"
    assert manifest["manifest_id"] == f"plan_manifest:{receipt}"
    assert manifest["artifacts"] == {
        "master_plan": f"master_plan:{receipt}",
        "sub_plan": f"sub_plan:{receipt}",
        "expected_commit": f"commit:{receipt}",
        "expected_result": f"result:{receipt}",
    }
    assert manifest["publish_order"] == ["master_plan", "sub_plan", "plan_manifest", "plan_record"]


def test_plan_materialization_bundle_writes_exact_runtime_artifacts(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_materialization import (  # noqa: PLC0415
        plan_materialization_manifest,
        write_plan_materialization_bundle,
    )
    from xctx.store.runtime_artifacts import read_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    receipt = "b" * 64
    plan = _minimal_materialized_plan(receipt)
    master_plan = {"object_type": "master_plan", "plan_id": plan["plan_id"], "master_plan_id": plan["master_plan_id"]}
    sub_plan = {"object_type": "sub_plan", "plan_id": plan["plan_id"], "sub_plan_id": plan["sub_plan_id"]}
    manifest = plan_materialization_manifest(
        plan_id=plan["plan_id"],
        receipt=receipt,
        master_plan_id=plan["master_plan_id"],
        sub_plan_id=plan["sub_plan_id"],
        commit_id=plan["expected_commit_id"],
        result_id=plan["expected_result_id"],
    )

    write_plan_materialization_bundle(
        store,
        receipt=receipt,
        master_plan=master_plan,
        sub_plan=sub_plan,
        manifest=manifest,
    )

    assert read_runtime_artifact(store, "master_plan", receipt) == master_plan
    assert read_runtime_artifact(store, "sub_plan", receipt) == sub_plan
    assert read_runtime_artifact(store, "plan_manifest", receipt) == manifest


def test_plan_materialization_verifier_accepts_complete_bundle(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_materialization import (  # noqa: PLC0415
        plan_materialization_manifest,
        verify_plan_materialization,
        write_plan_materialization_bundle,
    )

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    receipt = "c" * 64
    plan = _minimal_materialized_plan(receipt)
    master_plan = {"plan_id": plan["plan_id"], "master_plan_id": plan["master_plan_id"]}
    sub_plan = {"plan_id": plan["plan_id"], "sub_plan_id": plan["sub_plan_id"]}
    manifest = plan_materialization_manifest(
        plan_id=plan["plan_id"],
        receipt=receipt,
        master_plan_id=plan["master_plan_id"],
        sub_plan_id=plan["sub_plan_id"],
        commit_id=plan["expected_commit_id"],
        result_id=plan["expected_result_id"],
    )
    write_plan_materialization_bundle(
        store,
        receipt=receipt,
        master_plan=master_plan,
        sub_plan=sub_plan,
        manifest=manifest,
    )

    ok, verified_master, verified_sub, verified_manifest, errors = verify_plan_materialization(store, plan, receipt)

    assert ok is True
    assert verified_master == master_plan
    assert verified_sub == sub_plan
    assert verified_manifest == manifest
    assert errors == []


def test_plan_materialization_verifier_reports_missing_bundle_parts(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_materialization import verify_plan_materialization  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    receipt = "d" * 64

    ok, master_plan, sub_plan, manifest, errors = verify_plan_materialization(store, {}, receipt)

    assert ok is False
    assert master_plan is None
    assert sub_plan is None
    assert manifest is None
    assert {
        "plan_missing_materialized_artifacts",
        "plan_materialization_not_complete",
        "plan_manifest_ref_mismatch",
        "missing_plan_manifest",
        "missing_master_plan",
        "missing_sub_plan",
    }.issubset(set(errors))


def test_plan_materialization_verifier_reports_commit_and_result_mismatches(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_materialization import (  # noqa: PLC0415
        plan_materialization_manifest,
        verify_plan_materialization,
        write_plan_materialization_bundle,
    )

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    receipt = "e" * 64
    plan = _minimal_materialized_plan(receipt)
    manifest = plan_materialization_manifest(
        plan_id=plan["plan_id"],
        receipt=receipt,
        master_plan_id=plan["master_plan_id"],
        sub_plan_id=plan["sub_plan_id"],
        commit_id=f"commit:{'f' * 64}",
        result_id=f"result:{'f' * 64}",
    )
    write_plan_materialization_bundle(
        store,
        receipt=receipt,
        master_plan={"plan_id": plan["plan_id"], "master_plan_id": plan["master_plan_id"]},
        sub_plan={"plan_id": plan["plan_id"], "sub_plan_id": plan["sub_plan_id"]},
        manifest=manifest,
    )

    ok, _master_plan, _sub_plan, _manifest, errors = verify_plan_materialization(store, plan, receipt)

    assert ok is False
    assert "plan_manifest_expected_commit_mismatch" in errors
    assert "plan_manifest_expected_result_mismatch" in errors


def test_execute_refuses_missing_plan_manifest_without_adapter_call(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)
    (tmp_path / "plan_manifest" / f"{plan['receipt_sha256']}.json").unlink()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("adapter should not be invoked without a materialization manifest")

    monkeypatch.setattr("xctx.domain.planning.call_external_command", fail_if_called)

    result = execute_payload([plan["plan_id"]], True, store)

    assert result["ok"] is False
    assert result["error"] == "plan_not_materialized"
    assert "missing_plan_manifest" in result["materialization_errors"]
    assert result["mutations_applied"] == 0


def test_execute_refuses_corrupt_plan_manifest_without_adapter_call(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415
    from xctx.store.runtime_artifacts import read_runtime_artifact, write_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)
    manifest = read_runtime_artifact(store, "plan_manifest", plan["receipt_sha256"])
    assert manifest is not None
    manifest["artifacts"]["sub_plan"] = "sub_plan:" + ("f" * 64)
    write_runtime_artifact(store, "plan_manifest", plan["receipt_sha256"], manifest)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("adapter should not be invoked with a corrupt materialization manifest")

    monkeypatch.setattr("xctx.domain.planning.call_external_command", fail_if_called)

    result = execute_payload([plan["plan_id"]], True, store)

    assert result["ok"] is False
    assert result["error"] == "plan_not_materialized"
    assert "plan_manifest_sub_plan_mismatch" in result["materialization_errors"]
    assert result["mutations_applied"] == 0


def test_commit_execution_claim_is_exclusive(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.store.runtime_artifacts import create_commit_execution_claim, read_commit_execution_claim  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)
    receipt = plan["receipt_sha256"]
    first = {
        "object_type": "commit_execution_claim",
        "plan_id": plan["plan_id"],
        "commit_id": plan["expected_commit_id"],
        "result_id": plan["expected_result_id"],
        "receipt_sha256": receipt,
        "owner_id": "first",
        "status": "claimed",
    }
    second = {**first, "owner_id": "second", "status": "running"}

    assert create_commit_execution_claim(store, receipt, first) is True
    assert create_commit_execution_claim(store, receipt, second) is False

    persisted = read_commit_execution_claim(store, receipt)
    assert persisted is not None
    assert persisted["owner_id"] == "first"
    assert persisted["status"] == "claimed"


def test_commit_claim_builder_records_execution_identity() -> None:
    ensure_libs_path()
    from xctx.domain.planning_commit_state import new_execution_claim  # noqa: PLC0415

    receipt = "1" * 64
    claim = new_execution_claim(
        plan={"plan_id": f"plan:sha256:{receipt}"},
        receipt=receipt,
        commit_id=f"commit:{receipt}",
        result_id=f"result:{receipt}",
        current_context_sha="2" * 64,
    )

    assert claim["object_type"] == "commit_execution_claim"
    assert claim["plan_id"] == f"plan:sha256:{receipt}"
    assert claim["commit_id"] == f"commit:{receipt}"
    assert claim["result_id"] == f"result:{receipt}"
    assert claim["receipt_sha256"] == receipt
    assert claim["config_fingerprint"] == "2" * 64
    assert claim["status"] == "claimed"
    assert claim["started_at"] is None
    assert claim["completed_at"] is None
    assert claim["heartbeat_at"] == claim["claimed_at"]
    assert claim["recovery_policy"] == "never_reinvoke_adapter_without_operator_repair"
    assert len(claim["claim_nonce"]) == 64


def test_commit_claim_status_normalizes_missing_and_whitespace() -> None:
    ensure_libs_path()
    from xctx.domain.planning_commit_state import claim_status  # noqa: PLC0415

    assert claim_status(None) == ""
    assert claim_status({}) == ""
    assert claim_status({"status": " Running "}) == "running"
    assert claim_status({"status": "FINALIZING"}) == "finalizing"


def test_commit_claim_staleness_uses_heartbeat_then_claimed_at() -> None:
    ensure_libs_path()
    from xctx.domain.planning_commit_state import RUNNING_CLAIM_STALE_SECONDS, claim_is_stale  # noqa: PLC0415
    from xctx.store.runtime_artifacts import isoformat_utc, utc_now  # noqa: PLC0415

    current = utc_now()
    stale = isoformat_utc(current - timedelta(seconds=RUNNING_CLAIM_STALE_SECONDS + 1))
    fresh = isoformat_utc(current - timedelta(seconds=RUNNING_CLAIM_STALE_SECONDS - 1))

    assert claim_is_stale({"heartbeat_at": stale, "claimed_at": fresh}, now=current) is True
    assert claim_is_stale({"claimed_at": fresh}, now=current) is False
    assert claim_is_stale({"heartbeat_at": "not-a-date", "claimed_at": "also-bad"}, now=current) is True


def test_commit_claim_abandonment_writes_repair_required_state(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning_commit_state import RUNNING_CLAIM_STALE_SECONDS, mark_claim_abandoned_if_stale  # noqa: PLC0415
    from xctx.store.runtime_artifacts import isoformat_utc, read_commit_execution_claim, utc_now  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    receipt = "3" * 64
    stale_time = isoformat_utc(utc_now() - timedelta(seconds=RUNNING_CLAIM_STALE_SECONDS + 1))
    claim = {
        "object_type": "commit_execution_claim",
        "plan_id": f"plan:sha256:{receipt}",
        "receipt_sha256": receipt,
        "status": "running",
        "heartbeat_at": stale_time,
        "claimed_at": stale_time,
    }

    abandoned = mark_claim_abandoned_if_stale(store, receipt, claim)
    stored = read_commit_execution_claim(store, receipt)

    assert abandoned["status"] == "abandoned"
    assert abandoned["recovery_policy"] == "operator_repair_required_before_reinvoke"
    assert stored == abandoned


def test_terminal_commit_claim_is_not_abandoned_or_rewritten(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_commit_state  # noqa: PLC0415

    def fail_write(*_args, **_kwargs):
        raise AssertionError("terminal claims must not be rewritten")

    claim = {"status": "failed", "heartbeat_at": "not-a-date"}
    monkeypatch.setattr(planning_commit_state, "write_commit_execution_claim", fail_write)

    assert planning_commit_state.mark_claim_abandoned_if_stale({}, "4" * 64, claim) is claim


def test_planning_payload_heartbeat_uses_configured_values_with_fallbacks() -> None:
    ensure_libs_path()
    from xctx.domain.planning_payloads import heartbeat  # noqa: PLC0415

    assert heartbeat(
        {"running_heartbeat": {"phase": "custom_running", "message": "Working"}},
        "running_heartbeat",
        "fallback_phase",
        "Fallback message",
    ) == {"phase": "custom_running", "message": "Working"}
    assert heartbeat(
        {"running_heartbeat": {"phase": "", "message": ""}},
        "running_heartbeat",
        "fallback_phase",
        "Fallback message",
    ) == {"phase": "fallback_phase", "message": "Fallback message"}
    assert heartbeat({}, "running_heartbeat", "fallback_phase", "Fallback message") == {
        "phase": "fallback_phase",
        "message": "Fallback message",
    }


def test_planning_payload_adapter_failure_detection_is_protocol_based() -> None:
    ensure_libs_path()
    from xctx.domain.planning_payloads import adapter_payload_failed  # noqa: PLC0415

    assert adapter_payload_failed({"object_type": "adapter_error"}) is True
    assert adapter_payload_failed({"object_type": "demo", "command_status": {"ok": False}}) is True
    assert adapter_payload_failed({"object_type": "demo", "command_status": {"ok": True}}) is False
    assert adapter_payload_failed({"object_type": "demo", "command_status": "failed"}) is False


def test_planning_payload_already_committed_prefers_recorded_result_handle() -> None:
    ensure_libs_path()
    from xctx.domain.planning_payloads import plan_already_committed_payload  # noqa: PLC0415

    receipt = "5" * 64
    resolved = type("Resolved", (), {"matches": [receipt[:12]]})()
    payload = plan_already_committed_payload(
        requested_plan=f"plan:sha256:{receipt}",
        plan={
            "plan_id": f"plan:sha256:{receipt}",
            "receipt_sha256": receipt,
            "operation": "demo",
            "expected_commit_id": f"commit:{receipt}",
            "expected_result_id": f"result:{receipt}",
        },
        resolved=resolved,
        context_matches=True,
        planned_context_sha="6" * 64,
        current_context_sha="6" * 64,
    )

    assert payload["ok"] is False
    assert payload["error"] == "plan_already_committed"
    assert payload["commit_id"] == f"commit:{receipt}"
    assert payload["result_id"] == f"result:{receipt}"
    assert payload["observe_result_cmd"] == f"./xctx observe result:{receipt}"
    assert payload["planner_binding"]["short_receipt_matches"] == [receipt[:12]]


def test_planning_payload_execution_refusal_running_status_and_observe_next_move() -> None:
    ensure_libs_path()
    from xctx.domain.planning_payloads import execution_claim_refusal_payload  # noqa: PLC0415

    receipt = "7" * 64
    resolved = type("Resolved", (), {"matches": []})()
    payload = execution_claim_refusal_payload(
        requested_plan=f"plan:sha256:{receipt}",
        resolved=resolved,
        plan={"plan_id": f"plan:sha256:{receipt}", "operation": "demo"},
        receipt=receipt,
        commit_id=f"commit:{receipt}",
        result_id=f"result:{receipt}",
        context_matches=True,
        planned_context_sha="8" * 64,
        current_context_sha="8" * 64,
        reason="planned_effect_execution_in_progress",
        existing_result={"status": "running"},
        claim={"status": " Running "},
    )

    assert payload["status"] == "running"
    assert payload["execution_claim_status"] == "running"
    assert payload["existing_result_status"] == "running"
    assert payload["next_move"] == f"./xctx observe result:{receipt}"


def test_planning_payload_execution_refusal_repair_status_and_materialization_errors() -> None:
    ensure_libs_path()
    from xctx.domain.planning_payloads import execution_claim_refusal_payload  # noqa: PLC0415

    receipt = "9" * 64
    resolved = type("Resolved", (), {"matches": []})()
    payload = execution_claim_refusal_payload(
        requested_plan=f"plan:sha256:{receipt}",
        resolved=resolved,
        plan={"plan_id": f"plan:sha256:{receipt}", "operation": "demo"},
        receipt=receipt,
        commit_id=f"commit:{receipt}",
        result_id=f"result:{receipt}",
        context_matches=False,
        planned_context_sha="a" * 64,
        current_context_sha="b" * 64,
        reason="plan_not_materialized",
        existing_commit={"status": "claimed"},
        materialization_errors=["missing_plan_manifest"],
    )

    assert payload["status"] == "repair_required"
    assert payload["existing_commit_status"] == "claimed"
    assert payload["existing_result_status"] is None
    assert payload["materialization_errors"] == ["missing_plan_manifest"]
    assert payload["next_move"] == "./xctx repair <finding_id>"
    assert payload["planner_binding"]["context_fingerprint_verified"] is False


def test_planning_payload_failed_result_uses_terminal_ttl_and_handles() -> None:
    ensure_libs_path()
    from xctx.domain.planning_payloads import failed_result_payload  # noqa: PLC0415
    from xctx.store.runtime_artifacts import parse_utc_timestamp  # noqa: PLC0415

    receipt = "c" * 64
    payload = failed_result_payload(
        plan={"plan_id": f"plan:sha256:{receipt}"},
        planned_effect={"result_ttl_seconds": 120},
        receipt=receipt,
        message="adapter failed",
    )
    created_at = parse_utc_timestamp(payload["created_at"])
    expires_at = parse_utc_timestamp(payload["expires_at"])

    assert payload["status"] == "failed"
    assert payload["result_id"] == f"result:{receipt}"
    assert payload["commit_id"] == f"commit:{receipt}"
    assert payload["plan_id"] == f"plan:sha256:{receipt}"
    assert payload["payload"] is None
    assert payload["heartbeat"] == {"phase": "failed", "message": "adapter failed"}
    assert created_at is not None
    assert expires_at is not None
    assert expires_at - created_at == timedelta(seconds=120)


def test_planning_execution_commit_context_args_are_ordered() -> None:
    ensure_libs_path()
    from xctx.domain.planning_execution import commit_context_args  # noqa: PLC0415

    assert commit_context_args(
        canonical_plan_id="plan:sha256:abc",
        commit_id="commit:abc",
        result_id="result:abc",
    ) == [
        "--xctx-plan-id",
        "plan:sha256:abc",
        "--xctx-commit-id",
        "commit:abc",
        "--xctx-result-id",
        "result:abc",
    ]


def test_planning_execution_running_artifacts_include_lease_and_metadata() -> None:
    ensure_libs_path()
    from xctx.domain.planning_commit_state import RUNNING_CLAIM_STALE_SECONDS  # noqa: PLC0415
    from xctx.domain.planning_execution import running_execution_artifacts  # noqa: PLC0415
    from xctx.store.runtime_artifacts import parse_utc_timestamp  # noqa: PLC0415

    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    planned_effect = {
        "agent_domain": "demo_domain",
        "agent_subdomain": "demo_subdomain",
        "action": "create",
        "implemented_by": "demo_domain::demo_subdomain::create",
        "commit_adapter_command": "create",
        "ignored": "not framework metadata",
        "running_heartbeat": {"phase": "custom", "message": "Running"},
    }

    commit, running_result = running_execution_artifacts(
        canonical_plan_id="plan:sha256:abc",
        commit_id="commit:abc",
        result_id="result:abc",
        planned_effect=planned_effect,
        now=now,
    )

    assert commit["status"] == "claimed"
    assert commit["planned_effect"] == {
        "agent_domain": "demo_domain",
        "agent_subdomain": "demo_subdomain",
        "action": "create",
        "implemented_by": "demo_domain::demo_subdomain::create",
        "commit_adapter_command": "create",
    }
    assert running_result["status"] == "running"
    assert running_result["heartbeat"] == {"phase": "custom", "message": "Running"}
    assert running_result["payload"] is None
    assert parse_utc_timestamp(running_result["lease_expires_at"]) - parse_utc_timestamp(
        running_result["created_at"]
    ) == timedelta(seconds=RUNNING_CLAIM_STALE_SECONDS)


def test_planning_execution_materialized_artifact_state_transitions() -> None:
    ensure_libs_path()
    from xctx.domain.planning_execution import materialized_artifact_committed, materialized_artifact_committing  # noqa: PLC0415

    base = {"plan_id": "plan:sha256:abc", "custom": "kept"}
    committing = materialized_artifact_committing(
        base,
        commit_id="commit:abc",
        result_id="result:abc",
        committed_at="2026-05-28T12:00:00+00:00",
    )
    committed = materialized_artifact_committed(
        base,
        commit_id="commit:abc",
        result_id="result:abc",
        committed_at="2026-05-28T12:01:00+00:00",
        failed=True,
    )

    assert base == {"plan_id": "plan:sha256:abc", "custom": "kept"}
    assert committing["status"] == "committing"
    assert committing["execution_status"] == "committing"
    assert committing["custom"] == "kept"
    assert committed["status"] == "committed"
    assert committed["execution_status"] == "committed"
    assert committed["failed"] is True


def test_planning_execution_terminal_result_success_ttl_starts_at_finished_time() -> None:
    ensure_libs_path()
    from xctx.domain.planning_execution import terminal_result_payload  # noqa: PLC0415
    from xctx.store.runtime_artifacts import parse_utc_timestamp  # noqa: PLC0415

    running = {"created_at": "2026-05-28T11:00:00+00:00"}
    finished = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    payload = terminal_result_payload(
        running_result=running,
        canonical_plan_id="plan:sha256:abc",
        commit_id="commit:abc",
        result_id="result:abc",
        planned_effect={"result_ttl_seconds": 900, "complete_heartbeat": {"phase": "done", "message": "Ready"}},
        live_payload={"object_type": "ok"},
        failed=False,
        finished=finished,
    )

    assert payload["status"] == "ready"
    assert payload["created_at"] == running["created_at"]
    assert payload["completed_at"] == "2026-05-28T12:00:00Z"
    assert payload["payload"] == {"object_type": "ok"}
    assert payload["heartbeat"] == {"phase": "done", "message": "Ready"}
    assert parse_utc_timestamp(payload["expires_at"]) - parse_utc_timestamp(payload["completed_at"]) == timedelta(
        seconds=900
    )


def test_planning_execution_terminal_result_failure_redacts_failure_payload() -> None:
    ensure_libs_path()
    from xctx.domain.planning_execution import terminal_result_payload  # noqa: PLC0415

    payload = terminal_result_payload(
        running_result={"created_at": "2026-05-28T11:00:00+00:00"},
        canonical_plan_id="plan:sha256:abc",
        commit_id="commit:abc",
        result_id="result:abc",
        planned_effect={"result_ttl_seconds": 300},
        live_payload={"object_type": "adapter_error", "api_key": "secret-token"},
        failed=True,
        finished=datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
    )

    assert payload["status"] == "failed"
    assert payload["payload"] is None
    assert payload["failure_payload"]["api_key"] == "<redacted>"
    assert payload["heartbeat"] == {"phase": "failed", "message": "Scoped adapter returned a failure payload."}


def test_planning_execution_final_response_counts_mutation_only_on_success() -> None:
    ensure_libs_path()
    from xctx.domain.planning_execution import final_execute_response  # noqa: PLC0415

    resolved = type("Resolved", (), {"matches": ["abc"]})()
    success = final_execute_response(
        requested_plan="plan:sha256:abc",
        plan={"operation": "demo"},
        resolved=resolved,
        canonical_plan_id="plan:sha256:abc",
        receipt="abc",
        commit_id="commit:abc",
        result_id="result:abc",
        context_matches=True,
        planned_context_sha="a" * 64,
        current_context_sha="a" * 64,
        planned_effect={"writes_to_db": True},
        failed=False,
    )
    failure = final_execute_response(
        requested_plan="plan:sha256:abc",
        plan={"operation": "demo"},
        resolved=resolved,
        canonical_plan_id="plan:sha256:abc",
        receipt="abc",
        commit_id="commit:abc",
        result_id="result:abc",
        context_matches=True,
        planned_context_sha="a" * 64,
        current_context_sha="a" * 64,
        planned_effect={"writes_to_db": True},
        failed=True,
    )

    assert success["ok"] is True
    assert success["status"] == "committed"
    assert success["mutations_applied"] == 1
    assert success["observe_result_cmd"] == "./xctx observe result:abc"
    assert len(success["execution_receipt_sha256"]) == 64
    assert failure["ok"] is False
    assert failure["status"] == "failed"
    assert failure["error"] == "planned_effect_commit_failed"
    assert failure["mutations_applied"] == 0


def test_planning_execution_refusal_payload_has_stable_shape() -> None:
    ensure_libs_path()
    from xctx.domain.planning_execution import execute_refusal_payload  # noqa: PLC0415

    payload = execute_refusal_payload(
        error="plan_required",
        requested_plan=None,
        commit_requested=False,
        description="Execute requires a canonical plan id.",
        next_move="./xctx plan <operation> <target>",
    )

    assert payload == {
        "ok": False,
        "error": "plan_required",
        "requested_plan": None,
        "commit_requested": False,
        "status": "refused",
        "description": "Execute requires a canonical plan id.",
        "next_move": "./xctx plan <operation> <target>",
    }


def test_planning_execution_read_only_response_accepts_current_plan() -> None:
    ensure_libs_path()
    from xctx.domain.planning_execution import read_only_execute_response  # noqa: PLC0415

    resolved = type("Resolved", (), {"matches": ["abc"], "error": None, "plan": {"plan_id": "plan:sha256:abc"}})()
    payload = read_only_execute_response(
        requested_plan="plan:sha256:abc",
        resolved=resolved,
        accepted=True,
        canonical_plan_id="plan:sha256:abc",
        bound_receipt="abc",
        bound_operation="discover root",
        context_matches=True,
        planned_context_sha="1" * 64,
        current_context_sha="1" * 64,
    )

    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["status"] == "accepted_read_only_noop"
    assert payload["mutations_applied"] == 0
    assert payload["next_move"] == "./xctx audit root"
    assert payload["planner_binding"]["context_fingerprint_verified"] is True
    assert len(payload["execution_receipt_sha256"]) == 64


def test_planning_execution_read_only_response_refuses_stale_plan() -> None:
    ensure_libs_path()
    from xctx.domain.planning_execution import read_only_execute_response  # noqa: PLC0415

    resolved = type(
        "Resolved",
        (),
        {"matches": [], "error": "stale_plan_context", "plan": {"plan_id": "plan:sha256:abc"}},
    )()
    payload = read_only_execute_response(
        requested_plan="plan:sha256:abc",
        resolved=resolved,
        accepted=False,
        canonical_plan_id="plan:sha256:abc",
        bound_receipt="abc",
        bound_operation="discover root",
        context_matches=False,
        planned_context_sha="1" * 64,
        current_context_sha="2" * 64,
    )

    assert payload["ok"] is False
    assert payload["error"] == "stale_plan_context"
    assert payload["status"] == "refused"
    assert payload["next_move"] == "./xctx plan <operation> <target>"
    assert payload["planner_binding"]["context_fingerprint_verified"] is False


def test_execute_payload_validation_uses_refusal_helper_contract(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)

    missing = execute_payload([], False, store)
    too_many = execute_payload(["plan:sha256:" + "a" * 64, "plan:sha256:" + "b" * 64], True, store)
    raw = execute_payload(["a" * 64], True, store)

    assert missing["error"] == "plan_required"
    assert missing["requested_plan"] is None
    assert too_many["error"] == "invalid_execute_command"
    assert too_many["requested_plan"] == f"plan:sha256:{'a' * 64} plan:sha256:{'b' * 64}"
    assert raw["error"] == "plan_id_required"
    assert raw["next_move"] == "./xctx execute plan:sha256:<sha256> --commit"


def test_execute_commit_exists_result_missing_does_not_reinvoke_adapter(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415
    from xctx.store.runtime_artifacts import write_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)
    receipt = plan["receipt_sha256"]
    write_runtime_artifact(
        store,
        "commit",
        receipt,
        {
            "commit_id": plan["expected_commit_id"],
            "plan_id": plan["plan_id"],
            "result_id": plan["expected_result_id"],
            "status": "running",
        },
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("adapter should not be invoked when a commit artifact already exists")

    monkeypatch.setattr("xctx.domain.planning.call_external_command", fail_if_called)

    result = execute_payload([plan["plan_id"]], True, store)

    assert result["ok"] is False
    assert result["error"] == "planned_effect_execution_requires_repair"
    assert result["existing_commit_status"] == "running"


def test_execute_result_exists_commit_missing_does_not_reinvoke_adapter(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415
    from xctx.store.runtime_artifacts import isoformat_utc, utc_now, write_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)
    receipt = plan["receipt_sha256"]
    write_runtime_artifact(
        store,
        "result",
        receipt,
        {
            "result_id": plan["expected_result_id"],
            "commit_id": plan["expected_commit_id"],
            "plan_id": plan["plan_id"],
            "status": "running",
            "created_at": isoformat_utc(utc_now()),
            "heartbeat_at": isoformat_utc(utc_now()),
            "payload": None,
        },
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("adapter should not be invoked when a result artifact already exists")

    monkeypatch.setattr("xctx.domain.planning.call_external_command", fail_if_called)

    result = execute_payload([plan["plan_id"]], True, store)

    assert result["ok"] is False
    assert result["error"] == "planned_effect_execution_requires_repair"
    assert result["existing_result_status"] == "running"


def test_execute_existing_claim_does_not_reinvoke_adapter(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415
    from xctx.store.runtime_artifacts import create_commit_execution_claim, isoformat_utc, utc_now  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)
    receipt = plan["receipt_sha256"]
    now = isoformat_utc(utc_now())
    assert create_commit_execution_claim(
        store,
        receipt,
        {
            "object_type": "commit_execution_claim",
            "plan_id": plan["plan_id"],
            "commit_id": plan["expected_commit_id"],
            "result_id": plan["expected_result_id"],
            "receipt_sha256": receipt,
            "owner_id": "test-owner",
            "claim_nonce": "test-nonce",
            "status": "running",
            "claimed_at": now,
            "started_at": now,
            "heartbeat_at": now,
            "completed_at": None,
            "recovery_policy": "never_reinvoke_adapter_without_operator_repair",
        },
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("adapter should not be invoked when an execution claim already exists")

    monkeypatch.setattr("xctx.domain.planning.call_external_command", fail_if_called)

    result = execute_payload([plan["plan_id"]], True, store)

    assert result["ok"] is False
    assert result["error"] == "planned_effect_execution_in_progress"
    assert result["execution_claim_status"] == "running"


def test_stale_running_claim_is_abandoned_without_reinvoking_adapter(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415
    from xctx.store.runtime_artifacts import (  # noqa: PLC0415
        create_commit_execution_claim,
        isoformat_utc,
        read_commit_execution_claim,
        utc_now,
    )

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)
    receipt = plan["receipt_sha256"]
    stale = isoformat_utc(utc_now() - timedelta(hours=2))
    assert create_commit_execution_claim(
        store,
        receipt,
        {
            "object_type": "commit_execution_claim",
            "plan_id": plan["plan_id"],
            "commit_id": plan["expected_commit_id"],
            "result_id": plan["expected_result_id"],
            "receipt_sha256": receipt,
            "owner_id": "stale-test-owner",
            "claim_nonce": "stale-test-nonce",
            "status": "running",
            "claimed_at": stale,
            "started_at": stale,
            "heartbeat_at": stale,
            "completed_at": None,
            "recovery_policy": "never_reinvoke_adapter_without_operator_repair",
        },
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("adapter should not be invoked for a stale running claim")

    monkeypatch.setattr("xctx.domain.planning.call_external_command", fail_if_called)

    result = execute_payload([plan["plan_id"]], True, store)
    persisted = read_commit_execution_claim(store, receipt)

    assert result["ok"] is False
    assert result["error"] == "planned_effect_execution_requires_repair"
    assert result["execution_claim_status"] == "abandoned"
    assert persisted is not None
    assert persisted["status"] == "abandoned"
    assert persisted["recovery_policy"] == "operator_repair_required_before_reinvoke"


def test_adapter_exception_secret_is_not_persisted_in_result_artifact(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.store.runtime_artifacts import read_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)

    def fail_with_secret(*_args, **_kwargs):
        raise XctxError("adapter failed with api_key=SECRET_VALUE")

    monkeypatch.setattr("xctx.domain.planning.call_external_command", fail_with_secret)

    result = execute_payload([plan["plan_id"]], True, store)
    persisted = read_runtime_artifact(store, "result", plan["receipt_sha256"])

    assert result["ok"] is False
    assert persisted is not None
    assert "SECRET_VALUE" not in str(persisted)
    assert persisted["heartbeat"]["message"] == "adapter failed with api_key=<redacted>"


def test_terminal_result_ttl_starts_at_completed_at(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload  # noqa: PLC0415
    from xctx.store.runtime_artifacts import parse_utc_timestamp, read_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = _direct_planned_effect(store)

    def succeed(*_args, **_kwargs):
        return {"object_type": "test_adapter_success"}

    monkeypatch.setattr("xctx.domain.planning.call_external_command", succeed)

    result = execute_payload([plan["plan_id"]], True, store)
    persisted = read_runtime_artifact(store, "result", plan["receipt_sha256"])

    assert result["ok"] is True
    assert persisted is not None
    completed_at = parse_utc_timestamp(persisted["completed_at"])
    expires_at = parse_utc_timestamp(persisted["expires_at"])
    assert completed_at is not None
    assert expires_at is not None
    assert expires_at - completed_at >= timedelta(seconds=299)


def test_replanning_read_only_command_does_not_reset_committed_plan(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload, plan_payload  # noqa: PLC0415
    from xctx.store.plans import read_plan  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    first = plan_payload(["bring_online", "macro_intelligence_hub"], store)
    executed = execute_payload([first["plan_id"]], True, store)
    second = plan_payload(["bring_online", "macro_intelligence_hub"], store)
    first_persisted = read_plan(store, first["receipt_sha256"])

    assert executed["ok"] is True
    assert first_persisted is not None
    assert first_persisted["execution_status"] == "committed"
    assert second["plan_id"] != first["plan_id"]
    assert second["canonical_intent_hash"] == first["canonical_intent_hash"]


def test_runtime_artifacts_are_exact_bearer_handles_not_indexes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    plan = _plan_create_game()
    discovered = _results(["discover", plan["master_plan_id"]])

    assert discovered["artifact_kind"] == "master_plan"
    assert discovered["master_plan_id"] == plan["master_plan_id"]

    for target in ("plan_manifest", "master_plan", "sub_plan", "commit"):
        rc, payload = run_runtime_json(["discover", target])
        assert rc == 1
        assert payload["record_type"] == "error"
        assert payload["ok"] is False
        assert payload["error"] == f"unknown discovery target: {target}"
        assert "results" in payload and payload["results"] == {}

    for malformed in ("master_plan:", "master_plan:not-a-sha", "plan_manifest:", "plan_manifest:not-a-sha"):
        rc, payload = run_runtime_json(["discover", malformed])
        assert rc == 1
        assert payload["record_type"] == "error"
        assert payload["ok"] is False
        assert payload["error"] == "invalid runtime artifact reference"

    unknown_master = "master_plan:" + ("b" * 64)
    rc, payload = run_runtime_json(["discover", unknown_master])
    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["ok"] is False
    assert payload["error"] == f"unknown runtime artifact: {unknown_master}"
    assert payload["next_moves"] == [{"run_cmd": "./xctx discover"}, {"run_cmd": "./xctx plan <operation> <target>"}]


def test_result_handle_can_expire_without_domain_scope(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.store.runtime_artifacts import isoformat_utc, utc_now, write_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    digest = "a" * 64
    write_runtime_artifact(
        store,
        "result",
        digest,
        {
            "result_id": f"result:{digest}",
            "commit_id": f"commit:{digest}",
            "plan_id": f"plan:sha256:{digest}",
            "status": "ready",
            "created_at": isoformat_utc(utc_now() - timedelta(minutes=10)),
            "expires_at": isoformat_utc(utc_now() - timedelta(minutes=1)),
            "heartbeat_at": isoformat_utc(utc_now() - timedelta(minutes=10)),
            "heartbeat": {"phase": "complete", "message": "Result was ready."},
            "payload": {"value": "gone"},
        },
    )

    observed = _observe(f"result:{digest}")

    assert observed["status"] == "expired"
    assert observed["payload"] is None
    assert observed["heartbeat"]["phase"] == "expired"


def test_core_hook_points_do_not_contain_game_domain_vocabulary() -> None:
    generic_files = [
        "libs/xctx/domain/planning.py",
        "libs/xctx/domain/observation.py",
        "libs/xctx/store/runtime_artifacts.py",
    ]
    forbidden = ("guess_the_number_game", "choose_random_number", "guess_number", "secret_number")
    for rel in generic_files:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), rel
