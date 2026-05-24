"""Accessors for configurable xctx protocol keys and aliases."""

from __future__ import annotations

from typing import Any

from xctx.protocol.command_policy import (
    accepted_command_names,
    advertised_aliases,
    canonical_command,
    command_aliases,
    command_groups,
    hidden_commands,
    visible_commands,
)
from xctx.protocol.formatting import format_cmd


def protocol_version(store: dict[str, Any]) -> str:
    return str(store["protocol"].get("version_xctx", store["universe"].get("version_xctx", "")))


def envelope_keys(store: dict[str, Any]) -> dict[str, str]:
    return store["protocol"].get("stdout", {}).get("envelope_keys", {})


def key_for(store: dict[str, Any], logical_key: str, default: str | None = None) -> str | None:
    return envelope_keys(store).get(logical_key, default)


def run_cmd_key(store: dict[str, Any]) -> str:
    return store["protocol"].get("hint_keys", {}).get("run_command", "run_cmd")


def active_system_id(store: dict[str, Any]) -> str:
    return str(store.get("active_system") or store.get("system", {}).get("id", "")).strip()


def command_prefix(store: dict[str, Any]) -> str:
    system_id = active_system_id(store)
    return f"./xctx --system {system_id}" if system_id else "./xctx"


def scope_run_cmd(store: dict[str, Any], command: str) -> str:
    """Return an xctx command hint pinned to the active top-level system."""
    command = str(command).strip()
    if not command:
        return command

    parts = command.split()
    executable = parts[0]
    if executable not in {"xctx", "./xctx"}:
        return command
    if "--system" in parts:
        return "./" + command if executable == "xctx" else command

    system_id = active_system_id(store)
    scoped_parts = ["./xctx"]
    if system_id:
        scoped_parts.extend(["--system", system_id])
    scoped_parts.extend(parts[1:])
    return " ".join(scoped_parts)


def format_run_cmd(store: dict[str, Any], template: str, **context: Any) -> str:
    return scope_run_cmd(store, format_cmd(template, **context))


def response_template(store: dict[str, Any], name: str) -> dict[str, Any]:
    return store["protocol"].get("response_templates", {}).get(name, {})


def guidance_cmd(store: dict[str, Any], name: str, **context: Any) -> str:
    template = store["protocol"].get("guidance", {}).get(name, "")
    if not template:
        return ""
    return format_run_cmd(store, template, **context)


def help_aliases(store: dict[str, Any]) -> set[str]:
    return set(store["protocol"].get("help_aliases", []))


def command_map_for_group(store: dict[str, Any], map_key: str, group_name: str) -> dict[str, Any]:
    configured = store["commands"].get(map_key, {})
    group = command_groups(store).get(group_name, list(configured.keys()))
    if group_name == "main":
        group = [name for name in group if name in visible_commands(store)]
    elif group_name == "other":
        group = [name for name in group if name in hidden_commands(store)]
    return {name: configured[name] for name in group if name in configured}


def configured_command_names(store: dict[str, Any]) -> set[str]:
    return accepted_command_names(store)


def advertised_command_aliases(store: dict[str, Any]) -> dict[str, list[str]]:
    return advertised_aliases(store)
