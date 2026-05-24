"""Help and version payload builders for the xctx interface."""

from __future__ import annotations

from typing import Any

from xctx.protocol.accessors import command_map_for_group, protocol_version, response_template
from xctx.protocol.descriptions import selected_description


def build_help_payload(store: dict[str, Any]) -> dict[str, Any]:
    template = response_template(store, "help")
    active_agent_domain_id = store.get("active_agent_domain")
    active_agent_domain = store.get("agent_domains", {}).get(active_agent_domain_id, {})
    if active_agent_domain:
        identity = {
            "id": active_agent_domain.get("id"),
            "kind": active_agent_domain.get("kind", "agent_domain"),
            "status": active_agent_domain.get("status"),
            "description": selected_description(store, active_agent_domain),
        }
    else:
        system = store["system"]
        identity = {"name": system["name"], "desc": system["desc"]}
    return {
        template.get("version_key", "version_xctx"): protocol_version(store),
        template.get("system_key", "active_agent_domain"): identity,
        template.get("main_commands_key", "xctx"): command_map_for_group(store, "xctx", "main"),
    }


def build_version_payload(store: dict[str, Any]) -> dict[str, Any]:
    universe = store.get("universe", {})
    interface = universe.get("xctx_interface", {})
    active_agent_domain_id = store.get("active_agent_domain")
    active_agent_domain = store.get("agent_domains", {}).get(active_agent_domain_id, {})
    return {
        "id": interface.get("id", "xctx"),
        "kind": interface.get("kind", "executable_context_protocol"),
        "name": interface.get("name", "xctx"),
        "version_xctx": protocol_version(store),
        "description": selected_description(store, interface),
        "run_cmd": interface.get("run_cmd", "./xctx"),
        "discover_domains_run_cmd": interface.get("discover_domains_run_cmd", "./xctx discover"),
        "help_run_cmd": interface.get("help_run_cmd", "./xctx help"),
        "active_agent_domain": {
            "id": active_agent_domain.get("id", active_agent_domain_id),
            "kind": active_agent_domain.get("kind", "agent_domain"),
            "status": active_agent_domain.get("status"),
            "description": selected_description(store, active_agent_domain) if active_agent_domain else None,
        },
        "command_surface": {
            "xctx": command_map_for_group(store, "xctx", "main"),
        },
    }
