"""Preflight and claim acquisition for planned-effect execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xctx.domain.planning_commit_state import (
    TERMINAL_CLAIM_STATUSES,
    claim_status,
    mark_claim_abandoned_if_stale,
    new_execution_claim,
)
from xctx.domain.planning_ledger import plan_is_committed
from xctx.domain.planning_materialization import verify_plan_materialization
from xctx.domain.planning_payloads import execution_claim_refusal_payload, plan_already_committed_payload
from xctx.store.runtime_artifacts import (
    create_commit_execution_claim,
    read_commit_execution_claim,
    read_runtime_artifact,
    runtime_artifact_ref,
)


@dataclass(frozen=True)
class PlannedEffectExecutionPreflight:
    plan: dict[str, Any]
    receipt: str
    planned_effect: dict[str, Any]
    canonical_plan_id: str
    commit_id: str
    result_id: str
    master_plan: dict[str, Any] | None
    sub_plan: dict[str, Any] | None
    claim: dict[str, Any] | None
    refusal_payload: dict[str, Any] | None = None


def _refusal(
    *,
    requested_plan: str,
    resolved: Any,
    plan: dict[str, Any],
    receipt: str,
    commit_id: str,
    result_id: str,
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
    reason: str,
    existing_commit: dict[str, Any] | None = None,
    existing_result: dict[str, Any] | None = None,
    claim: dict[str, Any] | None = None,
    materialization_errors: list[str] | None = None,
) -> PlannedEffectExecutionPreflight:
    planned_effect = plan.get("planned_effect") if isinstance(plan.get("planned_effect"), dict) else {}
    return PlannedEffectExecutionPreflight(
        plan=plan,
        receipt=receipt,
        planned_effect=planned_effect,
        canonical_plan_id=str(plan.get("plan_id")),
        commit_id=commit_id,
        result_id=result_id,
        master_plan=None,
        sub_plan=None,
        claim=claim,
        refusal_payload=execution_claim_refusal_payload(
            requested_plan=requested_plan,
            resolved=resolved,
            plan=plan,
            receipt=receipt,
            commit_id=commit_id,
            result_id=result_id,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
            reason=reason,
            existing_commit=existing_commit,
            existing_result=existing_result,
            claim=claim,
            materialization_errors=materialization_errors,
        ),
    )


def planned_effect_execution_preflight(
    *,
    requested_plan: str,
    resolved: Any,
    store: dict[str, Any],
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
) -> PlannedEffectExecutionPreflight:
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
        return _refusal(
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
        return PlannedEffectExecutionPreflight(
            plan=plan,
            receipt=receipt,
            planned_effect=planned_effect,
            canonical_plan_id=canonical_plan_id,
            commit_id=commit_id,
            result_id=result_id,
            master_plan=master_plan,
            sub_plan=sub_plan,
            claim=existing_claim,
            refusal_payload=plan_already_committed_payload(
                requested_plan=requested_plan,
                plan={**plan, "commit_id": commit_id, "result_id": result_id},
                resolved=resolved,
                context_matches=context_matches,
                planned_context_sha=planned_context_sha,
                current_context_sha=current_context_sha,
            ),
        )
    if existing_claim:
        return _refusal(
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
        return _refusal(
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
        return _refusal(
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

    return PlannedEffectExecutionPreflight(
        plan=plan,
        receipt=receipt,
        planned_effect=planned_effect,
        canonical_plan_id=canonical_plan_id,
        commit_id=commit_id,
        result_id=result_id,
        master_plan=master_plan,
        sub_plan=sub_plan,
        claim=claim,
    )
