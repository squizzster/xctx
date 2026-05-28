"""Adapter invocation for planned-effect commits."""

from __future__ import annotations

from typing import Any

from xctx.domain.core import resolve_subdomain
from xctx.domain.planning_execution import commit_context_args
from xctx.ports.external_command import call_external_command


def invoke_commit_adapter(
    *,
    store: dict[str, Any],
    planned_effect: dict[str, Any],
    canonical_plan_id: str,
    commit_id: str,
    result_id: str,
) -> dict[str, Any]:
    subdomain = resolve_subdomain(
        store,
        str(planned_effect["agent_domain"]),
        str(planned_effect["agent_subdomain"]),
    )
    return call_external_command(
        store,
        subdomain,
        [
            str(planned_effect["commit_adapter_command"]),
            *[str(arg) for arg in planned_effect.get("adapter_args") or []],
            *commit_context_args(
                canonical_plan_id=canonical_plan_id,
                commit_id=commit_id,
                result_id=result_id,
            ),
        ],
    )
