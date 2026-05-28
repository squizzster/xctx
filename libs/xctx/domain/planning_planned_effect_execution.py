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
from xctx.domain.planning_execution import (
    commit_context_args,
    final_execute_response,
    materialized_artifact_committed,
    materialized_artifact_committing,
    running_execution_artifacts,
    terminal_result_payload,
)
from xctx.domain.planning_ledger import mark_plan_committed, plan_is_committed
from xctx.domain.planning_materialization import verify_plan_materialization
from xctx.domain.planning_payloads import (
    adapter_payload_failed,
    execution_claim_refusal_payload,
    failed_result_payload,
    plan_already_committed_payload,
)
from xctx.ports.external_command import call_external_command
from xctx.process.redaction import redact_preview
from xctx.store.runtime_artifacts import (
    create_commit_execution_claim,
    isoformat_utc,
    read_commit_execution_claim,
    read_runtime_artifact,
    runtime_artifact_ref,
    utc_now,
    write_commit_execution_claim,
    write_runtime_artifact,
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

    commit, running_result = running_execution_artifacts(
        canonical_plan_id=canonical_plan_id,
        commit_id=commit_id,
        result_id=result_id,
        planned_effect=planned_effect,
        now=utc_now(),
    )
    write_runtime_artifact(store, "commit", receipt, commit)
    write_runtime_artifact(store, "result", receipt, running_result)
    write_runtime_artifact(
        store,
        "master_plan",
        receipt,
        materialized_artifact_committing(
            master_plan,
            commit_id=commit_id,
            result_id=result_id,
            committed_at=running_result["created_at"],
        ),
    )
    write_runtime_artifact(
        store,
        "sub_plan",
        receipt,
        materialized_artifact_committing(
            sub_plan,
            commit_id=commit_id,
            result_id=result_id,
            committed_at=running_result["created_at"],
        ),
    )

    try:
        started = isoformat_utc(utc_now())
        commit["status"] = "running"
        write_runtime_artifact(store, "commit", receipt, commit)
        claim = {**claim, "status": "running", "started_at": started, "heartbeat_at": started}
        write_commit_execution_claim(store, receipt, claim)
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
        message = redact_preview(str(exc))
        failed = failed_result_payload(plan=plan, planned_effect=planned_effect, receipt=receipt, message=message)
        commit["status"] = "failed"
        commit["error"] = message
        commit["completed_at"] = failed["created_at"]
        write_runtime_artifact(store, "commit", receipt, commit)
        write_runtime_artifact(store, "result", receipt, failed)
        mark_plan_committed(
            store,
            plan,
            committed_at=failed["created_at"],
            commit_id=commit_id,
            result_id=result_id,
        )
        if master_plan:
            write_runtime_artifact(
                store,
                "master_plan",
                receipt,
                materialized_artifact_committed(
                    master_plan,
                    commit_id=commit_id,
                    result_id=result_id,
                    committed_at=failed["created_at"],
                    failed=True,
                ),
            )
        write_runtime_artifact(
            store,
            "sub_plan",
            receipt,
            materialized_artifact_committed(
                sub_plan,
                commit_id=commit_id,
                result_id=result_id,
                committed_at=failed["created_at"],
                failed=True,
            ),
        )
        write_commit_execution_claim(
            store,
            receipt,
            {**claim, "status": "failed", "completed_at": failed["created_at"], "heartbeat_at": failed["created_at"]},
        )
        return {
            "ok": False,
            "error": "planned_effect_commit_failed",
            "requested_plan": requested_plan,
            "commit_requested": True,
            "status": "failed",
            "description": "Execute accepted the planned effect boundary, but the scoped adapter failed. The result handle records the failure state.",
            "planner_binding": {
                "verified": True,
                "requested": requested_plan,
                "canonical_plan_id": canonical_plan_id,
                "receipt_sha256": receipt,
                "operation": plan.get("operation"),
                "short_receipt_matches": resolved.matches,
                "context_fingerprint_verified": context_matches,
                "planned_context_sha256": planned_context_sha,
                "current_context_sha256": current_context_sha,
            },
            "commit_id": commit_id,
            "result_id": result_id,
            "observe_result_cmd": f"./xctx observe {result_id}",
            "mutations_applied": 0,
            "next_move": f"./xctx observe {result_id}",
        }

    finished = utc_now()
    failed = adapter_payload_failed(live)
    result_payload = terminal_result_payload(
        running_result=running_result,
        canonical_plan_id=canonical_plan_id,
        commit_id=commit_id,
        result_id=result_id,
        planned_effect=planned_effect,
        live_payload=live,
        failed=failed,
        finished=finished,
    )
    completed_at = str(result_payload["completed_at"])
    claim = {**claim, "status": "finalizing", "heartbeat_at": completed_at}
    write_commit_execution_claim(store, receipt, claim)
    if failed:
        commit["status"] = "failed"
        commit["completed_at"] = completed_at
    else:
        commit["status"] = "committed"
        commit["completed_at"] = completed_at
    write_runtime_artifact(store, "commit", receipt, commit)
    write_runtime_artifact(store, "result", receipt, result_payload)
    mark_plan_committed(
        store,
        plan,
        committed_at=completed_at,
        commit_id=commit_id,
        result_id=result_id,
    )
    write_runtime_artifact(
        store,
        "master_plan",
        receipt,
        materialized_artifact_committed(
            master_plan,
            commit_id=commit_id,
            result_id=result_id,
            committed_at=completed_at,
        ),
    )
    write_runtime_artifact(
        store,
        "sub_plan",
        receipt,
        materialized_artifact_committed(
            sub_plan,
            commit_id=commit_id,
            result_id=result_id,
            committed_at=completed_at,
        ),
    )
    write_commit_execution_claim(
        store,
        receipt,
        {**claim, "status": "failed" if failed else "succeeded", "completed_at": completed_at, "heartbeat_at": completed_at},
    )
    return final_execute_response(
        requested_plan=requested_plan,
        plan=plan,
        resolved=resolved,
        canonical_plan_id=canonical_plan_id,
        receipt=receipt,
        commit_id=commit_id,
        result_id=result_id,
        context_matches=context_matches,
        planned_context_sha=planned_context_sha,
        current_context_sha=current_context_sha,
        planned_effect=planned_effect,
        failed=failed,
    )
