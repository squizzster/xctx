"""Agent-domain discovery, observation, audit, and repair behavior."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from xctx.config.paths import as_project_path
from xctx.errors import XctxError
from xctx.ports.external_command import call_external_command
from xctx.protocol.actions import action_matches
from xctx.protocol.accessors import command_aliases, command_map_for_group, protocol_version
from xctx.protocol.options import encode_cli_options_for_target, option_config_checks, target_option_surface
from xctx.protocol.descriptions import detail_enabled, selected_description, with_description
from xctx.store.plans import resolve_plan, write_plan


## Protocol boundary: this module routes configured domains, subdomains, and
## scoped modes. It must not encode domain-pack business vocabulary or policy.


def has_agent_domains(store: dict[str, Any]) -> bool:
    return bool(store.get("agent_domains"))


def active_domain(store: dict[str, Any]) -> dict[str, Any]:
    domain_id = store.get("active_agent_domain")
    domains = store.get("agent_domains", {})
    if domain_id in domains:
        return domains[domain_id]
    if domains:
        return next(iter(domains.values()))
    raise XctxError("next valid move: configure agent_domains")



def _domain_action_name(action_name: str, action: dict[str, Any]) -> str:
    return str(action.get("domain_action_name") or action_name)


def _domain_action_candidate(
    domain_id: str,
    subdomain_id: str,
    action_name: str,
    action: dict[str, Any],
) -> dict[str, Any]:
    """Build a domain-scoped action config from a subdomain action.

    Domain-scoped affordances are deliberately opt-in from subdomain YAML via
    ``domain_affordance: true``. This keeps the universe/root protocol surface
    generic while still allowing scoped conveniences once an agent has entered
    a named domain.
    """
    public_name = _domain_action_name(action_name, action)
    aliases = list(action.get("aliases") or [])
    if action_name != public_name and action_name not in aliases:
        aliases.append(action_name)
    return {
        **action,
        "aliases": aliases,
        "agent_domain": domain_id,
        "agent_subdomain": subdomain_id,
        "_action_name": public_name,
    }


def iter_domain_action_configs(store: dict[str, Any], domain_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Return opt-in affordance shortcuts for an already-scoped agent domain."""
    domain = store.get("agent_domains", {}).get(domain_id)
    if not domain:
        return []
    items: list[tuple[str, dict[str, Any]]] = []
    for subdomain_id, subdomain in sorted(
        (domain.get("_subdomains") or {}).items(),
        key=lambda item: item[1].get("_priority", 9999),
    ):
        for action_name, action in sorted(
            (subdomain.get("actions") or {}).items(),
            key=lambda item: item[1].get("priority", 9999),
        ):
            if not action.get("domain_affordance"):
                continue
            candidate = _domain_action_candidate(domain_id, subdomain_id, action_name, action)
            items.append((str(candidate["_action_name"]), candidate))
    return items


def domain_action_config(store: dict[str, Any], domain_id: str, action_name: str) -> dict[str, Any] | None:
    """Resolve a named affordance inside an explicit agent-domain scope."""
    for name, action in iter_domain_action_configs(store, domain_id):
        if action_matches(name, action, action_name):
            return {**action, "_action_name": name, "_matched_as": action_name}
    return None


def subdomain_action_config(subdomain: dict[str, Any], action_name: str) -> tuple[str | None, dict[str, Any] | None]:
    for name, action in (subdomain.get("actions") or {}).items():
        if action_matches(name, action, action_name):
            return name, {**action, "_action_name": name, "_matched_as": action_name}
    return None, None


def parse_scoped_subdomain_mode_ref(
    store: dict[str, Any],
    token: str | None,
) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    """Parse <agent_domain>::<agent_subdomain>::<mode> structurally."""
    ## Boundary guard: this parser validates only configured reference shape.
    ## The resolved mode's meaning is owned by YAML metadata and its adapter.
    if not token or "::" not in token:
        return None, None, None, None
    parts = token.split("::")
    if len(parts) != 3:
        return None, None, None, None
    domain_id, subdomain_token, action_token = parts
    if not domain_id:
        domain_id = str(store.get("active_agent_domain") or "")
    if not domain_id or not subdomain_token or not action_token:
        return None, None, None, None
    domains = store.get("agent_domains", {})
    if domain_id not in domains:
        return None, None, None, None
    aliases = domains[domain_id].get("_subdomain_aliases", {})
    subdomain_id = str(aliases.get(subdomain_token, subdomain_token))
    subdomain = (domains[domain_id].get("_subdomains") or {}).get(subdomain_id)
    if not subdomain:
        return None, None, None, None
    mode_name, mode = subdomain_action_config(subdomain, action_token)
    if not mode_name or not mode:
        raise XctxError(f"next valid move: choose a known action for {domain_id}::{subdomain_id} ({action_token})")
    return domain_id, subdomain_id, mode_name, mode


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
    if run_cmd:
        payload["run_cmd"] = run_cmd
        payload["next_moves"] = [run_cmd]
    for key in (
        "mode",
        "mode_kind",
        "grammar",
        "argument_shapes",
        "accepted_arguments",
        "examples",
        "example_queries",
        "related_commands",
        "related_modes",
        "returns",
        "collection",
        "valid_targets",
        "valid_identity_shapes",
    ):
        if key in public_action:
            payload[key] = public_action[key]
    return payload


def _collection_contract(action: dict[str, Any]) -> dict[str, Any]:
    collection = action.get("collection") or {}
    return collection if isinstance(collection, dict) else {}


def _has_collection_cursor(collection: dict[str, Any]) -> bool:
    return str(collection.get("cursor", "none")).lower() not in {"", "none", "false", "no"}


def _collection_shapes(collection: dict[str, Any]) -> set[str]:
    raw = collection.get("item_shapes", collection.get("shapes", [])) or []
    if isinstance(raw, str):
        raw = [raw]
    return {str(item) for item in raw}


def validate_declared_collection_args(action: dict[str, Any], action_args: list[str]) -> None:
    ## Protocol boundary: validate generic collection controls only when a
    ## scoped pack declares them. Cursor tokens stay opaque to xctx.
    collection = _collection_contract(action)
    index = 0
    while index < len(action_args):
        token = action_args[index]
        if token not in {"--limit", "--cursor", "--shape"}:
            index += 1
            continue
        if not collection:
            raise XctxError(f"next valid move: remove {token}; this action does not declare collection controls")
        if index + 1 >= len(action_args):
            raise XctxError(f"next valid move: provide a value for {token}")
        value = action_args[index + 1]
        if token == "--cursor":
            if not _has_collection_cursor(collection):
                raise XctxError("next valid move: remove --cursor; this collection does not declare cursor support")
        elif token == "--shape":
            shapes = _collection_shapes(collection)
            if not shapes:
                raise XctxError("next valid move: remove --shape; this collection does not declare item shapes")
            if value not in shapes:
                raise XctxError(f"next valid move: choose --shape {'|'.join(sorted(shapes))}")
        elif token == "--limit":
            try:
                limit = int(value)
            except ValueError as exc:
                raise XctxError("next valid move: --limit requires an integer") from exc
            if limit < 1:
                raise XctxError("next valid move: --limit must be at least 1")
            max_limit = collection.get("max_limit")
            if max_limit is not None and limit > int(max_limit):
                raise XctxError(f"next valid move: choose --limit <= {max_limit}")
        index += 2


def agent_routing(store: dict[str, Any]) -> dict[str, Any]:
    return store.get("universe", {}).get("agent_routing", {}) or {}


def compact_domain(store: dict[str, Any], domain: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": domain["id"],
        "kind": domain.get("kind", "agent_domain"),
        "status": domain.get("status", "unknown"),
        "health": domain.get("health"),
        "description": selected_description(store, domain),
        "run_cmd": f"./xctx discover {domain['id']}::",
    }
    if domain.get("offline_reason"):
        payload["offline_reason"] = domain["offline_reason"]
    repair_path = domain.get("repair_path")
    if repair_path:
        payload["repair_cmd"] = repair_path.get("run_cmd")
    elif domain.get("status") == "down_for_maintenance":
        payload["repair_cmd"] = None
        payload["terminal_reason"] = "down_for_maintenance"
    return {key: value for key, value in payload.items() if value is not None}


def compact_subdomain(store: dict[str, Any], domain_id: str, subdomain: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": subdomain["id"],
        "kind": subdomain.get("kind", "agent_subdomain"),
        "status": subdomain.get("status", "unknown"),
        "description": selected_description(store, subdomain),
        "aliases": subdomain.get("aliases", []),
        "run_cmd": f"./xctx discover {domain_id}::{subdomain['id']}",
    }
    if subdomain.get("offline_reason"):
        payload["offline_reason"] = subdomain["offline_reason"]
    repair_path = subdomain.get("repair_path")
    if repair_path:
        payload["repair_cmd"] = repair_path.get("run_cmd")
    elif subdomain.get("status") == "down_for_maintenance":
        payload["repair_cmd"] = None
        payload["terminal_reason"] = "down_for_maintenance"
    return {key: value for key, value in payload.items() if value is not None}


def parse_ref(store: dict[str, Any], token: str | None) -> tuple[str | None, str | None]:
    if not token:
        return None, None
    domains = store.get("agent_domains", {})
    if "::" in token:
        domain_id, subdomain_id = token.split("::", 1)
        if not domain_id:
            domain_id = str(store.get("active_agent_domain") or "")
        if domain_id not in domains:
            return None, None
        if not subdomain_id:
            return domain_id, None
        aliases = domains[domain_id].get("_subdomain_aliases", {})
        return domain_id, aliases.get(subdomain_id, subdomain_id)
    if token in domains:
        return token, None
    domain = active_domain(store)
    aliases = domain.get("_subdomain_aliases", {})
    if token in aliases:
        return domain["id"], aliases[token]
    return None, None


def parse_scoped_action(store: dict[str, Any], token: str | None) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Parse <agent_domain>::<domain_affordance> without mistaking the affordance for a subdomain."""
    if not token or "::" not in token:
        return None, None, None
    domain_id, scoped_token = token.split("::", 1)
    if not domain_id or not scoped_token:
        return None, None, None
    if domain_id not in store.get("agent_domains", {}):
        return None, None, None
    action = domain_action_config(store, domain_id, scoped_token)
    if action:
        return domain_id, str(action.get("_action_name", scoped_token)), action
    return None, None, None


def resolve_domain(store: dict[str, Any], domain_id: str) -> dict[str, Any]:
    domain = store.get("agent_domains", {}).get(domain_id)
    if not domain:
        raise XctxError(f"next valid move: choose a known agent_domain ({domain_id})")
    return domain


def resolve_subdomain(store: dict[str, Any], domain_id: str, subdomain_id: str) -> dict[str, Any]:
    domain = resolve_domain(store, domain_id)
    subdomain = domain.get("_subdomains", {}).get(subdomain_id)
    if not subdomain:
        raise XctxError(f"next valid move: choose a known agent_subdomain ({domain_id}::{subdomain_id})")
    return subdomain


def route_for_identifier(store: dict[str, Any], identifier: str) -> tuple[str, str] | tuple[None, None]:
    routing = agent_routing(store)
    lowered = identifier.lower().strip()
    uppered = identifier.upper().strip()
    for route in routing.get("observe_routes", []) or []:
        prefixes = [str(prefix).lower() for prefix in route.get("prefixes", []) or []]
        exact_tokens = {str(token).upper() for token in route.get("unprefixed_exact", []) or []}
        if any(lowered.startswith(prefix) for prefix in prefixes) or uppered in exact_tokens:
            return str(route.get("agent_domain")), str(route.get("agent_subdomain"))
    default_route = routing.get("default_observe_route") or {}
    if default_route.get("agent_domain") and default_route.get("agent_subdomain"):
        return str(default_route["agent_domain"]), str(default_route["agent_subdomain"])
    return None, None


def fallback_discovery_route(store: dict[str, Any]) -> dict[str, Any] | None:
    route = agent_routing(store).get("discovery_fallback") or {}
    if route.get("agent_domain") and route.get("agent_subdomain"):
        return route
    return None


def observe_adapter_option_args(store: dict[str, Any], subdomain: dict[str, Any], options: dict[str, Any]) -> list[str]:
    """Encode observe options only after the concrete subdomain is resolved."""
    action_name, action = subdomain_action_config(subdomain, "observe")
    return encode_cli_options_for_target(
        store,
        subdomain,
        "observe",
        action_name=action_name,
        action=action,
        values=options or {},
    )


def joined_identifier(parts: list[str | None]) -> str | None:
    text = " ".join(str(part) for part in parts if part).strip()
    return text or None


def scoped_action_run_cmd(store: dict[str, Any], action_name: str) -> str:
    active_id = store.get("active_agent_domain")
    domains = store.get("agent_domains", {})
    ordered_domain_ids: list[str] = []
    if active_id and active_id in domains:
        ordered_domain_ids.append(str(active_id))
    ordered_domain_ids.extend(domain_id for domain_id in domains if domain_id not in ordered_domain_ids)
    for domain_id in ordered_domain_ids:
        for name, action in iter_domain_action_configs(store, domain_id):
            if action_matches(name, action, action_name):
                return f"./xctx discover {domain_id}::{name}"
    return ""


def offline_subdomain_payload(store: dict[str, Any], domain_id: str, subdomain: dict[str, Any]) -> dict[str, Any]:
    payload = with_description(store, subdomain)
    payload["agent_domain"] = domain_id
    payload["status"] = subdomain.get("status")
    if subdomain.get("status") == "offline" and subdomain.get("repair_path"):
        payload["repair_cmd"] = subdomain["repair_path"].get("run_cmd")
    if subdomain.get("status") == "down_for_maintenance":
        payload["repair_path"] = None
        payload["terminal_reason"] = "down_for_maintenance"
    return payload


def universe_discovery_payload(store: dict[str, Any]) -> dict[str, Any]:
    universe = store.get("universe", {})
    interface = universe.get("xctx_interface", {})
    domains = store.get("agent_domains", {})
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
        "active_agent_domain": store.get("active_agent_domain"),
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
            "xctx_other": command_map_for_group(store, "xctx_other", "other"),
            "aliases": command_aliases(store),
        },
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
    domain = active_domain(store)
    online_subdomains = [
        subdomain
        for subdomain in sorted(domain.get("_subdomains", {}).values(), key=lambda item: item.get("_priority", 9999))
        if subdomain.get("status") == "online"
    ]
    next_moves = [f"./xctx discover {domain['id']}::"]
    if domain.get("status") != "online" and (domain.get("repair_path") or {}).get("run_cmd"):
        next_moves.append(domain["repair_path"]["run_cmd"])
    next_moves.append("./xctx audit root")
    return {
        "description": selected_description(store, root),
        "active_agent_domain": store.get("active_agent_domain"),
        "agent_domains": [compact_domain(store, domain) for domain in store.get("agent_domains", {}).values()],
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
        payload["repair_cmd"] = domain["repair_path"].get("run_cmd")
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
    subdomain = resolve_subdomain(store, domain_id, subdomain_id)
    if subdomain.get("status") != "online":
        return offline_subdomain_payload(store, domain_id, subdomain)
    if query_parts:
        action_name, action = subdomain_action_config(subdomain, query_parts[0])
        if action_name and action:
            return scoped_subdomain_action_payload(store, domain_id, subdomain, action_name, action, query_parts[1:])
    live = call_external_command(store, subdomain, ["discover", *query_parts])
    payload = {
        "agent_domain": domain_id,
        "agent_subdomain": compact_subdomain(store, domain_id, subdomain),
        "description": selected_description(store, subdomain),
        "configured_actions": subdomain.get("actions", {}),
        "configured_options": target_option_surface(store, subdomain),
        "live_data": live,
    }
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
    validate_declared_collection_args(action, query_parts)
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
    validate_declared_collection_args(action, action_args)
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

    route = fallback_discovery_route(store)
    if route:
        domain_id = str(route["agent_domain"])
        subdomain_id = str(route["agent_subdomain"])
        subdomain = resolve_subdomain(store, domain_id, subdomain_id)
        live_command = str(route.get("entrypoint_command", "discover"))
        live = call_external_command(store, subdomain, [live_command, target, *query_parts])
        return (
            "agent_subdomain",
            {
                "interpretation": route.get("interpretation", "free_text_discovery_routed_to_configured_fallback"),
                "agent_domain": domain_id,
                "agent_subdomain": subdomain_id,
                "live_data": live,
            },
        )
    raise XctxError(f"next valid move: ./xctx discover or ./xctx other --topic {target}")


def observe_payload(
    store: dict[str, Any],
    target: str | None,
    rest: list[str],
    item_id: str | None,
    observe_options: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    rest_identifier = joined_identifier(rest)
    identifier = item_id or rest_identifier
    options = observe_options or {}
    domain_id, subdomain_id = parse_ref(store, target)
    if domain_id and subdomain_id:
        subdomain = resolve_subdomain(store, domain_id, subdomain_id)
        if subdomain.get("status") != "online":
            return "agent_subdomain", offline_subdomain_payload(store, domain_id, subdomain)
        if not identifier:
            if options:
                raise XctxError("next valid move: provide an observation target before configured observe options")
            live = call_external_command(store, subdomain, ["discover"])
        else:
            option_args = observe_adapter_option_args(store, subdomain, options)
            live = call_external_command(store, subdomain, ["observe", identifier, *option_args])
        return "agent_subdomain", {"agent_domain": domain_id, "agent_subdomain": subdomain_id, "live_data": live}
    if domain_id:
        return "agent_domain", domain_discovery_payload(store, domain_id)

    identifier = item_id or joined_identifier([target, *rest])
    if not identifier:
        raise XctxError("next valid move: ./xctx observe <thing> or ./xctx observe <target> --id <id>")
    domain_id, subdomain_id = route_for_identifier(store, identifier)
    if not domain_id or not subdomain_id:
        raise XctxError("next valid move: observe a discovered id with a known prefix")
    subdomain = resolve_subdomain(store, domain_id, subdomain_id)
    if subdomain.get("status") != "online":
        return "agent_subdomain", offline_subdomain_payload(store, domain_id, subdomain)
    option_args = observe_adapter_option_args(store, subdomain, options)
    live = call_external_command(store, subdomain, ["observe", identifier, *option_args])
    return "agent_subdomain", {"agent_domain": domain_id, "agent_subdomain": subdomain_id, "live_data": live}


def availability_findings(store: dict[str, Any], scope: str = "root") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def include_domain(domain_id: str) -> bool:
        if scope in {"root", "all", "*"}:
            return True
        parsed_domain, _parsed_subdomain = parse_ref(store, scope)
        return parsed_domain == domain_id or scope == domain_id

    for domain_id, domain in store.get("agent_domains", {}).items():
        if not include_domain(domain_id):
            continue
        status = domain.get("status")
        if status in {"offline", "down_for_maintenance"}:
            repair_path = domain.get("repair_path")
            findings.append(
                {
                    "id": f"{status}:{domain_id}",
                    "target": domain_id,
                    "target_kind": "agent_domain",
                    "status": status,
                    "severity": "terminal" if status == "down_for_maintenance" else "repairable",
                    "repairable": bool(repair_path),
                    "repair_cmd": repair_path.get("run_cmd") if repair_path else None,
                    "reason": domain.get("offline_reason"),
                }
            )

        parsed_domain, parsed_subdomain = parse_ref(store, scope)
        for subdomain_id, subdomain in domain.get("_subdomains", {}).items():
            if scope not in {"root", "all", "*", domain_id} and not (
                parsed_domain == domain_id and parsed_subdomain in {None, subdomain_id}
            ):
                continue
            subdomain_status = subdomain.get("status")
            if subdomain_status in {"offline", "down_for_maintenance"}:
                repair_path = subdomain.get("repair_path")
                findings.append(
                    {
                        "id": f"{subdomain_status}:{domain_id}::{subdomain_id}",
                        "target": f"{domain_id}::{subdomain_id}",
                        "target_kind": "agent_subdomain",
                        "status": subdomain_status,
                        "severity": "terminal" if subdomain_status == "down_for_maintenance" else "repairable",
                        "repairable": bool(repair_path),
                        "repair_cmd": repair_path.get("run_cmd") if repair_path else None,
                        "reason": subdomain.get("offline_reason"),
                    }
                )
    return findings


def audit_payload(store: dict[str, Any], scope: str) -> dict[str, Any]:
    scope = scope or "root"
    findings = availability_findings(store, scope)
    checks: list[dict[str, Any]] = [
        {
            "id": "audit:xctx:config_loaded",
            "status": "pass",
            "loaded_config_files": [
                as_project_path(store["root"], path) if not isinstance(path, str) else path
                for path in store.get("config_files", [])
            ],
        },
        {
            "id": "audit:xctx:agent_domains_loaded",
            "status": "pass" if store.get("agent_domains") else "fail",
            "agent_domain_count": len(store.get("agent_domains", {})),
        },
    ]
    checks.extend(option_config_checks(store))
    parsed_domain, parsed_subdomain = parse_ref(store, scope)
    if scope in {"root", "all", "*"}:
        domain_ids = list(store.get("agent_domains", {}))
    elif parsed_domain:
        domain_ids = [parsed_domain]
    else:
        domain_ids = []

    for domain_id in domain_ids:
        domain = store["agent_domains"][domain_id]
        subdomain_ids = [parsed_subdomain] if parsed_subdomain else list(domain.get("_subdomains", {}))
        for subdomain_id in [item for item in subdomain_ids if item]:
            subdomain = domain.get("_subdomains", {}).get(subdomain_id)
            if subdomain and subdomain.get("status") == "online" and subdomain.get("entrypoint"):
                live = call_external_command(store, subdomain, ["audit"])
                checks.extend(live.get("checks", []))

    return {
        "scope": scope,
        "summary": {
            "checks": len(checks),
            "findings": len(findings),
            "repairable_findings": sum(1 for finding in findings if finding.get("repairable")),
            "terminal_maintenance_findings": sum(
                1 for finding in findings if finding.get("status") == "down_for_maintenance"
            ),
        },
        "checks": checks,
        "findings": findings,
    }


def target_from_repair_arg(target: str) -> tuple[str, str, str | None]:
    status_prefix = ""
    raw = target
    if ":" in target and target.split(":", 1)[0] in {"offline", "down_for_maintenance"}:
        status_prefix, raw = target.split(":", 1)
    if "::" in raw:
        domain_id, subdomain_id = raw.split("::", 1)
        return status_prefix, domain_id, subdomain_id or None
    return status_prefix, raw, None


def repair_payload(store: dict[str, Any], target: str) -> tuple[bool, dict[str, Any], str | None]:
    if not target:
        raise XctxError("next valid move: ./xctx audit root, then ./xctx repair <finding_id>")
    _status_prefix, domain_id, subdomain_id = target_from_repair_arg(target)
    if domain_id not in store.get("agent_domains", {}):
        raise XctxError(f"next valid move: choose a known repair target ({target})")
    domain = store["agent_domains"][domain_id]
    obj = domain if not subdomain_id else domain.get("_subdomains", {}).get(subdomain_id)
    if not obj:
        raise XctxError(f"next valid move: choose a known repair target ({target})")

    status = obj.get("status")
    repair_path = obj.get("repair_path")
    resolved_target = domain_id if not subdomain_id else f"{domain_id}::{subdomain_id}"
    if status == "down_for_maintenance":
        return (
            False,
            {
                "target": resolved_target,
                "current_status": "down_for_maintenance",
                "repair_path": None,
                "final": True,
                "message": "down for maintenance: no repair path is exposed for this target.",
            },
            "down_for_maintenance",
        )
    if status == "offline":
        if not repair_path:
            return (
                False,
                {
                    "target": resolved_target,
                    "current_status": "offline",
                    "repair_path": None,
                    "final": True,
                    "message": "offline target has no configured repair path.",
                },
                "no_repair_path",
            )
        return (
            True,
            {
                "target": resolved_target,
                "current_status": "offline",
                "repair_path": repair_path,
                "execution_state": "not_applied_read_only_external_adapter_surface",
                "message": "Repair path exposed. xctx describes the repair; domain tools or operators perform real state changes.",
                "next_moves": [f"./xctx plan bring_online {resolved_target}", f"./xctx audit {resolved_target}"],
            },
            None,
        )
    return (
        True,
        {
            "target": resolved_target,
            "current_status": status,
            "repair_path": None,
            "message": "Target is online or repair is unnecessary.",
            "next_move": f"./xctx discover {resolved_target if subdomain_id else resolved_target + '::'}",
        },
        None,
    )


def _receipt_for_payload(payload: dict[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def plan_payload(args: list[str], store: dict[str, Any]) -> dict[str, Any]:
    operation = " ".join(args).strip()
    plan_material = {
        "protocol": "xctx.v4.2",
        "operation": operation or None,
        "surface": "read_only_external_adapter_surface",
        "mutation_policy": "no_state_change_planned",
    }
    receipt = _receipt_for_payload(plan_material)
    plan_id = f"plan:sha256:{receipt}"
    payload = {
        "operation": operation or None,
        "planner_id": receipt,
        "plan_id": plan_id,
        "status": "read_only_surface",
        "decision": "no_state_change_planned",
        "description": "xctx can rehearse the requested operation. This proof-of-concept accepts the receipt at execute time but performs no mutation.",
        "receipt_sha256": receipt,
        "receipt_sha5": receipt[:5],
        "receipt_note": "receipt_sha5 is accepted only when it resolves uniquely to a recorded plan in the local xctx plan ledger; receipt_sha256 is the canonical deterministic receipt.",
        "planner_ledger": ".xctx_runtime/plans",
        "accepted_execute_shape": f"./xctx execute {plan_id} --commit",
        "lawful_next_moves": [
            "./xctx discover",
            "./xctx audit root",
            "./xctx repair <finding_id>",
            f"./xctx execute {plan_id} --commit",
            f"./xctx execute {receipt[:5]} --commit",
        ],
    }
    write_plan(store, payload)
    return payload


def execute_payload(args: list[str], commit: bool, store: dict[str, Any]) -> dict[str, Any]:
    requested_plan = " ".join(args).strip() or None
    if not requested_plan:
        return {
            "ok": False,
            "error": "plan_required",
            "requested_plan": None,
            "commit_requested": commit,
            "status": "refused",
            "description": "Execute requires a plan id or receipt.",
            "next_move": "./xctx plan <operation> <target>",
        }
    if not commit:
        return {
            "ok": False,
            "error": "commit_required",
            "requested_plan": requested_plan,
            "commit_requested": False,
            "status": "refused",
            "description": "Execute requires explicit --commit even for the read-only proof-of-concept acceptance path.",
            "next_move": f"./xctx execute {requested_plan} --commit",
        }
    resolved = resolve_plan(store, requested_plan)
    accepted = resolved.ok
    canonical_plan_id = None
    bound_operation = None
    bound_receipt = None
    if resolved.plan:
        bound_receipt = resolved.plan.get("receipt_sha256")
        canonical_plan_id = resolved.plan.get("plan_id")
        bound_operation = resolved.plan.get("operation")
    return {
        "ok": accepted,
        "error": None if accepted else resolved.error,
        "requested_plan": requested_plan,
        "commit_requested": True,
        "status": "accepted_read_only_noop" if accepted else "refused",
        "description": "Execute accepts only receipts that bind to a recorded xctx plan. No domain mutation was performed because this build exposes only read-only external adapters.",
        "planner_binding": {
            "verified": accepted,
            "requested": requested_plan,
            "canonical_plan_id": canonical_plan_id,
            "receipt_sha256": bound_receipt,
            "operation": bound_operation,
            "short_receipt_matches": resolved.matches,
        },
        "mutations_applied": 0,
        "execution_receipt_sha256": _receipt_for_payload({"execute": requested_plan, "bound_plan": canonical_plan_id, "commit": True, "mutations_applied": 0}),
        "next_move": "./xctx audit root" if accepted else "./xctx plan <operation> <target>",
    }
