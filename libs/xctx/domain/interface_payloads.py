"""Help and version payload builders for the xctx interface."""

from __future__ import annotations

from typing import Any

from xctx.protocol.accessors import command_map_for_group, protocol_version, response_template
from xctx.protocol.descriptions import selected_description


def build_help_payload(store: dict[str, Any]) -> dict[str, Any]:
    template = response_template(store, "help")
    return {
        template.get("version_key", "version_xctx"): protocol_version(store),
        template.get("main_commands_key", "xctx"): command_map_for_group(store, "xctx", "main"),
    }


def build_version_payload(store: dict[str, Any]) -> dict[str, Any]:
    universe = store.get("universe", {})
    interface = universe.get("xctx_interface", {})
    return {
        "id": interface.get("id", "xctx"),
        "kind": interface.get("kind", "executable_context_protocol"),
        "name": interface.get("name", "xctx"),
        "version_xctx": protocol_version(store),
        "description": selected_description(store, interface),
        "run_cmd": interface.get("run_cmd", "./xctx"),
        "discover_domains_run_cmd": interface.get("discover_domains_run_cmd", "./xctx discover"),
        "help_run_cmd": interface.get("help_run_cmd", "./xctx help"),
        "command_surface": {
            "xctx": command_map_for_group(store, "xctx", "main"),
        },
    }
