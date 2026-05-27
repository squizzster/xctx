"""Interface payload builders for scoped xctx actions."""

from __future__ import annotations

from typing import Any

from xctx.domain.core import compact_subdomain
from xctx.protocol.guidance import command_hint


## Protocol boundary: action interface payloads publish declared metadata only.
def scoped_mode_interface_payload(
    store: dict[str, Any],
    action_name: str,
    action: dict[str, Any],
    domain_id: str,
    subdomain: dict[str, Any],
    *,
    compact: bool,
    query_required: bool,
) -> dict[str, Any]:
    ## Boundary guard: copy interface metadata declared by the scoped pack.
    ## Do not synthesize domain-pack examples or argument meaning in core code.
    public_action = {key: value for key, value in action.items() if not key.startswith("_")}
    run_cmd = public_action.get("run_cmd")
    payload: dict[str, Any] = {
        "object_type": "xctx_action_discovery_interface",
        "agent_domain": domain_id,
        "agent_subdomain": compact_subdomain(store, domain_id, subdomain) if compact else subdomain["id"],
        "action": action_name,
        "action_description": public_action.get("desc"),
        "query_required": query_required,
        "configured_action": public_action,
        "data_boundary": "Interface only. Provide a query to execute this discovery action.",
    }
    if public_action.get("domain_affordance"):
        domain_action_name = str(public_action.get("domain_action_name") or action_name)
        payload["domain_affordance"] = True
        payload["domain_action_name"] = domain_action_name
        payload["domain_affordance_run_cmd"] = str(
            public_action.get("domain_run_cmd") or f"./xctx discover {domain_id}::{domain_action_name}"
        )
        implemented_by = str(public_action.get("implemented_by") or f"{domain_id}::{subdomain['id']}::{action_name}")
        payload["implemented_by"] = implemented_by
        payload["implemented_by_run_cmd"] = str(
            public_action.get("implemented_by_run_cmd") or f"./xctx discover {implemented_by}"
        )
    if run_cmd:
        payload["run_cmd"] = run_cmd
        payload["next_moves"] = [command_hint(str(run_cmd))]
    for key in (
        "mode",
        "mode_kind",
        "grammar",
        "argument_patterns",
        "accepted_arguments",
        "examples",
        "example_queries",
        "related_commands",
        "related_modes",
        "returns",
        "collection",
        "projections",
        "output_projections",
        "valid_targets",
        "valid_identity_patterns",
    ):
        if key in public_action:
            payload[key] = public_action[key]
    return payload
