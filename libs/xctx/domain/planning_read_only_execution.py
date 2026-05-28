"""Read-only execute transitions for recorded xctx plans."""

from __future__ import annotations

from typing import Any

from xctx.domain.planning_execution import read_only_execute_response
from xctx.domain.planning_ledger import mark_plan_committed
from xctx.store.runtime_artifacts import isoformat_utc, utc_now


def execute_read_only_plan(
    *,
    requested_plan: str,
    resolved: Any,
    accepted: bool,
    store: dict[str, Any],
    canonical_plan_id: str | None,
    bound_receipt: str | None,
    bound_operation: str | None,
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
) -> dict[str, Any]:
    payload = read_only_execute_response(
        requested_plan=requested_plan,
        resolved=resolved,
        accepted=accepted,
        canonical_plan_id=canonical_plan_id,
        bound_receipt=bound_receipt,
        bound_operation=bound_operation,
        context_matches=context_matches,
        planned_context_sha=planned_context_sha,
        current_context_sha=current_context_sha,
    )
    if accepted and resolved.plan:
        mark_plan_committed(
            store,
            resolved.plan,
            committed_at=isoformat_utc(utc_now()),
        )
    return payload
