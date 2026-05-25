"""Discovery payload construction for xctx agent domains and subdomains."""

from __future__ import annotations

from typing import Any

from xctx.domain.actions import (
    canonical_action_for_structural_token,
    compact_action_index,
    iter_domain_action_configs,
    parse_scoped_subdomain_mode_ref,
    selected_action_shape,
    subdomain_action_config,
    validate_declared_action_args,
)
from xctx.domain.core import compact_domain, compact_subdomain, offline_subdomain_payload, resolve_domain, resolve_subdomain
from xctx.domain.interfaces import scoped_mode_interface_payload
from xctx.domain.routing import parse_ref, parse_scoped_action, scoped_action_run_cmd
from xctx.errors import XctxError
from xctx.ports.external_command import call_external_command
from xctx.protocol.accessors import command_map_for_group, protocol_version
from xctx.protocol.descriptions import detail_enabled, selected_description, with_description
from xctx.protocol.option_surface import target_option_surface


## Protocol boundary: discovery exposes configured/live affordances and routes
## scoped execution, without hardcoding a domain pack's business vocabulary.
def agent_domain_scope_guidance(
    store: dict[str, Any],
    domains: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    root = store.get("universe", {}).get("root", {})
    guidance = root.get("next_move_guidance") or {}
    template = str(guidance.get("agent_domain_scope_template") or "./xctx discover {{agent_domain_id}}::")
    audit_cmd = str(guidance.get("audit_root_run_cmd") or "./xctx audit root")
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

    return [template, audit_cmd, *examples[:2]], {
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
    _next_moves, next_move_context = agent_domain_scope_guidance(store, compact_domains)
    discover_domains_cmd = interface.get("discover_domains_run_cmd", "./xctx discover")
    help_cmd = interface.get("help_run_cmd", "./xctx help")
    return {
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
        "command_surface": {
            "xctx": command_map_for_group(store, "xctx", "main"),
        },
        "next_move_context": next_move_context,
        "next_moves": [
            {
                "desc": "Discover configured agent domains in this universe.",
                "run_cmd": discover_domains_cmd,
            },
            {
                "desc": "Inspect the machine command surface explicitly.",
                "run_cmd": help_cmd,
            },
            {
                "desc": "Audit loaded configuration, live adapters, and offline/maintenance findings.",
                "run_cmd": "./xctx audit root",
            },
        ],
    }

def root_discovery_payload(store: dict[str, Any]) -> dict[str, Any]:
    root = store.get("universe", {}).get("root", {})
    domains = [compact_domain(store, domain) for domain in store.get("agent_domains", {}).values()]
    next_moves, next_move_context = agent_domain_scope_guidance(store, domains)
    return {
        "description": selected_description(store, root),
        "agent_domains": domains,
        "next_move_context": next_move_context,
        "next_moves": next_moves,
    }

def domain_discovery_payload(store: dict[str, Any], domain_id: str) -> dict[str, Any]:
    domain = resolve_domain(store, domain_id)
    payload = with_description(store, domain)
    payload["agent_subdomains"] = [
        compact_subdomain(store, domain_id, subdomain)
        for subdomain in sorted(domain.get("_subdomains", {}).values(), key=lambda item: item.get("_priority", 9999))
    ]
    payload["domain_affordances"] = {
        name: {key: value for key, value in config.items() if not key.startswith("_")}
        for name, config in iter_domain_action_configs(store, domain_id)
    }
    payload["next_moves"] = [f"./xctx discover {domain_id}::{sub['id']}" for sub in domain.get("_subdomains", {}).values()]
    if domain.get("status") == "offline" and domain.get("repair_path"):
        repair_cmd = domain["repair_path"].get("run_cmd")
        payload["repair_cmd"] = repair_cmd
        if repair_cmd:
            payload["next_moves"].append(repair_cmd)
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
            if token == "--shape":
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
            return scoped_subdomain_action_payload(store, domain_id, subdomain, action_name, action, query_parts[1:])
        canonical_action = canonical_action_for_structural_token(subdomain, query_parts[0])
        if canonical_action:
            raise XctxError(
                f"next valid move: use canonical action ./xctx discover {domain_id}::{subdomain_id} {canonical_action}"
            )
    _discover_action_name, discover_action = subdomain_action_config(subdomain, "discover")
    if discover_action:
        validate_declared_action_args(discover_action, query_parts)
    shape = selected_action_shape(discover_action, query_parts)
    live = call_external_command(store, subdomain, ["discover", *query_parts])
    actions = subdomain.get("actions", {})
    payload = {
        "agent_domain": domain_id,
        "agent_subdomain": compact_subdomain(store, domain_id, subdomain),
        "description": selected_description(store, subdomain),
        "configured_options": target_option_surface(store, subdomain),
        "live_data": live,
    }
    if shape:
        payload["shape"] = shape
    concrete_query = has_concrete_discovery_query(query_parts)
    if shape == "compact" and not concrete_query:
        payload["configured_action_index"] = compact_action_index(actions)
    elif shape != "compact" and not concrete_query:
        payload["configured_actions"] = actions
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
    subdomain = resolve_subdomain(store, domain_id, subdomain_id)
    if subdomain.get("status") != "online":
        return {
            "action": action_name,
            "action_status": "subdomain_not_online",
            "agent_domain": domain_id,
            "agent_subdomain": offline_subdomain_payload(store, domain_id, subdomain),
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
        "agent_domain": domain_id,
        "agent_subdomain": subdomain_id,
        "action_description": action.get("desc"),
        "live_data": live,
    }
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
        "agent_domain": domain_id,
        "agent_subdomain": compact_subdomain(store, domain_id, subdomain),
        "action": action_name,
        "action_description": action.get("desc"),
        "live_data": live,
    }
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
    scoped_domain_id, scoped_action_name, scoped_action = parse_scoped_action(store, target)
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
        return "agent_domain", domain_discovery_payload(store, domain_id)

    scoped_run_cmd = scoped_action_run_cmd(store, target)
    if scoped_run_cmd:
        raise XctxError(f"next valid move: {scoped_run_cmd}")

    raise XctxError("next valid move: ./xctx discover")
