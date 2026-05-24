"""Command admission policy for the production xctx surface."""

from __future__ import annotations

from typing import Any


VISIBLE_CORE_COMMANDS = frozenset({"discover", "observe", "plan", "execute", "audit", "repair"})
HIDDEN_EXTENSION_COMMANDS = frozenset({"other"})
DEV_ONLY_COMMANDS = frozenset({"status", "identify", "doctor", "write"})


def command_groups(store: dict[str, Any]) -> dict[str, list[str]]:
    return store["protocol"].get("command_groups", {})


def command_aliases(store: dict[str, Any]) -> dict[str, list[str]]:
    return store["protocol"].get("command_aliases", {})


def visible_commands(store: dict[str, Any]) -> set[str]:
    configured = set(command_groups(store).get("main", []))
    return configured & VISIBLE_CORE_COMMANDS


def hidden_commands(store: dict[str, Any]) -> set[str]:
    configured = set(command_groups(store).get("other", []))
    return configured & HIDDEN_EXTENSION_COMMANDS


def canonical_command(store: dict[str, Any], command: str) -> str:
    for canonical, aliases in command_aliases(store).items():
        if command == canonical or command in aliases:
            return canonical
    return command


def accepted_command_names(store: dict[str, Any]) -> set[str]:
    names = visible_commands(store) | hidden_commands(store)
    for canonical, aliases in command_aliases(store).items():
        if canonical in names:
            names.update(aliases)
    return names


def visible_command_names_for_guidance(store: dict[str, Any]) -> set[str]:
    names = set(visible_commands(store))
    for canonical, aliases in command_aliases(store).items():
        if canonical in names:
            names.update(aliases)
    return names


def advertised_aliases(store: dict[str, Any]) -> dict[str, list[str]]:
    visible = visible_commands(store)
    return {canonical: list(aliases) for canonical, aliases in command_aliases(store).items() if canonical in visible}
