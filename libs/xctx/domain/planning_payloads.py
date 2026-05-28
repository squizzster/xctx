"""Payload builders used by plan execution orchestration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from xctx.domain.planning_commit_state import claim_status
from xctx.store.runtime_artifacts import isoformat_utc, runtime_artifact_ref, utc_now


def plan_already_committed_payload(
    *,
    requested_plan: str,
    plan: dict[str, Any],
    resolved: Any,
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
) -> dict[str, Any]:
    result_id = str(plan.get("result_id") or plan.get("expected_result_id") or "")
    return {
        "ok": False,
        "error": "plan_already_committed",
        "requested_plan": requested_plan,
        "commit_requested": True,
        "status": "refused",
        "description": "This plan has already been committed. Plans are one-shot; observe the existing result or create a new plan.",
        "planner_binding": {
            "verified": True,
            "requested": requested_plan,
            "canonical_plan_id": plan.get("plan_id"),
            "receipt_sha256": plan.get("receipt_sha256"),
            "operation": plan.get("operation"),
            "short_receipt_matches": resolved.matches,
            "context_fingerprint_verified": context_matches,
            "planned_context_sha256": planned_context_sha,
            "current_context_sha256": current_context_sha,
        },
        "commit_id": plan.get("commit_id") or plan.get("expected_commit_id"),
        "result_id": result_id or None,
        "observe_result_cmd": f"./xctx observe {result_id}" if result_id else None,
        "mutations_applied": 0,
        "next_move": f"./xctx observe {result_id}" if result_id else "./xctx plan <operation> <target>",
    }


def heartbeat(planned_effect: dict[str, Any], key: str, fallback_phase: str, fallback_message: str) -> dict[str, Any]:
    configured = planned_effect.get(key)
    if isinstance(configured, dict):
        return {
            "phase": configured.get("phase") or fallback_phase,
            "message": configured.get("message") or fallback_message,
        }
    return {"phase": fallback_phase, "message": fallback_message}


def adapter_payload_failed(payload: dict[str, Any]) -> bool:
    object_type = str(payload.get("object_type", "")).lower()
    if object_type.endswith("_error"):
        return True
    command_status = payload.get("command_status")
    return isinstance(command_status, dict) and command_status.get("ok") is False


def execution_claim_refusal_payload(
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
) -> dict[str, Any]:
    current_claim_status = claim_status(claim) or None
    return {
        "ok": False,
        "error": reason,
        "requested_plan": requested_plan,
        "commit_requested": True,
        "status": "repair_required" if reason != "planned_effect_execution_in_progress" else "running",
        "description": (
            "Execute found existing ledger evidence for this planned effect and will not invoke the adapter again "
            "without an explicit repair path."
        ),
        "planner_binding": {
            "verified": True,
            "requested": requested_plan,
            "canonical_plan_id": plan.get("plan_id"),
            "receipt_sha256": receipt,
            "operation": plan.get("operation"),
            "short_receipt_matches": resolved.matches,
            "context_fingerprint_verified": context_matches,
            "planned_context_sha256": planned_context_sha,
            "current_context_sha256": current_context_sha,
        },
        "commit_id": commit_id,
        "result_id": result_id,
        "execution_claim_status": current_claim_status,
        "materialization_errors": list(materialization_errors or []),
        "existing_commit_status": existing_commit.get("status") if isinstance(existing_commit, dict) else None,
        "existing_result_status": existing_result.get("status") if isinstance(existing_result, dict) else None,
        "observe_result_cmd": f"./xctx observe {result_id}",
        "mutations_applied": 0,
        "next_move": f"./xctx observe {result_id}" if existing_result else "./xctx repair <finding_id>",
    }


def failed_result_payload(
    *,
    plan: dict[str, Any],
    planned_effect: dict[str, Any],
    receipt: str,
    message: str,
) -> dict[str, Any]:
    now = utc_now()
    ttl_seconds = int(planned_effect.get("result_ttl_seconds") or 300)
    expires_at = now + timedelta(seconds=ttl_seconds)
    return {
        "result_id": runtime_artifact_ref("result", receipt),
        "commit_id": runtime_artifact_ref("commit", receipt),
        "plan_id": plan.get("plan_id"),
        "status": "failed",
        "created_at": isoformat_utc(now),
        "expires_at": isoformat_utc(expires_at),
        "heartbeat_at": isoformat_utc(now),
        "heartbeat": {"phase": "failed", "message": message},
        "payload": None,
    }
