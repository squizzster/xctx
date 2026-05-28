"""Planned-effect execute transactions for recorded xctx plans."""

from __future__ import annotations

from typing import Any

from xctx.domain.planning_planned_effect_adapter import invoke_commit_adapter
from xctx.domain.planning_planned_effect_preflight import planned_effect_execution_preflight
from xctx.domain.planning_planned_effect_start import (
    mark_execution_started,
    publish_running_execution_artifacts,
)
from xctx.domain.planning_planned_effect_terminal import (
    adapter_exception_failure_response,
    finalize_adapter_execution,
)


def execute_planned_effect_payload(
    *,
    requested_plan: str,
    resolved: Any,
    store: dict[str, Any],
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
) -> dict[str, Any]:
    preflight = planned_effect_execution_preflight(
        requested_plan=requested_plan,
        resolved=resolved,
        store=store,
        context_matches=context_matches,
        planned_context_sha=planned_context_sha,
        current_context_sha=current_context_sha,
    )
    if preflight.refusal_payload is not None:
        return preflight.refusal_payload
    assert preflight.master_plan is not None
    assert preflight.sub_plan is not None
    assert preflight.claim is not None

    commit, running_result = publish_running_execution_artifacts(
        store=store,
        receipt=preflight.receipt,
        canonical_plan_id=preflight.canonical_plan_id,
        commit_id=preflight.commit_id,
        result_id=preflight.result_id,
        planned_effect=preflight.planned_effect,
        master_plan=preflight.master_plan,
        sub_plan=preflight.sub_plan,
    )

    try:
        commit, claim = mark_execution_started(
            store=store,
            receipt=preflight.receipt,
            commit=commit,
            claim=preflight.claim,
        )
        live = invoke_commit_adapter(
            store=store,
            planned_effect=preflight.planned_effect,
            canonical_plan_id=preflight.canonical_plan_id,
            commit_id=preflight.commit_id,
            result_id=preflight.result_id,
        )
    except Exception as exc:  # keep the committed result handle observable
        return adapter_exception_failure_response(
            requested_plan=requested_plan,
            resolved=resolved,
            store=store,
            plan=preflight.plan,
            receipt=preflight.receipt,
            canonical_plan_id=preflight.canonical_plan_id,
            commit_id=preflight.commit_id,
            result_id=preflight.result_id,
            planned_effect=preflight.planned_effect,
            commit=commit,
            claim=claim,
            master_plan=preflight.master_plan,
            sub_plan=preflight.sub_plan,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
            exc=exc,
        )

    return finalize_adapter_execution(
        requested_plan=requested_plan,
        resolved=resolved,
        store=store,
        plan=preflight.plan,
        receipt=preflight.receipt,
        canonical_plan_id=preflight.canonical_plan_id,
        commit_id=preflight.commit_id,
        result_id=preflight.result_id,
        planned_effect=preflight.planned_effect,
        commit=commit,
        running_result=running_result,
        claim=claim,
        master_plan=preflight.master_plan,
        sub_plan=preflight.sub_plan,
        live_payload=live,
        context_matches=context_matches,
        planned_context_sha=planned_context_sha,
        current_context_sha=current_context_sha,
    )
