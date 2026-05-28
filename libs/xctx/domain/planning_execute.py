"""Execute request validation and routing for recorded xctx plans."""

from __future__ import annotations

from typing import Any

from xctx.domain.execution_contract import parse_execute_request
from xctx.domain.planning_execution import execute_refusal_payload
from xctx.domain.planning_ledger import context_match, plan_is_committed
from xctx.domain.planning_payloads import plan_already_committed_payload
from xctx.domain.planning_planned_effect_execution import execute_planned_effect_payload
from xctx.domain.planning_read_only_execution import execute_read_only_plan
from xctx.store.plans import PLAN_RECEIPT_PREFIX, resolve_plan


def execute_payload(args: list[str], commit: bool, store: dict[str, Any]) -> dict[str, Any]:
    cleaned = [str(arg).strip() for arg in args if str(arg).strip()]
    if not cleaned:
        return execute_refusal_payload(
            error="plan_required",
            requested_plan=None,
            commit_requested=commit,
            description="Execute requires a canonical plan id.",
            next_move="./xctx plan <operation> <target>",
        )
    if len(cleaned) != 1:
        return execute_refusal_payload(
            error="invalid_execute_command",
            requested_plan=" ".join(cleaned),
            commit_requested=commit,
            description="Execute accepts exactly one plan id.",
            next_move="./xctx execute <PLAN_ID> --commit",
        )
    request = parse_execute_request(args, commit=commit)
    requested_plan = request.plan_identifier
    if not str(requested_plan).startswith(PLAN_RECEIPT_PREFIX):
        return execute_refusal_payload(
            error="plan_id_required",
            requested_plan=requested_plan,
            commit_requested=commit,
            description="Execute requires a canonical plan id. Raw receipt hashes and short receipts are not executable.",
            next_move="./xctx execute plan:sha256:<sha256> --commit",
        )
    if not request.commit:
        return execute_refusal_payload(
            error="commit_required",
            requested_plan=requested_plan,
            commit_requested=False,
            description="Execute requires explicit --commit before any recorded plan can be accepted.",
            next_move=f"./xctx execute {requested_plan} --commit",
        )

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
        context_matches, planned_context_sha, current_context_sha = context_match(store, resolved.plan)
        if not context_matches:
            accepted = False
            resolved = resolved.__class__(False, "stale_plan_context", resolved.requested_plan, resolved.plan, resolved.matches)

    if accepted and resolved.plan and plan_is_committed(resolved.plan):
        return plan_already_committed_payload(
            requested_plan=requested_plan,
            plan=resolved.plan,
            resolved=resolved,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
        )

    if accepted and resolved.plan and isinstance(resolved.plan.get("planned_effect"), dict):
        return execute_planned_effect_payload(
            requested_plan=requested_plan,
            resolved=resolved,
            store=store,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
        )

    return execute_read_only_plan(
        requested_plan=requested_plan,
        resolved=resolved,
        accepted=accepted,
        store=store,
        canonical_plan_id=canonical_plan_id,
        bound_receipt=bound_receipt,
        bound_operation=bound_operation,
        context_matches=context_matches,
        planned_context_sha=planned_context_sha,
        current_context_sha=current_context_sha,
    )
