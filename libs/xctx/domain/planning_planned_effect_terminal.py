"""Terminal planned-effect execution transitions."""

from __future__ import annotations

from typing import Any

from xctx.domain.planning_execution import (
    final_execute_response,
    materialized_artifact_committed,
    terminal_result_payload,
)
from xctx.domain.planning_ledger import mark_plan_committed
from xctx.domain.planning_payloads import adapter_payload_failed, failed_result_payload
from xctx.process.redaction import redact_preview
from xctx.store.runtime_artifacts import (
    utc_now,
    write_commit_execution_claim,
    write_runtime_artifact,
)


def adapter_exception_failure_response(
    *,
    requested_plan: str,
    resolved: Any,
    store: dict[str, Any],
    plan: dict[str, Any],
    receipt: str,
    canonical_plan_id: str,
    commit_id: str,
    result_id: str,
    planned_effect: dict[str, Any],
    commit: dict[str, Any],
    claim: dict[str, Any],
    master_plan: dict[str, Any] | None,
    sub_plan: dict[str, Any],
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
    exc: BaseException,
) -> dict[str, Any]:
    message = redact_preview(str(exc))
    failed = failed_result_payload(plan=plan, planned_effect=planned_effect, receipt=receipt, message=message)
    failed_commit = {
        **commit,
        "status": "failed",
        "error": message,
        "completed_at": failed["created_at"],
    }
    write_runtime_artifact(store, "commit", receipt, failed_commit)
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


def finalize_adapter_execution(
    *,
    requested_plan: str,
    resolved: Any,
    store: dict[str, Any],
    plan: dict[str, Any],
    receipt: str,
    canonical_plan_id: str,
    commit_id: str,
    result_id: str,
    planned_effect: dict[str, Any],
    commit: dict[str, Any],
    running_result: dict[str, Any],
    claim: dict[str, Any],
    master_plan: dict[str, Any],
    sub_plan: dict[str, Any],
    live_payload: dict[str, Any],
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
) -> dict[str, Any]:
    finished = utc_now()
    failed = adapter_payload_failed(live_payload)
    result_payload = terminal_result_payload(
        running_result=running_result,
        canonical_plan_id=canonical_plan_id,
        commit_id=commit_id,
        result_id=result_id,
        planned_effect=planned_effect,
        live_payload=live_payload,
        failed=failed,
        finished=finished,
    )
    completed_at = str(result_payload["completed_at"])
    finalizing_claim = {**claim, "status": "finalizing", "heartbeat_at": completed_at}
    write_commit_execution_claim(store, receipt, finalizing_claim)
    terminal_commit = {
        **commit,
        "status": "failed" if failed else "committed",
        "completed_at": completed_at,
    }
    write_runtime_artifact(store, "commit", receipt, terminal_commit)
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
        {
            **finalizing_claim,
            "status": "failed" if failed else "succeeded",
            "completed_at": completed_at,
            "heartbeat_at": completed_at,
        },
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
