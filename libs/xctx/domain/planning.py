"""Plan rehearsal and execute binding for the protocol-local xctx ledger."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from xctx.domain.core import resolve_subdomain
from xctx.domain.execution_contract import parse_execute_request, parse_plan_request
from xctx.domain.planning_common import receipt_for_payload as _receipt_for_payload
from xctx.domain.planning_commit_state import (
    RUNNING_CLAIM_STALE_SECONDS,
    TERMINAL_CLAIM_STATUSES,
    claim_status as _claim_status,
    mark_claim_abandoned_if_stale as _mark_claim_abandoned_if_stale,
    new_execution_claim as _new_execution_claim,
)
from xctx.domain.planning_ledger import (
    context_match as _context_match,
    mark_plan_committed as _mark_plan_committed,
    plan_is_committed as _plan_is_committed,
)
from xctx.domain.planning_materialization import (
    verify_plan_materialization as _verify_plan_materialization,
)
from xctx.domain.planning_payloads import (
    adapter_payload_failed as _adapter_payload_failed,
    execution_claim_refusal_payload as _execution_claim_refusal_payload,
    failed_result_payload as _failed_result_payload,
    heartbeat as _heartbeat,
    plan_already_committed_payload as _plan_already_committed_payload,
)
from xctx.domain.planning_intent import resolve_planned_action as _resolve_planned_action
from xctx.domain.planning_planned_effects import planned_effect_plan_payload as _planned_effect_plan_payload
from xctx.domain.planning_read_only import read_only_plan_payload as _read_only_plan_payload
from xctx.ports.external_command import call_external_command
from xctx.process.redaction import redact_preview, redact_value
from xctx.store.plans import PLAN_RECEIPT_PREFIX, resolve_plan
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


## Protocol boundary: the plan ledger is xctx-local evidence. It binds execute
## requests to recorded dry-runs or planned effects. Business/domain mutation is
## still owned by scoped adapters and only happens after explicit execute --commit.


def _plan_full_payload(args: list[str], store: dict[str, Any]) -> dict[str, Any]:
    request = parse_plan_request(args)
    planned = _resolve_planned_action(store, request.operation, list(request.raw_args[1:]))
    if planned:
        return _planned_effect_plan_payload(args, store, planned)
    return _read_only_plan_payload(args, store)


def plan_payload(args: list[str], store: dict[str, Any]) -> dict[str, Any]:
    return _plan_full_payload(args, store)


def _execute_planned_effect_payload(
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
    materialized, master_plan, sub_plan, _manifest, materialization_errors = _verify_plan_materialization(
        store,
        plan,
        receipt,
    )
    if not materialized or not master_plan or not sub_plan:
        return _execution_claim_refusal_payload(
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
        existing_claim = _mark_claim_abandoned_if_stale(store, receipt, existing_claim)

    if _plan_is_committed(plan) or _claim_status(existing_claim) in TERMINAL_CLAIM_STATUSES:
        return _plan_already_committed_payload(
            requested_plan=requested_plan,
            plan={**plan, "commit_id": commit_id, "result_id": result_id},
            resolved=resolved,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
        )
    if existing_claim:
        return _execution_claim_refusal_payload(
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
                if _claim_status(existing_claim) in {"claimed", "running", "finalizing"}
                else "planned_effect_execution_requires_repair"
            ),
            existing_commit=existing_commit,
            existing_result=existing_result,
            claim=existing_claim,
        )
    if existing_commit or existing_result:
        return _execution_claim_refusal_payload(
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

    claim = _new_execution_claim(
        plan=plan,
        receipt=receipt,
        commit_id=commit_id,
        result_id=result_id,
        current_context_sha=current_context_sha,
    )
    if not create_commit_execution_claim(store, receipt, claim):
        existing_claim = read_commit_execution_claim(store, receipt)
        if existing_claim:
            existing_claim = _mark_claim_abandoned_if_stale(store, receipt, existing_claim)
        return _execution_claim_refusal_payload(
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

    now = utc_now()
    running_lease_expires_at = now + timedelta(seconds=RUNNING_CLAIM_STALE_SECONDS)
    running_result = {
        "result_id": result_id,
        "commit_id": commit_id,
        "plan_id": canonical_plan_id,
        "status": "running",
        "created_at": isoformat_utc(now),
        "lease_expires_at": isoformat_utc(running_lease_expires_at),
        "heartbeat_at": isoformat_utc(now),
        "heartbeat": _heartbeat(
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
        "created_at": isoformat_utc(now),
        "planned_effect": {
            key: planned_effect.get(key)
            for key in ("agent_domain", "agent_subdomain", "action", "implemented_by", "commit_adapter_command")
            if planned_effect.get(key) is not None
        },
    }
    write_runtime_artifact(store, "commit", receipt, commit)
    write_runtime_artifact(store, "result", receipt, running_result)
    updated_master_plan = {
        **master_plan,
        "status": "committing",
        "execution_status": "committing",
        "commit_id": commit_id,
        "result_id": result_id,
        "committed_at": running_result["created_at"],
    }
    write_runtime_artifact(store, "master_plan", receipt, updated_master_plan)
    write_runtime_artifact(
        store,
        "sub_plan",
        receipt,
        {
            **sub_plan,
            "status": "committing",
            "execution_status": "committing",
            "commit_id": commit_id,
            "result_id": result_id,
            "committed_at": running_result["created_at"],
        },
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
        commit_context_args = [
            "--xctx-plan-id",
            canonical_plan_id,
            "--xctx-commit-id",
            commit_id,
            "--xctx-result-id",
            result_id,
        ]
        live = call_external_command(
            store,
            subdomain,
            [
                str(planned_effect["commit_adapter_command"]),
                *[str(arg) for arg in planned_effect.get("adapter_args") or []],
                *commit_context_args,
            ],
        )
    except Exception as exc:  # keep the committed result handle observable
        message = redact_preview(str(exc))
        failed = _failed_result_payload(plan=plan, planned_effect=planned_effect, receipt=receipt, message=message)
        commit["status"] = "failed"
        commit["error"] = message
        commit["completed_at"] = failed["created_at"]
        write_runtime_artifact(store, "commit", receipt, commit)
        write_runtime_artifact(store, "result", receipt, failed)
        _mark_plan_committed(
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
                {
                    **master_plan,
                    "status": "committed",
                    "execution_status": "committed",
                    "commit_id": commit_id,
                    "result_id": result_id,
                    "committed_at": failed["created_at"],
                    "failed": True,
                },
            )
        write_runtime_artifact(
            store,
            "sub_plan",
            receipt,
            {
                **sub_plan,
                "status": "committed",
                "execution_status": "committed",
                "commit_id": commit_id,
                "result_id": result_id,
                "committed_at": failed["created_at"],
                "failed": True,
            },
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
    failed = _adapter_payload_failed(live)
    ttl_seconds = int(planned_effect.get("result_ttl_seconds") or 300)
    completed_at = isoformat_utc(finished)
    expires_at = isoformat_utc(finished + timedelta(seconds=ttl_seconds))
    claim = {**claim, "status": "finalizing", "heartbeat_at": completed_at}
    write_commit_execution_claim(store, receipt, claim)
    result_payload = {
        "result_id": result_id,
        "commit_id": commit_id,
        "plan_id": canonical_plan_id,
        "status": "failed" if failed else "ready",
        "created_at": running_result["created_at"],
        "completed_at": completed_at,
        "expires_at": expires_at,
        "heartbeat_at": completed_at,
        "heartbeat": (
            {"phase": "failed", "message": "Scoped adapter returned a failure payload."}
            if failed
            else _heartbeat(planned_effect, "complete_heartbeat", "complete", "Result is ready.")
        ),
        "payload": None if failed else live,
    }
    if failed:
        result_payload["failure_payload"] = redact_value(live)
        commit["status"] = "failed"
        commit["completed_at"] = completed_at
    else:
        commit["status"] = "committed"
        commit["completed_at"] = completed_at
    write_runtime_artifact(store, "commit", receipt, commit)
    write_runtime_artifact(store, "result", receipt, result_payload)
    _mark_plan_committed(
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
        {
            **master_plan,
            "status": "committed",
            "execution_status": "committed",
            "commit_id": commit_id,
            "result_id": result_id,
            "committed_at": completed_at,
        },
    )
    write_runtime_artifact(
        store,
        "sub_plan",
        receipt,
        {
            **sub_plan,
            "status": "committed",
            "execution_status": "committed",
            "commit_id": commit_id,
            "result_id": result_id,
            "committed_at": completed_at,
        },
    )
    write_commit_execution_claim(
        store,
        receipt,
        {**claim, "status": "failed" if failed else "succeeded", "completed_at": completed_at, "heartbeat_at": completed_at},
    )
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
        "mutations_applied": 1 if not failed and planned_effect.get("writes_to_db") else 0,
        "execution_receipt_sha256": _receipt_for_payload(
            {
                "execute": requested_plan,
                "bound_plan": canonical_plan_id,
                "commit": True,
                "commit_id": commit_id,
                "result_id": result_id,
                "mutations_applied": 1 if not failed and planned_effect.get("writes_to_db") else 0,
                "context_verified": True,
            }
        ),
        "next_move": f"./xctx observe {result_id}",
    }


def _execute_full_payload(args: list[str], commit: bool, store: dict[str, Any]) -> dict[str, Any]:
    cleaned = [str(arg).strip() for arg in args if str(arg).strip()]
    if not cleaned:
        return {
            "ok": False,
            "error": "plan_required",
            "requested_plan": None,
            "commit_requested": commit,
            "status": "refused",
            "description": "Execute requires a canonical plan id.",
            "next_move": "./xctx plan <operation> <target>",
        }
    if len(cleaned) != 1:
        return {
            "ok": False,
            "error": "invalid_execute_command",
            "requested_plan": " ".join(cleaned),
            "commit_requested": commit,
            "status": "refused",
            "description": "Execute accepts exactly one plan id.",
            "next_move": "./xctx execute <PLAN_ID> --commit",
        }
    request = parse_execute_request(args, commit=commit)
    requested_plan = request.plan_identifier
    if not str(requested_plan).startswith(PLAN_RECEIPT_PREFIX):
        return {
            "ok": False,
            "error": "plan_id_required",
            "requested_plan": requested_plan,
            "commit_requested": commit,
            "status": "refused",
            "description": "Execute requires a canonical plan id. Raw receipt hashes and short receipts are not executable.",
            "next_move": "./xctx execute plan:sha256:<sha256> --commit",
        }
    if not request.commit:
        return {
            "ok": False,
            "error": "commit_required",
            "requested_plan": requested_plan,
            "commit_requested": False,
            "status": "refused",
            "description": "Execute requires explicit --commit before any recorded plan can be accepted.",
            "next_move": f"./xctx execute {requested_plan} --commit",
        }

    resolved = resolve_plan(store, requested_plan)
    accepted = resolved.ok
    canonical_plan_id = None
    bound_operation = None
    bound_receipt = None
    context_matches = False
    planned_context_sha = None
    current_context_sha = None
    if resolved.plan:
        bound_receipt = resolved.plan.get("receipt_sha256")
        canonical_plan_id = resolved.plan.get("plan_id")
        bound_operation = resolved.plan.get("operation")
        context_matches, planned_context_sha, current_context_sha = _context_match(store, resolved.plan)
        if not context_matches:
            accepted = False
            resolved = resolved.__class__(False, "stale_plan_context", resolved.requested_plan, resolved.plan, resolved.matches)

    if accepted and resolved.plan and _plan_is_committed(resolved.plan):
        return _plan_already_committed_payload(
            requested_plan=requested_plan,
            plan=resolved.plan,
            resolved=resolved,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
        )

    if accepted and resolved.plan and isinstance(resolved.plan.get("planned_effect"), dict):
        return _execute_planned_effect_payload(
            requested_plan=requested_plan,
            resolved=resolved,
            store=store,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
        )

    payload = {
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
        "execution_receipt_sha256": _receipt_for_payload(
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
    if accepted and resolved.plan:
        _mark_plan_committed(
            store,
            resolved.plan,
            committed_at=isoformat_utc(utc_now()),
        )
    return payload


def execute_payload(args: list[str], commit: bool, store: dict[str, Any]) -> dict[str, Any]:
    return _execute_full_payload(args, commit, store)
