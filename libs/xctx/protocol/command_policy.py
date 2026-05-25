"""Command admission policy for the production xctx surface.

The public protocol has a deliberately small command set. YAML can declare the
surface, but this module is the fail-closed guardrail: only the six core xctx
commands are visible and only the single ``other`` extension lane is accepted as
hidden/non-discoverable escape hatch.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

VISIBLE_CORE_COMMAND_ORDER = ("discover", "observe", "plan", "execute", "audit", "repair")
HIDDEN_EXTENSION_COMMAND_ORDER = ("other",)
VISIBLE_CORE_COMMANDS = frozenset(VISIBLE_CORE_COMMAND_ORDER)
HIDDEN_EXTENSION_COMMANDS = frozenset(HIDDEN_EXTENSION_COMMAND_ORDER)
VISIBLE_COMMAND_MAP_KEY = "xctx"
HIDDEN_COMMAND_MAP_KEY = "xctx_other"


@dataclass(frozen=True)
class CommandSurface:
    """Resolved command contract for one loaded xctx store."""

    visible: tuple[str, ...]
    hidden: tuple[str, ...]
    rejected_from_main: tuple[str, ...]
    rejected_from_other: tuple[str, ...]
    rejected_command_map_entries: tuple[str, ...]
    duplicate_main_entries: tuple[str, ...]
    duplicate_other_entries: tuple[str, ...]
    missing_visible: tuple[str, ...]
    missing_hidden: tuple[str, ...]

    @property
    def accepted(self) -> set[str]:
        return set(self.visible) | set(self.hidden)

    @property
    def ok(self) -> bool:
        return not (
            self.rejected_from_main
            or self.rejected_from_other
            or self.rejected_command_map_entries
            or self.duplicate_main_entries
            or self.duplicate_other_entries
            or self.missing_visible
            or self.missing_hidden
        )


def command_groups(store: dict[str, Any]) -> dict[str, list[str]]:
    groups = store.get("protocol", {}).get("command_groups", {})
    return groups if isinstance(groups, dict) else {}


def _configured_command_map(store: dict[str, Any], key: str) -> dict[str, Any]:
    configured = store.get("commands", {}).get(key, {})
    return configured if isinstance(configured, dict) else {}


def _raw_group_values(store: dict[str, Any], group_name: str) -> list[str]:
    raw = command_groups(store).get(group_name, [])
    if not isinstance(raw, list):
        return []
    return [str(name) for name in raw or []]


def _duplicates(values: list[str]) -> tuple[str, ...]:
    counts = Counter(values)
    return tuple(sorted(value for value, count in counts.items() if count > 1))


def _ordered_intersection(order: tuple[str, ...], names: set[str]) -> tuple[str, ...]:
    return tuple(name for name in order if name in names)


def resolve_command_surface(store: dict[str, Any]) -> CommandSurface:
    """Resolve the admitted command surface from YAML plus the hard contract."""

    visible_map_names = set(_configured_command_map(store, VISIBLE_COMMAND_MAP_KEY))
    hidden_map_names = set(_configured_command_map(store, HIDDEN_COMMAND_MAP_KEY))
    raw_main = _raw_group_values(store, "main")
    raw_other = _raw_group_values(store, "other")
    main_names = set(raw_main)
    other_names = set(raw_other)

    visible_names = main_names & visible_map_names & VISIBLE_CORE_COMMANDS
    hidden_names = other_names & hidden_map_names & HIDDEN_EXTENSION_COMMANDS

    return CommandSurface(
        visible=_ordered_intersection(VISIBLE_CORE_COMMAND_ORDER, visible_names),
        hidden=_ordered_intersection(HIDDEN_EXTENSION_COMMAND_ORDER, hidden_names),
        rejected_from_main=tuple(sorted(main_names - VISIBLE_CORE_COMMANDS)),
        rejected_from_other=tuple(sorted(other_names - HIDDEN_EXTENSION_COMMANDS)),
        rejected_command_map_entries=tuple(
            sorted((visible_map_names - VISIBLE_CORE_COMMANDS) | (hidden_map_names - HIDDEN_EXTENSION_COMMANDS))
        ),
        duplicate_main_entries=_duplicates(raw_main),
        duplicate_other_entries=_duplicates(raw_other),
        missing_visible=tuple(name for name in VISIBLE_CORE_COMMAND_ORDER if name not in visible_names),
        missing_hidden=tuple(name for name in HIDDEN_EXTENSION_COMMAND_ORDER if name not in hidden_names),
    )


def visible_commands(store: dict[str, Any]) -> set[str]:
    return set(resolve_command_surface(store).visible)


def hidden_commands(store: dict[str, Any]) -> set[str]:
    return set(resolve_command_surface(store).hidden)


def canonical_command(store: dict[str, Any], command: str) -> str:
    # No aliases are canonicalized in v4.2. Keeping this function as the single
    # extension point prevents alias handling from leaking into parsers/handlers.
    return str(command)


def accepted_command_names(store: dict[str, Any]) -> set[str]:
    return resolve_command_surface(store).accepted


def visible_command_names_for_guidance(store: dict[str, Any]) -> set[str]:
    return set(resolve_command_surface(store).visible)


def command_surface_check(store: dict[str, Any]) -> dict[str, Any]:
    """Return an audit check for the public/hidden command contract."""

    surface = resolve_command_surface(store)
    return {
        "id": "audit:xctx:command_surface",
        "status": "pass" if surface.ok else "fail",
        "visible_commands": list(surface.visible),
        "hidden_extension_commands": list(surface.hidden),
        "missing_visible_commands": list(surface.missing_visible),
        "missing_hidden_extension_commands": list(surface.missing_hidden),
        "rejected_main_entries": list(surface.rejected_from_main),
        "rejected_other_entries": list(surface.rejected_from_other),
        "rejected_command_map_entries": list(surface.rejected_command_map_entries),
        "duplicate_main_entries": list(surface.duplicate_main_entries),
        "duplicate_other_entries": list(surface.duplicate_other_entries),
    }
