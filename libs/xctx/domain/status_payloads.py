"""Status and help payload builders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xctx.config.paths import as_project_path
from xctx.protocol.accessors import command_map_for_group, run_cmd_key, protocol_version, response_template
from xctx.protocol.descriptions import selected_description


def normalize_status(value: str) -> str:
    return str(value).strip().lower()


def build_status_payload(store: dict[str, Any]) -> dict[str, Any]:
    system = store["system"]
    template = response_template(store, "status")
    checks = store["status_checks"]
    overall = "pass"
    if any(normalize_status(check.get("status", "")) == "fail" for check in checks):
        overall = "fail"
    elif any(normalize_status(check.get("status", "")) == "warn" for check in checks):
        overall = "warn"

    root: Path = store["root"]
    run_key = run_cmd_key(store)
    payload = {
        template.get("version_key", "version_xctx"): protocol_version(store),
        template.get("system_key", "top_level_system_name"): {
            "name": system["name"],
            "id": system["id"],
            "desc": system["desc"],
        },
        template.get("protocol_key", "protocol_xctx"): {"version": protocol_version(store)},
        template.get("source_data_key", "source_data"): system.get("source_data", {}),
        template.get("available_systems_key", "available_systems"): [
            {
                "id": item.get("id"),
                "name": item.get("name", item.get("id")),
                "desc": item.get("desc", ""),
                "active": item.get("id") == store.get("active_system"),
                run_key: f"./xctx discover {item.get('id')}::",
            }
            for item in store.get("all_systems", [])
        ],
        template.get("subsystems_key", "subsystems"): [
            {"id": subsystem["id"], "name": subsystem["name"], "desc": subsystem["desc"]}
            for subsystem in store["subsystems"]
        ],
        template.get("checks_key", "status_check_list"): checks,
        template.get("overall_status_key", "overall_status"): overall,
        template.get("config_files_key", "loaded_config_files"): [
            as_project_path(root, path) for path in store.get("config_files", [])
        ],
    }
    if store["subsystems"]:
        first_subsystem = store["subsystems"][0]
        payload[template.get("active_subsystem_key", "this_sub_system_name")] = {
            "name": first_subsystem["name"],
            "id": first_subsystem["id"],
            "desc": first_subsystem["desc"],
        }
    return payload


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
