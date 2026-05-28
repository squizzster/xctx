"""Plan-time preflight for planned effects.

The framework owns only the optional preflight hook and error propagation here.
The scoped adapter owns the validation meaning behind the configured command.
"""

from __future__ import annotations

from typing import Any

from xctx.domain.core import resolve_subdomain
from xctx.domain.planning_intent import PlannedAction, PlannedActionArgs
from xctx.errors import XctxError
from xctx.ports.external_command import call_external_command


def _preflight_failed(live: dict[str, Any]) -> tuple[bool, str | None]:
    if live.get("ok") is False:
        return True, str(live.get("error") or "planned effect preflight failed")
    command_status = live.get("command_status")
    if isinstance(command_status, dict) and command_status.get("ok") is False:
        return True, str(command_status.get("error") or "planned effect preflight failed")
    object_type = str(live.get("object_type") or "").lower()
    if object_type.endswith("_error"):
        return True, str(live.get("error") or object_type)
    return False, None


def planned_effect_plan_preflight(
    store: dict[str, Any],
    planned: PlannedAction,
    parsed_args: PlannedActionArgs,
) -> None:
    command = planned.planning.get("preflight_adapter_command")
    if not command:
        return

    subdomain = resolve_subdomain(store, planned.domain_id, planned.subdomain_id)
    live = call_external_command(store, subdomain, [str(command), *parsed_args.adapter_args])
    failed, error = _preflight_failed(live)
    if not failed:
        return

    next_moves = live.get("next_moves")
    if not isinstance(next_moves, list) or not next_moves:
        next_moves = [
            str(
                planned.action.get("run_cmd")
                or f"./xctx plan {planned.domain_id}::{planned.subdomain_id}::{planned.action_name}"
            )
        ]
    raise XctxError(error or "planned effect preflight failed", next_moves=next_moves)
