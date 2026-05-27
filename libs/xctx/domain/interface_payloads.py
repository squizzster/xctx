"""Help and version payload builders for the xctx interface."""

from __future__ import annotations

from typing import Any

from xctx.protocol.accessors import command_map_for_group, protocol_version, response_template
from xctx.protocol.descriptions import selected_description
from xctx.protocol.detail import at_least_more, detail_controls, is_max


def _record_types(store: dict[str, Any]) -> dict[str, Any]:
    return store.get("protocol", {}).get("record_types", {}) or {}


def _detail_policy() -> dict[str, Any]:
    return {
        "levels": ["basic", "more", "max"],
        "default_rule": {
            "naked_orientation_surfaces": "more",
            "scoped_and_named_surfaces": "basic",
        },
        "separation": "detail_level controls protocol guidance/diagnostics; projection controls domain result density.",
    }


def build_help_payload(store: dict[str, Any]) -> dict[str, Any]:
    template = response_template(store, "help")
    payload: dict[str, Any] = {
        template.get("version_key", "version_xctx"): protocol_version(store),
        template.get("main_commands_key", "xctx"): command_map_for_group(store, "xctx", "main"),
        "detail_controls": detail_controls(store, "./xctx help"),
    }
    if at_least_more(store):
        payload["record_types"] = sorted(_record_types(store).keys())
        payload["detail_policy"] = _detail_policy()
    if is_max(store):
        payload["record_type_descriptions"] = _record_types(store)
        payload["stdout"] = store.get("protocol", {}).get("stdout", {})
        payload["stderr"] = store.get("protocol", {}).get("stderr", {})
    return payload


def build_version_payload(store: dict[str, Any]) -> dict[str, Any]:
    universe = store.get("universe", {})
    interface = universe.get("xctx_interface", {})
    payload: dict[str, Any] = {
        "id": interface.get("id", "xctx"),
        "kind": interface.get("kind", "executable_context_protocol"),
        "name": interface.get("name", "xctx"),
        "version_xctx": protocol_version(store),
        "description": selected_description(store, interface),
        "run_cmd": interface.get("run_cmd", "./xctx"),
        "discover_domains_run_cmd": interface.get("discover_domains_run_cmd", "./xctx discover"),
        "help_run_cmd": interface.get("help_run_cmd", "./xctx help"),
        "detail_controls": detail_controls(store, "./xctx --version"),
    }
    if at_least_more(store):
        payload["command_surface"] = {"xctx": command_map_for_group(store, "xctx", "main")}
        payload["record_types"] = sorted(_record_types(store).keys())
        payload["detail_policy"] = _detail_policy()
    if is_max(store):
        payload["protocol_metadata"] = {
            "record_type_descriptions": _record_types(store),
            "stdout": store.get("protocol", {}).get("stdout", {}),
            "stderr": store.get("protocol", {}).get("stderr", {}),
        }
    return payload
