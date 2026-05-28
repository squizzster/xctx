"""Pure execute-transition payload helpers for planned effects."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from xctx.domain.planning_commit_state import RUNNING_CLAIM_STALE_SECONDS
from xctx.domain.planning_common import receipt_for_payload
from xctx.domain.planning_payloads import heartbeat
from xctx.process.redaction import redact_value
from xctx.store.runtime_artifacts import isoformat_utc


def commit_context_args(*, canonical_plan_id: str, commit_id: str, result_id: str) -> list[str]:
    return [
        "--xctx-plan-id",
        canonical_plan_id,
        "--xctx-commit-id",
        commit_id,
        "--xctx-result-id",
        result_id,
    ]


def running_execution_artifacts(
    *,
    canonical_plan_id: str,
    commit_id: str,
    result_id: str,
    planned_effect: dict[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    created_at = isoformat_utc(now)
    running_lease_expires_at = now + timedelta(seconds=RUNNING_CLAIM_STALE_SECONDS)
    running_result = {
        "result_id": result_id,
        "commit_id": commit_id,
        "plan_id": canonical_plan_id,
        "status": "running",
        "created_at": created_at,
        "lease_expires_at": isoformat_utc(running_lease_expires_at),
        "heartbeat_at": created_at,
        "heartbeat": heartbeat(
            planned_effect,
            "running_heartbeat",
            "commit_running",
            "Commit accepted; adapter work is running.",
        ),
        "payload": None,
    }
    commit = {
        "commit_id": commit_id,
        "plan_id": canonical_plan_id,
        "result_id": result_id,
        "status": "claimed",
        "created_at": created_at,
        "planned_effect": {
            key: planned_effect.get(key)
            for key in ("agent_domain", "agent_subdomain", "action", "implemented_by", "commit_adapter_command")
            if planned_effect.get(key) is not None
        },
    }
    return commit, running_result


def materialized_artifact_committing(
    artifact: dict[str, Any],
    *,
    commit_id: str,
    result_id: str,
    committed_at: str,
) -> dict[str, Any]:
    return {
        **artifact,
        "status": "committing",
        "execution_status": "committing",
        "commit_id": commit_id,
        "result_id": result_id,
        "committed_at": committed_at,
    }


def materialized_artifact_committed(
    artifact: dict[str, Any],
    *,
    commit_id: str,
    result_id: str,
    committed_at: str,
    failed: bool = False,
) -> dict[str, Any]:
    updated = {
        **artifact,
        "status": "committed",
        "execution_status": "committed",
        "commit_id": commit_id,
        "result_id": result_id,
        "committed_at": committed_at,
    }
    if failed:
        updated["failed"] = True
    return updated


def terminal_result_payload(
    *,
    running_result: dict[str, Any],
    canonical_plan_id: str,
    commit_id: str,
    result_id: str,
    planned_effect: dict[str, Any],
    live_payload: dict[str, Any],
    failed: bool,
    finished: datetime,
) -> dict[str, Any]:
    completed_at = isoformat_utc(finished)
    ttl_seconds = int(planned_effect.get("result_ttl_seconds") or 300)
    result_payload = {
        "result_id": result_id,
        "commit_id": commit_id,
        "plan_id": canonical_plan_id,
        "status": "failed" if failed else "ready",
        "created_at": running_result["created_at"],
        "completed_at": completed_at,
        "expires_at": isoformat_utc(finished + timedelta(seconds=ttl_seconds)),
        "heartbeat_at": completed_at,
        "heartbeat": (
            {"phase": "failed", "message": "Scoped adapter returned a failure payload."}
            if failed
            else heartbeat(planned_effect, "complete_heartbeat", "complete", "Result is ready.")
        ),
        "payload": None if failed else live_payload,
    }
    if failed:
        result_payload["failure_payload"] = redact_value(live_payload)
    return result_payload


def final_execute_response(
    *,
    requested_plan: str,
    plan: dict[str, Any],
    resolved: Any,
    canonical_plan_id: str,
    receipt: str,
    commit_id: str,
    result_id: str,
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
    planned_effect: dict[str, Any],
    failed: bool,
) -> dict[str, Any]:
    mutations_applied = 1 if not failed and planned_effect.get("writes_to_db") else 0
    return {
        "ok": not failed,
        "error": "planned_effect_commit_failed" if failed else None,
        "requested_plan": requested_plan,
        "commit_requested": True,
        "status": "committed" if not failed else "failed",
        "description": "Execute committed a recorded planned effect through its scoped adapter and wrote a protocol-local result handle.",
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
        "mutations_applied": mutations_applied,
        "execution_receipt_sha256": receipt_for_payload(
            {
                "execute": requested_plan,
                "bound_plan": canonical_plan_id,
                "commit": True,
                "commit_id": commit_id,
                "result_id": result_id,
                "mutations_applied": mutations_applied,
                "context_verified": True,
            }
        ),
        "next_move": f"./xctx observe {result_id}",
    }


def execute_refusal_payload(
    *,
    error: str,
    requested_plan: str | None,
    commit_requested: bool,
    description: str,
    next_move: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": error,
        "requested_plan": requested_plan,
        "commit_requested": commit_requested,
        "status": "refused",
        "description": description,
        "next_move": next_move,
    }


def read_only_execute_response(
    *,
    requested_plan: str,
    resolved: Any,
    accepted: bool,
    canonical_plan_id: str | None,
    bound_receipt: str | None,
    bound_operation: str | None,
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
) -> dict[str, Any]:
    return {
        "ok": accepted,
        "error": None if accepted else resolved.error,
        "requested_plan": requested_plan,
        "commit_requested": True,
        "status": "accepted_read_only_noop" if accepted else "refused",
        "description": "Execute accepts only receipts that bind to a recorded xctx plan made against the current protocol surface. No domain mutation was performed because the bundled adapters expose read-only operations.",
        "planner_binding": {
            "verified": accepted,
            "requested": requested_plan,
            "canonical_plan_id": canonical_plan_id,
            "receipt_sha256": bound_receipt,
            "operation": bound_operation,
            "short_receipt_matches": resolved.matches,
            "context_fingerprint_verified": context_matches if resolved.plan else False,
            "planned_context_sha256": planned_context_sha,
            "current_context_sha256": current_context_sha,
        },
        "mutations_applied": 0,
        "execution_receipt_sha256": receipt_for_payload(
            {
                "execute": requested_plan,
                "bound_plan": canonical_plan_id,
                "commit": True,
                "mutations_applied": 0,
                "context_verified": accepted,
            }
        ),
        "next_move": "./xctx audit root" if accepted else "./xctx plan <operation> <target>",
    }
