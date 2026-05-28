"""Plan ledger state helpers shared by plan and execute flows."""

from __future__ import annotations

from typing import Any

from xctx.domain.planning_common import plan_context
from xctx.store.plans import write_plan


def plan_is_committed(plan: dict[str, Any]) -> bool:
    return str(plan.get("execution_status") or "").lower() == "committed"


def mark_plan_committed(
    store: dict[str, Any],
    plan: dict[str, Any],
    *,
    committed_at: str,
    commit_id: str | None = None,
    result_id: str | None = None,
) -> None:
    updated = dict(plan)
    updated["execution_status"] = "committed"
    updated["committed_at"] = committed_at
    if commit_id:
        updated["commit_id"] = commit_id
    if result_id:
        updated["result_id"] = result_id
    write_plan(store, updated)


def context_match(store: dict[str, Any], plan: dict[str, Any] | None) -> tuple[bool, str | None, str | None]:
    if not plan:
        return False, None, plan_context(store)["config_sha256"]
    current = plan_context(store)["config_sha256"]
    stored_context = plan.get("planner_context")
    if not isinstance(stored_context, dict):
        return False, None, current
    planned = stored_context.get("config_sha256")
    return planned == current, str(planned) if planned else None, current
