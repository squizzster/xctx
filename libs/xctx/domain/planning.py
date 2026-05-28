"""Plan rehearsal and execute binding for the protocol-local xctx ledger."""

from __future__ import annotations

from typing import Any

from xctx.domain.execution_contract import parse_plan_request
from xctx.domain.planning_execute import execute_payload as _execute_payload
from xctx.domain.planning_intent import resolve_planned_action as _resolve_planned_action
from xctx.domain.planning_planned_effects import planned_effect_plan_payload as _planned_effect_plan_payload
from xctx.domain.planning_read_only import read_only_plan_payload as _read_only_plan_payload


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


def execute_payload(args: list[str], commit: bool, store: dict[str, Any]) -> dict[str, Any]:
    return _execute_payload(args, commit, store)
