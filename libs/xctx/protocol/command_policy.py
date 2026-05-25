"""Command admission policy for the production xctx surface."""

from __future__ import annotations

from typing import Any


VISIBLE_CORE_COMMANDS = frozenset({"discover", "observe", "plan", "execute", "audit", "repair"})
HIDDEN_EXTENSION_COMMANDS = frozenset({"other"})


def command_groups(store: dict[str, Any]) -> dict[str, list[str]]:
    return store["protocol"].get("command_groups", {})


def visible_commands(store: dict[str, Any]) -> set[str]:
    configured = set(command_groups(store).get("main", []))
    return configured & VISIBLE_CORE_COMMANDS


def hidden_commands(store: dict[str, Any]) -> set[str]:
    configured = set(command_groups(store).get("other", []))
    return configured & HIDDEN_EXTENSION_COMMANDS


def canonical_command(store: dict[str, Any], command: str) -> str:
    return command


def accepted_command_names(store: dict[str, Any]) -> set[str]:
    return visible_commands(store) | hidden_commands(store)


def visible_command_names_for_guidance(store: dict[str, Any]) -> set[str]:
    return set(visible_commands(store))
