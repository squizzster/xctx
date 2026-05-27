"""Plan rehearsal and execute binding for the protocol-local xctx ledger."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from xctx.config.paths import as_project_path
from xctx.domain.execution_contract import parse_execute_request, parse_plan_request
from xctx.protocol.guidance import command_hints
from xctx.store.fingerprints import config_fingerprint_payload
from xctx.store.plans import plan_store_dir, resolve_plan, write_plan


## Protocol boundary: the plan ledger is xctx-local evidence. It binds execute
## requests to recorded dry-runs; it does not mutate business/domain state.
def _receipt_for_payload(payload: dict[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _plan_context(store: dict[str, Any]) -> dict[str, Any]:
    fingerprint = config_fingerprint_payload(store)
    return {
        "config_sha256": fingerprint["sha256"],
        "protocol_version": fingerprint["protocol_version"],
        "config_file_count": fingerprint["config_file_count"],
        "fingerprint_algorithm": fingerprint["algorithm"],
    }


def _plan_full_payload(args: list[str], store: dict[str, Any]) -> dict[str, Any]:
    request = parse_plan_request(args)
    context = _plan_context(store)
    operation = request.operation_text
    plan_material = {
        "protocol": "xctx.v4.2",
        "operation": operation or None,
        "operation_token": request.operation,
        "target": request.target,
        "surface": "read_only_external_adapter_surface",
        "mutation_policy": "no_state_change_planned",
        "planner_context": context,
    }
    receipt = _receipt_for_payload(plan_material)
    plan_id = f"plan:sha256:{receipt}"
    payload = {
        "operation": operation or None,
        "operation_token": request.operation,
        "target": request.target,
        "planner_id": receipt,
        "plan_id": plan_id,
        "status": "read_only_surface",
        "decision": "no_state_change_planned",
        "description": "xctx rehearsed the requested operation against the current protocol surface and recorded a deterministic execute binding. This read-only build performs no domain mutation.",
        "receipt_sha256": receipt,
        "receipt_sha5": receipt[:5],
        "receipt_note": "receipt_sha5 is accepted only when it resolves uniquely to a recorded plan in the local xctx plan ledger; receipt_sha256 is the canonical deterministic receipt.",
        "planner_context": context,
        "planner_ledger": as_project_path(store["root"], plan_store_dir(store)),
        "accepted_execute_cmd": f"./xctx execute {plan_id} --commit",
        "lawful_next_moves": command_hints(
            [
                "./xctx discover",
                "./xctx audit root",
                "./xctx repair <finding_id>",
                f"./xctx execute {plan_id} --commit",
                f"./xctx execute {receipt[:5]} --commit",
            ]
        ),
    }
    write_plan(store, payload)
    return payload


def plan_payload(args: list[str], store: dict[str, Any]) -> dict[str, Any]:
    return _plan_full_payload(args, store)

def _context_match(store: dict[str, Any], plan: dict[str, Any] | None) -> tuple[bool, str | None, str | None]:
    if not plan:
        return False, None, _plan_context(store)["config_sha256"]
    current = _plan_context(store)["config_sha256"]
    stored_context = plan.get("planner_context")
    if not isinstance(stored_context, dict):
        return False, None, current
    planned = stored_context.get("config_sha256")
    return planned == current, str(planned) if planned else None, current


def _execute_full_payload(args: list[str], commit: bool, store: dict[str, Any]) -> dict[str, Any]:
    cleaned = [str(arg).strip() for arg in args if str(arg).strip()]
    if not cleaned:
        return {
            "ok": False,
            "error": "plan_required",
            "requested_plan": None,
            "commit_requested": commit,
            "status": "refused",
            "description": "Execute requires a plan id or receipt.",
            "next_move": "./xctx plan <operation> <target>",
        }
    if len(cleaned) != 1:
        return {
            "ok": False,
            "error": "invalid_execute_command",
            "requested_plan": " ".join(cleaned),
            "commit_requested": commit,
            "status": "refused",
            "description": "Execute accepts exactly one plan id or receipt token.",
            "next_move": "./xctx execute <PLAN_ID|SHA256|SHA5> --commit",
        }
    request = parse_execute_request(args, commit=commit)
    requested_plan = request.plan_identifier
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


def execute_payload(args: list[str], commit: bool, store: dict[str, Any]) -> dict[str, Any]:
    return _execute_full_payload(args, commit, store)
