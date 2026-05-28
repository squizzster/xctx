"""Discovery payload construction for xctx agent domains and subdomains."""

from __future__ import annotations

from typing import Any

from xctx.domain.actions import (
    canonical_action_for_structural_token,
    compact_action_index,
    iter_domain_action_configs,
    parse_scoped_subdomain_mode_ref,
    selected_action_projection,
    subdomain_action_config,
    validate_declared_action_args,
)
from xctx.domain.core import (
    attach_agent_subdomain_identity,
    compact_domain,
    compact_subdomain,
    offline_subdomain_payload,
    resolve_domain,
    resolve_subdomain,
)
from xctx.domain.interfaces import scoped_mode_interface_payload
from xctx.domain.routing import parse_ref, parse_scoped_action, scoped_action_run_cmd
from xctx.errors import XctxError
from xctx.ports.external_command import call_external_command
from xctx.protocol.accessors import command_map_for_group, protocol_version
from xctx.protocol.descriptions import detail_enabled, selected_description, with_description
from xctx.protocol.detail import detail_at_least, is_max
from xctx.protocol.guidance import command_hint, command_hints, root_protocol_next_moves
from xctx.protocol.option_surface import target_option_surface
from xctx.store.runtime_artifacts import is_runtime_ref, runtime_artifact_discovery_payload


## Protocol boundary: discovery exposes configured/live affordances and routes
## scoped execution, without hardcoding a domain pack's business vocabulary.
def agent_domain_scope_guidance(
    store: dict[str, Any],
    domains: list[dict[str, Any]],
) -> dict[str, Any]:
    root = store.get("universe", {}).get("root", {})
    guidance = root.get("next_move_guidance") or {}
    template = str(guidance.get("agent_domain_scope_template") or "./xctx discover {{agent_domain_id}}::")
    requested_example_ids = [str(item) for item in guidance.get("example_agent_domains") or []]
    domains_by_id = {str(domain.get("id")): domain for domain in domains if domain.get("id")}

    examples: list[str] = []
    for domain_id in requested_example_ids:
        domain = domains_by_id.get(domain_id)
        if domain and domain.get("status") == "online" and domain.get("run_cmd"):
            examples.append(str(domain["run_cmd"]))
    for domain in domains:
        run_cmd = str(domain.get("run_cmd") or "")
        if domain.get("status") == "online" and run_cmd and run_cmd not in examples:
            examples.append(run_cmd)
        if len(examples) >= 2:
            break

    return {
        "agent_domain_id": str(
            guidance.get("agent_domain_id_context")
            or "Replace {{agent_domain_id}} with an id from agent_domains."
        ),
        "agent_domain_scope_template": template,
        "examples": examples[:2],
    }

def universe_discovery_payload(store: dict[str, Any]) -> dict[str, Any]:
    universe = store.get("universe", {})
    interface = universe.get("xctx_interface", {})
    domains = store.get("agent_domains", {})
    compact_domains = [compact_domain(store, domain) for domain in domains.values()]
    next_move_context = agent_domain_scope_guidance(store, compact_domains)
    payload = {
        "id": universe.get("name", "xctx_universe"),
        "kind": "xctx_universe",
        "version_xctx": protocol_version(store),
        "xctx": {
            "id": interface.get("id", "xctx"),
            "kind": interface.get("kind", "executable_context_protocol"),
            "name": interface.get("name", "xctx"),
            "description": selected_description(store, interface),
            "run_cmd": interface.get("run_cmd", "./xctx"),
        },
        "contains": {
            "agent_domain_count": len(domains),
            "online_agent_domain_count": sum(1 for domain in domains.values() if domain.get("status") == "online"),
            "offline_agent_domain_count": sum(1 for domain in domains.values() if domain.get("status") == "offline"),
            "maintenance_agent_domain_count": sum(
                1 for domain in domains.values() if domain.get("status") == "down_for_maintenance"
            ),
        },
        "agent_domains": compact_domains,
        "next_moves": root_protocol_next_moves(store),
    }
    if detail_at_least(store, "more"):
        payload["command_surface"] = {"xctx": command_map_for_group(store, "xctx", "main")}
        payload["next_move_context"] = next_move_context
    return payload

def root_discovery_payload(store: dict[str, Any]) -> dict[str, Any]:
    root = store.get("universe", {}).get("root", {})
    domains = [compact_domain(store, domain) for domain in store.get("agent_domains", {}).values()]
    next_move_context = agent_domain_scope_guidance(store, domains)
    payload = {
        "description": selected_description(store, root),
        "agent_domains": domains,
        "next_moves": root_protocol_next_moves(store),
    }
    if detail_at_least(store, "more"):
        payload["next_move_context"] = next_move_context
    return payload

def domain_discovery_payload(store: dict[str, Any], domain_id: str) -> dict[str, Any]:
    domain = resolve_domain(store, domain_id)
    payload = with_description(store, domain)
    payload["agent_subdomains"] = [
        compact_subdomain(store, domain_id, subdomain)
        for subdomain in sorted(domain.get("_subdomains", {}).values(), key=lambda item: item.get("_priority", 9999))
    ]
    if detail_at_least(store, "more"):
        payload["domain_affordances"] = {
            name: {key: value for key, value in config.items() if not key.startswith("_")}
            for name, config in iter_domain_action_configs(store, domain_id)
        }
    else:
        affordance_cmds = [
            str(config.get("run_cmd"))
            for _name, config in iter_domain_action_configs(store, domain_id)
            if config.get("run_cmd")
        ]
        if affordance_cmds:
            payload["affordance_count"] = len(affordance_cmds)
    payload["next_moves"] = command_hints(
        [f"./xctx discover {domain_id}::{sub['id']}" for sub in domain.get("_subdomains", {}).values()]
    )
    if domain.get("status") == "offline" and domain.get("repair_path"):
        repair_cmd = domain["repair_path"].get("run_cmd")
        payload["repair_cmd"] = repair_cmd
        if repair_cmd:
            payload["next_moves"].append(command_hint(str(repair_cmd)))
    if domain.get("status") == "down_for_maintenance":
        payload["repair_path"] = None
        payload["terminal_reason"] = "down_for_maintenance"
    return payload

def subdomain_discovery_payload(
    store: dict[str, Any],
    domain_id: str,
    subdomain_id: str,
    query_parts: list[str],
) -> dict[str, Any]:
    def has_concrete_discovery_query(parts: list[str]) -> bool:
        index = 0
        while index < len(parts):
            token = parts[index]
            if token == "--projection":
                index += 2
                continue
            return True
        return False

    subdomain = resolve_subdomain(store, domain_id, subdomain_id)
    if subdomain.get("status") != "online":
        return offline_subdomain_payload(store, domain_id, subdomain)
    if query_parts:
        action_name, action = subdomain_action_config(subdomain, query_parts[0])
        if action_name and action:
            raise XctxError(
                f"non-canonical subdomain action form: {domain_id}::{subdomain_id} {query_parts[0]}",
                next_moves=[f"./xctx discover {domain_id}::{subdomain_id}::{action_name}"],
            )
        canonical_action = canonical_action_for_structural_token(subdomain, query_parts[0])
        if canonical_action:
            raise XctxError(
                f"non-canonical action token for {domain_id}::{subdomain_id}: {query_parts[0]}",
                next_moves=[f"./xctx discover {domain_id}::{subdomain_id} {canonical_action}"],
            )
    _discover_action_name, discover_action = subdomain_action_config(subdomain, "discover")
    if discover_action:
        validate_declared_action_args(discover_action, query_parts)
    projection = selected_action_projection(discover_action, query_parts)
    live = call_external_command(store, subdomain, ["discover", *query_parts])
    actions = subdomain.get("actions", {})
    payload = {
        "description": selected_description(store, subdomain),
        "live_data": live,
    }
    attach_agent_subdomain_identity(payload, store, domain_id, subdomain)
    if detail_at_least(store, "more"):
        payload["configured_options"] = target_option_surface(store, subdomain)
    if projection:
        payload["projection"] = projection
    concrete_query = has_concrete_discovery_query(query_parts)
    if not concrete_query:
        if is_max(store):
            payload["configured_actions"] = actions
        elif detail_at_least(store, "more"):
            payload["configured_action_index"] = compact_action_index(actions)
        else:
            payload["configured_action_count"] = len(actions)
    if detail_enabled(store) and subdomain.get("data_description"):
        payload["data_description"] = subdomain["data_description"]
    return payload

def scoped_action_discovery_payload(
    store: dict[str, Any],
    domain_id: str,
    action_name: str,
    action: dict[str, Any],
    query_parts: list[str],
) -> dict[str, Any]:
    """Execute an opt-in domain affordance through an explicit agent-domain scope."""
    subdomain_id = str(action["agent_subdomain"])
    source_action = str(action.get("_source_action_name") or action_name)
    implemented_by = str(action.get("implemented_by") or f"{domain_id}::{subdomain_id}::{source_action}")
    subdomain = resolve_subdomain(store, domain_id, subdomain_id)
    if subdomain.get("status") != "online":
        return {
            "action": action_name,
            "action_status": "subdomain_not_online",
            "agent_subdomain": offline_subdomain_payload(store, domain_id, subdomain),
            "agent_subdomain_id": f"{domain_id}::{subdomain_id}",
        }
    query = " ".join(query_parts).strip()
    if action.get("query_required", True) and not query:
        return scoped_mode_interface_payload(
            store, action_name, action, domain_id, subdomain, compact=False, query_required=True
        )
    validate_declared_action_args(action, query_parts)
    live_command = action.get("entrypoint_command", "discover")
    live = call_external_command(store, subdomain, [live_command, *query_parts])
    payload = {
        "action": action_name,
        "domain_affordance": True,
        "implemented_by": implemented_by,
        "implemented_by_run_cmd": f"./xctx discover {implemented_by}",
        "action_description": action.get("desc"),
        "live_data": live,
    }
    attach_agent_subdomain_identity(payload, store, domain_id, subdomain)
    if source_action != action_name:
        payload["implemented_action"] = source_action
    if query and action.get("query_required", True):
        payload["query"] = query
    if query_parts:
        payload["action_args"] = query_parts
    return payload

def scoped_subdomain_action_payload(
    store: dict[str, Any],
    domain_id: str,
    subdomain: dict[str, Any],
    action_name: str,
    action: dict[str, Any],
    action_args: list[str],
) -> dict[str, Any]:
    query = " ".join(action_args).strip()
    if action.get("query_required", False) and not query:
        return scoped_mode_interface_payload(
            store, action_name, action, domain_id, subdomain, compact=True, query_required=True
        )
    validate_declared_action_args(action, action_args)
    live_command = action.get("entrypoint_command", action_name)
    live = call_external_command(store, subdomain, [live_command, *action_args])
    payload = {
        "action": action_name,
        "action_description": action.get("desc"),
        "live_data": live,
    }
    attach_agent_subdomain_identity(payload, store, domain_id, subdomain)
    if action.get("domain_affordance"):
        domain_action_name = str(action.get("domain_action_name") or action_name)
        payload["domain_affordance"] = True
        payload["domain_action_name"] = domain_action_name
        payload["domain_affordance_run_cmd"] = f"./xctx discover {domain_id}::{domain_action_name}"
        payload["implemented_by"] = f"{domain_id}::{subdomain['id']}::{action_name}"
    if action_args:
        payload["action_args"] = action_args
    return payload

def discover_payload(
    store: dict[str, Any],
    target: str | None,
    query_parts: list[str],
) -> tuple[str, dict[str, Any]]:
    if target is None:
        return "root", root_discovery_payload(store)
    if any(is_runtime_ref(kind, target) for kind in ("plan_manifest", "master_plan", "sub_plan", "commit")):
        if query_parts:
            raise XctxError(f"runtime artifact discovery does not accept extra arguments: {target}")
        return "root", runtime_artifact_discovery_payload(store, target)
    scoped_domain_id, scoped_action_name, scoped_action = parse_scoped_action(store, target, action_args=query_parts)
    if scoped_domain_id and scoped_action_name and scoped_action:
        return "agent_subdomain", scoped_action_discovery_payload(
            store,
            scoped_domain_id,
            scoped_action_name,
            scoped_action,
            query_parts,
        )
    mode_domain_id, mode_subdomain_id, scoped_mode_name, scoped_mode = parse_scoped_subdomain_mode_ref(
        store, target
    )
    if mode_domain_id and mode_subdomain_id and scoped_mode_name and scoped_mode:
        subdomain = resolve_subdomain(store, mode_domain_id, mode_subdomain_id)
        return "agent_subdomain", scoped_subdomain_action_payload(
            store,
            mode_domain_id,
            subdomain,
            scoped_mode_name,
            scoped_mode,
            query_parts,
        )
    domain_id, subdomain_id = parse_ref(store, target)
    if domain_id and subdomain_id:
        return "agent_subdomain", subdomain_discovery_payload(store, domain_id, subdomain_id, query_parts)
    if domain_id:
        if query_parts:
            raise XctxError(
                f"discovery arguments require a scoped agent_subdomain target: {domain_id}",
                next_moves=[f"./xctx discover {domain_id}::<agent_subdomain>"],
            )
        return "agent_domain", domain_discovery_payload(store, domain_id)

    scoped_run_cmd = scoped_action_run_cmd(store, target)
    if scoped_run_cmd:
        raise XctxError(f"unscoped discovery target: {target}", next_moves=[scoped_run_cmd])

    raise XctxError(f"unknown discovery target: {target}", next_moves=["./xctx discover"])
