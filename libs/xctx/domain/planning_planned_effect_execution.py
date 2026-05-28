"""Planned-effect execute transactions for recorded xctx plans."""

from __future__ import annotations

from typing import Any

from xctx.domain.core import resolve_subdomain
from xctx.domain.planning_commit_state import (
    TERMINAL_CLAIM_STATUSES,
    claim_status,
    mark_claim_abandoned_if_stale,
    new_execution_claim,
)
from xctx.domain.planning_execution import commit_context_args
from xctx.domain.planning_ledger import plan_is_committed
from xctx.domain.planning_materialization import verify_plan_materialization
from xctx.domain.planning_payloads import execution_claim_refusal_payload, plan_already_committed_payload
from xctx.domain.planning_planned_effect_start import (
    mark_execution_started,
    publish_running_execution_artifacts,
)
from xctx.domain.planning_planned_effect_terminal import (
    adapter_exception_failure_response,
    finalize_adapter_execution,
)
from xctx.ports.external_command import call_external_command
from xctx.store.runtime_artifacts import (
    create_commit_execution_claim,
    read_commit_execution_claim,
    read_runtime_artifact,
    runtime_artifact_ref,
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
    plan = dict(resolved.plan or {})
    receipt = str(plan["receipt_sha256"]).lower()
    planned_effect = plan.get("planned_effect") if isinstance(plan.get("planned_effect"), dict) else {}
    canonical_plan_id = str(plan.get("plan_id"))
    commit_id = str(plan.get("expected_commit_id") or runtime_artifact_ref("commit", receipt))
    result_id = str(plan.get("expected_result_id") or runtime_artifact_ref("result", receipt))
    materialized, master_plan, sub_plan, _manifest, materialization_errors = verify_plan_materialization(
        store,
        plan,
        receipt,
    )
    if not materialized or not master_plan or not sub_plan:
        return execution_claim_refusal_payload(
            requested_plan=requested_plan,
            resolved=resolved,
            plan=plan,
            receipt=receipt,
            commit_id=commit_id,
            result_id=result_id,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
            reason="plan_not_materialized",
            materialization_errors=materialization_errors,
        )

    existing_commit = read_runtime_artifact(store, "commit", receipt)
    existing_result = read_runtime_artifact(store, "result", receipt)
    existing_claim = read_commit_execution_claim(store, receipt)
    if existing_claim:
        existing_claim = mark_claim_abandoned_if_stale(store, receipt, existing_claim)

    if plan_is_committed(plan) or claim_status(existing_claim) in TERMINAL_CLAIM_STATUSES:
        return plan_already_committed_payload(
            requested_plan=requested_plan,
            plan={**plan, "commit_id": commit_id, "result_id": result_id},
            resolved=resolved,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
        )
    if existing_claim:
        return execution_claim_refusal_payload(
            requested_plan=requested_plan,
            resolved=resolved,
            plan=plan,
            receipt=receipt,
            commit_id=commit_id,
            result_id=result_id,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
            reason=(
                "planned_effect_execution_in_progress"
                if claim_status(existing_claim) in {"claimed", "running", "finalizing"}
                else "planned_effect_execution_requires_repair"
            ),
            existing_commit=existing_commit,
            existing_result=existing_result,
            claim=existing_claim,
        )
    if existing_commit or existing_result:
        return execution_claim_refusal_payload(
            requested_plan=requested_plan,
            resolved=resolved,
            plan=plan,
            receipt=receipt,
            commit_id=commit_id,
            result_id=result_id,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
            reason="planned_effect_execution_requires_repair",
            existing_commit=existing_commit,
            existing_result=existing_result,
        )

    claim = new_execution_claim(
        plan=plan,
        receipt=receipt,
        commit_id=commit_id,
        result_id=result_id,
        current_context_sha=current_context_sha,
    )
    if not create_commit_execution_claim(store, receipt, claim):
        existing_claim = read_commit_execution_claim(store, receipt)
        if existing_claim:
            existing_claim = mark_claim_abandoned_if_stale(store, receipt, existing_claim)
        return execution_claim_refusal_payload(
            requested_plan=requested_plan,
            resolved=resolved,
            plan=plan,
            receipt=receipt,
            commit_id=commit_id,
            result_id=result_id,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
            reason="planned_effect_execution_in_progress",
            existing_commit=read_runtime_artifact(store, "commit", receipt),
            existing_result=read_runtime_artifact(store, "result", receipt),
            claim=existing_claim,
        )

    commit, running_result = publish_running_execution_artifacts(
        store=store,
        receipt=receipt,
        canonical_plan_id=canonical_plan_id,
        commit_id=commit_id,
        result_id=result_id,
        planned_effect=planned_effect,
        master_plan=master_plan,
        sub_plan=sub_plan,
    )

    try:
        commit, claim = mark_execution_started(store=store, receipt=receipt, commit=commit, claim=claim)
        subdomain = resolve_subdomain(
            store,
            str(planned_effect["agent_domain"]),
            str(planned_effect["agent_subdomain"]),
        )
        live = call_external_command(
            store,
            subdomain,
            [
                str(planned_effect["commit_adapter_command"]),
                *[str(arg) for arg in planned_effect.get("adapter_args") or []],
                *commit_context_args(
                    canonical_plan_id=canonical_plan_id,
                    commit_id=commit_id,
                    result_id=result_id,
                ),
            ],
        )
    except Exception as exc:  # keep the committed result handle observable
        return adapter_exception_failure_response(
            requested_plan=requested_plan,
            resolved=resolved,
            store=store,
            plan=plan,
            receipt=receipt,
            canonical_plan_id=canonical_plan_id,
            commit_id=commit_id,
            result_id=result_id,
            planned_effect=planned_effect,
            commit=commit,
            claim=claim,
            master_plan=master_plan,
            sub_plan=sub_plan,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
            exc=exc,
        )

    return finalize_adapter_execution(
        requested_plan=requested_plan,
        resolved=resolved,
        store=store,
        plan=plan,
        receipt=receipt,
        canonical_plan_id=canonical_plan_id,
        commit_id=commit_id,
        result_id=result_id,
        planned_effect=planned_effect,
        commit=commit,
        running_result=running_result,
        claim=claim,
        master_plan=master_plan,
        sub_plan=sub_plan,
        live_payload=live,
        context_matches=context_matches,
        planned_context_sha=planned_context_sha,
        current_context_sha=current_context_sha,
    )
