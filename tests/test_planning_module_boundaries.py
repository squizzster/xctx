"""Unit contracts for the planning public wrapper and execute module split."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from framework_helpers import ROOT, ensure_libs_path


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(90)]


def _load_store(tmp_path, monkeypatch) -> dict:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    return load_store(root=ROOT)


def _direct_planned_effect(store: dict) -> dict:
    ensure_libs_path()
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


def _terminal_planned_effect_state(store: dict) -> SimpleNamespace:
    ensure_libs_path()
    from xctx.domain.planning_commit_state import new_execution_claim  # noqa: PLC0415
    from xctx.domain.planning_execution import running_execution_artifacts  # noqa: PLC0415
    from xctx.store.runtime_artifacts import read_runtime_artifact, utc_now  # noqa: PLC0415

    plan = _direct_planned_effect(store)
    receipt = plan["receipt_sha256"]
    planned_effect = plan["planned_effect"]
    commit_id = plan["expected_commit_id"]
    result_id = plan["expected_result_id"]
    commit, running_result = running_execution_artifacts(
        canonical_plan_id=plan["plan_id"],
        commit_id=commit_id,
        result_id=result_id,
        planned_effect=planned_effect,
        now=utc_now(),
    )
    claim = new_execution_claim(
        plan=plan,
        receipt=receipt,
        commit_id=commit_id,
        result_id=result_id,
        current_context_sha="current-sha",
    )
    master_plan = read_runtime_artifact(store, "master_plan", receipt)
    sub_plan = read_runtime_artifact(store, "sub_plan", receipt)
    assert master_plan is not None
    assert sub_plan is not None
    return SimpleNamespace(
        plan=plan,
        receipt=receipt,
        planned_effect=planned_effect,
        commit_id=commit_id,
        result_id=result_id,
        commit=commit,
        running_result=running_result,
        claim=claim,
        master_plan=master_plan,
        sub_plan=sub_plan,
        resolved=SimpleNamespace(matches=[receipt]),
    )


def test_planning_execute_payload_delegates_to_execute_module(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning  # noqa: PLC0415

    calls: list[tuple[list[str], bool, dict]] = []
    sentinel = {"ok": True, "source": "execute_module"}

    def fake_execute(args, commit, store):
        calls.append((args, commit, store))
        return sentinel

    store = {"store": "sentinel"}
    monkeypatch.setattr(planning, "_execute_payload", fake_execute)

    result = planning.execute_payload(["plan:sha256:" + ("a" * 64)], True, store)

    assert result is sentinel
    assert calls == [(["plan:sha256:" + ("a" * 64)], True, store)]


def test_planning_plan_payload_routes_planned_effect_to_planned_effect_module(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning  # noqa: PLC0415

    planned = {"domain": "domain", "action": "action"}
    sentinel = {"ok": True, "source": "planned_effect"}

    monkeypatch.setattr(
        planning,
        "parse_plan_request",
        lambda args: SimpleNamespace(operation="mutate", raw_args=["mutate", "target"]),
    )
    monkeypatch.setattr(planning, "_resolve_planned_action", lambda store, operation, args: planned)
    monkeypatch.setattr(planning, "_planned_effect_plan_payload", lambda args, store, resolved: sentinel)

    assert planning.plan_payload(["mutate", "target"], {"store": "sentinel"}) is sentinel


def test_planning_plan_payload_routes_unplanned_command_to_read_only_module(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning  # noqa: PLC0415

    sentinel = {"ok": True, "source": "read_only"}

    monkeypatch.setattr(
        planning,
        "parse_plan_request",
        lambda args: SimpleNamespace(operation="discover", raw_args=["discover", "root"]),
    )
    monkeypatch.setattr(planning, "_resolve_planned_action", lambda store, operation, args: None)
    monkeypatch.setattr(planning, "_read_only_plan_payload", lambda args, store: sentinel)

    assert planning.plan_payload(["discover", "root"], {"store": "sentinel"}) is sentinel


def test_execute_module_requires_plan_identifier_without_store_lookup(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415

    monkeypatch.setattr(
        planning_execute,
        "resolve_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("store lookup should not run")),
    )

    result = planning_execute.execute_payload([], True, {})

    assert result["ok"] is False
    assert result["error"] == "plan_required"


def test_execute_module_rejects_multiple_plan_identifiers_without_store_lookup(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415

    monkeypatch.setattr(
        planning_execute,
        "resolve_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("store lookup should not run")),
    )

    result = planning_execute.execute_payload(["plan:sha256:" + ("a" * 64), "extra"], True, {})

    assert result["ok"] is False
    assert result["error"] == "invalid_execute_command"


def test_execute_module_rejects_raw_receipt_without_store_lookup(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415

    monkeypatch.setattr(
        planning_execute,
        "resolve_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("store lookup should not run")),
    )

    result = planning_execute.execute_payload(["a" * 64], True, {})

    assert result["ok"] is False
    assert result["error"] == "plan_id_required"


def test_execute_module_requires_commit_without_store_lookup(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415

    monkeypatch.setattr(
        planning_execute,
        "resolve_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("store lookup should not run")),
    )

    result = planning_execute.execute_payload(["plan:sha256:" + ("a" * 64)], False, {})

    assert result["ok"] is False
    assert result["error"] == "commit_required"


def test_execute_module_dispatches_planned_effect_to_transaction_module(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415
    from xctx.store.plans import ResolvedPlan  # noqa: PLC0415

    receipt = "b" * 64
    requested_plan = f"plan:sha256:{receipt}"
    plan = {
        "plan_id": requested_plan,
        "receipt_sha256": receipt,
        "operation": "mutate",
        "planned_effect": {"kind": "test"},
    }
    resolved = ResolvedPlan(True, None, requested_plan, plan, [receipt])
    calls: list[dict] = []
    sentinel = {"ok": True, "source": "planned_effect_transaction"}

    def fake_execute_planned_effect_payload(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(planning_execute, "resolve_plan", lambda store, value: resolved)
    monkeypatch.setattr(planning_execute, "context_match", lambda store, plan_record: (True, "planned-sha", "current-sha"))
    monkeypatch.setattr(planning_execute, "plan_is_committed", lambda plan_record: False)
    monkeypatch.setattr(planning_execute, "execute_planned_effect_payload", fake_execute_planned_effect_payload)

    result = planning_execute.execute_payload([requested_plan], True, {"store": "sentinel"})

    assert result is sentinel
    assert calls == [
        {
            "requested_plan": requested_plan,
            "resolved": resolved,
            "store": {"store": "sentinel"},
            "context_matches": True,
            "planned_context_sha": "planned-sha",
            "current_context_sha": "current-sha",
        }
    ]


def test_execute_module_refuses_committed_plan_before_transaction_module(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415
    from xctx.store.plans import ResolvedPlan  # noqa: PLC0415

    receipt = "c" * 64
    requested_plan = f"plan:sha256:{receipt}"
    plan = {
        "plan_id": requested_plan,
        "receipt_sha256": receipt,
        "operation": "mutate",
        "planned_effect": {"kind": "test"},
        "execution_status": "committed",
    }
    resolved = ResolvedPlan(True, None, requested_plan, plan, [receipt])

    monkeypatch.setattr(planning_execute, "resolve_plan", lambda store, value: resolved)
    monkeypatch.setattr(planning_execute, "context_match", lambda store, plan_record: (True, "planned-sha", "current-sha"))
    monkeypatch.setattr(planning_execute, "plan_is_committed", lambda plan_record: True)
    monkeypatch.setattr(
        planning_execute,
        "execute_planned_effect_payload",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("transaction module should not run")),
    )

    result = planning_execute.execute_payload([requested_plan], True, {})

    assert result["ok"] is False
    assert result["error"] == "plan_already_committed"


def test_execute_module_refuses_stale_context_before_transaction_module(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415
    from xctx.store.plans import ResolvedPlan  # noqa: PLC0415

    receipt = "d" * 64
    requested_plan = f"plan:sha256:{receipt}"
    plan = {
        "plan_id": requested_plan,
        "receipt_sha256": receipt,
        "operation": "mutate",
        "planned_effect": {"kind": "test"},
    }
    resolved = ResolvedPlan(True, None, requested_plan, plan, [receipt])

    monkeypatch.setattr(planning_execute, "resolve_plan", lambda store, value: resolved)
    monkeypatch.setattr(planning_execute, "context_match", lambda store, plan_record: (False, "planned-sha", "current-sha"))
    monkeypatch.setattr(
        planning_execute,
        "execute_planned_effect_payload",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("transaction module should not run")),
    )

    result = planning_execute.execute_payload([requested_plan], True, {})

    assert result["ok"] is False
    assert result["error"] == "stale_plan_context"
    assert result["planner_binding"]["context_fingerprint_verified"] is False


def test_execute_module_has_no_adapter_invocation_port() -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415

    assert not hasattr(planning_execute, "call_external_command")
    assert not hasattr(planning_execute, "resolve_subdomain")


def test_execute_module_dispatches_read_only_plan_to_read_only_execution_module(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415
    from xctx.store.plans import ResolvedPlan  # noqa: PLC0415

    receipt = "e" * 64
    requested_plan = f"plan:sha256:{receipt}"
    plan = {
        "plan_id": requested_plan,
        "receipt_sha256": receipt,
        "operation": "discover",
    }
    resolved = ResolvedPlan(True, None, requested_plan, plan, [receipt])
    calls: list[dict] = []
    sentinel = {"ok": True, "source": "read_only_execution"}

    def fake_execute_read_only_plan(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(planning_execute, "resolve_plan", lambda store, value: resolved)
    monkeypatch.setattr(planning_execute, "context_match", lambda store, plan_record: (True, "planned-sha", "current-sha"))
    monkeypatch.setattr(planning_execute, "plan_is_committed", lambda plan_record: False)
    monkeypatch.setattr(planning_execute, "execute_read_only_plan", fake_execute_read_only_plan)

    result = planning_execute.execute_payload([requested_plan], True, {"store": "sentinel"})

    assert result is sentinel
    assert calls == [
        {
            "requested_plan": requested_plan,
            "resolved": resolved,
            "accepted": True,
            "store": {"store": "sentinel"},
            "canonical_plan_id": requested_plan,
            "bound_receipt": receipt,
            "bound_operation": "discover",
            "context_matches": True,
            "planned_context_sha": "planned-sha",
            "current_context_sha": "current-sha",
        }
    ]


def test_read_only_execution_module_does_not_commit_refused_plan(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_read_only_execution  # noqa: PLC0415
    from xctx.store.plans import ResolvedPlan  # noqa: PLC0415

    receipt = "f" * 64
    requested_plan = f"plan:sha256:{receipt}"
    resolved = ResolvedPlan(False, "stale_plan_context", requested_plan, {"plan_id": requested_plan}, [receipt])
    monkeypatch.setattr(
        planning_read_only_execution,
        "mark_plan_committed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("refused plan should not be committed")),
    )

    result = planning_read_only_execution.execute_read_only_plan(
        requested_plan=requested_plan,
        resolved=resolved,
        accepted=False,
        store={},
        canonical_plan_id=requested_plan,
        bound_receipt=receipt,
        bound_operation="discover",
        context_matches=False,
        planned_context_sha="planned-sha",
        current_context_sha="current-sha",
    )

    assert result["ok"] is False
    assert result["error"] == "stale_plan_context"


def test_read_only_execution_module_marks_accepted_plan_committed(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain.planning import plan_payload  # noqa: PLC0415
    from xctx.domain.planning_read_only_execution import execute_read_only_plan  # noqa: PLC0415
    from xctx.store.plans import read_plan, resolve_plan  # noqa: PLC0415

    store = _load_store(tmp_path, monkeypatch)
    plan = plan_payload(["bring_online", "macro_intelligence_hub"], store)
    resolved = resolve_plan(store, plan["plan_id"])

    result = execute_read_only_plan(
        requested_plan=plan["plan_id"],
        resolved=resolved,
        accepted=True,
        store=store,
        canonical_plan_id=plan["plan_id"],
        bound_receipt=plan["receipt_sha256"],
        bound_operation=plan["operation"],
        context_matches=True,
        planned_context_sha=None,
        current_context_sha=None,
    )
    persisted = read_plan(store, plan["receipt_sha256"])

    assert result["ok"] is True
    assert persisted is not None
    assert persisted["execution_status"] == "committed"


def test_execute_module_marks_read_only_plan_committed(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain.planning import plan_payload  # noqa: PLC0415
    from xctx.domain.planning_execute import execute_payload  # noqa: PLC0415
    from xctx.store.plans import read_plan  # noqa: PLC0415

    store = _load_store(tmp_path, monkeypatch)
    plan = plan_payload(["bring_online", "macro_intelligence_hub"], store)

    result = execute_payload([plan["plan_id"]], True, store)
    persisted = read_plan(store, plan["receipt_sha256"])

    assert result["ok"] is True
    assert persisted is not None
    assert persisted["execution_status"] == "committed"


def test_planned_effect_execution_module_uses_moved_adapter_call_boundary(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning, planning_execute, planning_planned_effect_execution  # noqa: PLC0415

    store = _load_store(tmp_path, monkeypatch)
    plan = _direct_planned_effect(store)
    calls: list[list[str]] = []

    def fake_call(_store, _subdomain, args):
        calls.append(list(args))
        return {"object_type": "test_adapter_success"}

    monkeypatch.setattr(planning_planned_effect_execution, "call_external_command", fake_call)

    result = planning_execute.execute_payload([plan["plan_id"]], True, store)

    assert result["ok"] is True
    assert calls
    assert calls[0][0] == plan["planned_effect"]["commit_adapter_command"]
    assert calls[0][-6:] == [
        "--xctx-plan-id",
        plan["plan_id"],
        "--xctx-commit-id",
        plan["expected_commit_id"],
        "--xctx-result-id",
        plan["expected_result_id"],
    ]
    assert not hasattr(planning, "call_external_command")
    assert not hasattr(planning_execute, "call_external_command")


def test_planned_effect_terminal_success_persists_committed_artifacts(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain.planning_planned_effect_terminal import finalize_adapter_execution  # noqa: PLC0415
    from xctx.store.plans import read_plan  # noqa: PLC0415
    from xctx.store.runtime_artifacts import read_commit_execution_claim, read_runtime_artifact  # noqa: PLC0415

    store = _load_store(tmp_path, monkeypatch)
    state = _terminal_planned_effect_state(store)

    result = finalize_adapter_execution(
        requested_plan=state.plan["plan_id"],
        resolved=state.resolved,
        store=store,
        plan=state.plan,
        receipt=state.receipt,
        canonical_plan_id=state.plan["plan_id"],
        commit_id=state.commit_id,
        result_id=state.result_id,
        planned_effect=state.planned_effect,
        commit=state.commit,
        running_result=state.running_result,
        claim=state.claim,
        master_plan=state.master_plan,
        sub_plan=state.sub_plan,
        live_payload={"object_type": "test_adapter_success", "value": 7},
        context_matches=True,
        planned_context_sha="planned-sha",
        current_context_sha="current-sha",
    )

    commit = read_runtime_artifact(store, "commit", state.receipt)
    persisted_result = read_runtime_artifact(store, "result", state.receipt)
    claim = read_commit_execution_claim(store, state.receipt)
    persisted_plan = read_plan(store, state.receipt)
    master_plan = read_runtime_artifact(store, "master_plan", state.receipt)
    sub_plan = read_runtime_artifact(store, "sub_plan", state.receipt)

    assert result["ok"] is True
    assert result["status"] == "committed"
    assert commit is not None and commit["status"] == "committed"
    assert persisted_result is not None and persisted_result["status"] == "ready"
    assert persisted_result["payload"]["value"] == 7
    assert claim is not None and claim["status"] == "succeeded"
    assert persisted_plan is not None and persisted_plan["execution_status"] == "committed"
    assert master_plan is not None and master_plan["execution_status"] == "committed"
    assert sub_plan is not None and sub_plan["execution_status"] == "committed"


def test_planned_effect_terminal_failure_payload_persists_failed_artifacts(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain.planning_planned_effect_terminal import finalize_adapter_execution  # noqa: PLC0415
    from xctx.store.runtime_artifacts import read_commit_execution_claim, read_runtime_artifact  # noqa: PLC0415

    store = _load_store(tmp_path, monkeypatch)
    state = _terminal_planned_effect_state(store)

    result = finalize_adapter_execution(
        requested_plan=state.plan["plan_id"],
        resolved=state.resolved,
        store=store,
        plan=state.plan,
        receipt=state.receipt,
        canonical_plan_id=state.plan["plan_id"],
        commit_id=state.commit_id,
        result_id=state.result_id,
        planned_effect=state.planned_effect,
        commit=state.commit,
        running_result=state.running_result,
        claim=state.claim,
        master_plan=state.master_plan,
        sub_plan=state.sub_plan,
        live_payload={"object_type": "test_adapter_error", "api_key": "SECRET_VALUE"},
        context_matches=True,
        planned_context_sha="planned-sha",
        current_context_sha="current-sha",
    )

    commit = read_runtime_artifact(store, "commit", state.receipt)
    persisted_result = read_runtime_artifact(store, "result", state.receipt)
    claim = read_commit_execution_claim(store, state.receipt)

    assert result["ok"] is False
    assert result["error"] == "planned_effect_commit_failed"
    assert commit is not None and commit["status"] == "failed"
    assert persisted_result is not None
    assert persisted_result["status"] == "failed"
    assert persisted_result["payload"] is None
    assert "SECRET_VALUE" not in str(persisted_result)
    assert persisted_result["failure_payload"]["api_key"] == "<redacted>"
    assert claim is not None and claim["status"] == "failed"


def test_planned_effect_terminal_exception_persists_redacted_failure(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain.planning_planned_effect_terminal import adapter_exception_failure_response  # noqa: PLC0415
    from xctx.store.runtime_artifacts import read_commit_execution_claim, read_runtime_artifact  # noqa: PLC0415

    store = _load_store(tmp_path, monkeypatch)
    state = _terminal_planned_effect_state(store)

    result = adapter_exception_failure_response(
        requested_plan=state.plan["plan_id"],
        resolved=state.resolved,
        store=store,
        plan=state.plan,
        receipt=state.receipt,
        canonical_plan_id=state.plan["plan_id"],
        commit_id=state.commit_id,
        result_id=state.result_id,
        planned_effect=state.planned_effect,
        commit=state.commit,
        claim=state.claim,
        master_plan=state.master_plan,
        sub_plan=state.sub_plan,
        context_matches=True,
        planned_context_sha="planned-sha",
        current_context_sha="current-sha",
        exc=RuntimeError("adapter crashed with api_key=SECRET_VALUE"),
    )

    commit = read_runtime_artifact(store, "commit", state.receipt)
    persisted_result = read_runtime_artifact(store, "result", state.receipt)
    claim = read_commit_execution_claim(store, state.receipt)
    master_plan = read_runtime_artifact(store, "master_plan", state.receipt)

    assert result["ok"] is False
    assert result["error"] == "planned_effect_commit_failed"
    assert commit is not None and commit["status"] == "failed"
    assert commit["error"] == "adapter crashed with api_key=<redacted>"
    assert persisted_result is not None
    assert "SECRET_VALUE" not in str(persisted_result)
    assert persisted_result["heartbeat"]["message"] == "adapter crashed with api_key=<redacted>"
    assert claim is not None and claim["status"] == "failed"
    assert master_plan is not None and master_plan["failed"] is True
