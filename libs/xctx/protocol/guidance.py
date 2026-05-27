"""Canonical command-guidance shapes for xctx payloads."""

from __future__ import annotations

from typing import Any

COMMAND_HINT_LIST_KEYS = frozenset({"next_moves", "lawful_next_moves"})


def command_hint(run_cmd: str, desc: str | None = None, **extra: Any) -> dict[str, Any]:
    """Return the canonical xctx command-hint object."""

    hint: dict[str, Any] = {}
    if desc:
        hint["desc"] = str(desc)
    hint["run_cmd"] = str(run_cmd)
    for key, value in extra.items():
        if key not in {"desc", "run_cmd"} and value is not None:
            hint[key] = value
    return hint


def _normalize_command_hint(value: Any) -> Any:
    if isinstance(value, str):
        return command_hint(value)
    if not isinstance(value, dict):
        return normalize_guidance(value)
    normalized = normalize_guidance(value)
    if not isinstance(normalized, dict) or "run_cmd" not in normalized:
        return normalized
    return command_hint(
        str(normalized["run_cmd"]),
        None if normalized.get("desc") is None else str(normalized["desc"]),
        **{key: item for key, item in normalized.items() if key not in {"desc", "run_cmd"}},
    )


def command_hints(values: list[Any] | tuple[Any, ...]) -> list[Any]:
    """Normalize a command-hint list without mutating the caller's objects."""

    return [_normalize_command_hint(value) for value in values]


def normalize_guidance(value: Any) -> Any:
    """Recursively enforce canonical command-hint list shapes.

    Generic xctx output must not alternate between raw command strings and
    objects for the same semantic field. This normalizer is intentionally
    narrow: it only rewrites fields that are command-hint lists.
    """

    if isinstance(value, list):
        return [normalize_guidance(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if key in COMMAND_HINT_LIST_KEYS and isinstance(item, list):
            normalized[key] = command_hints(item)
        else:
            normalized[key] = normalize_guidance(item)
    return normalized


def root_protocol_next_moves(store: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the canonical root/universe navigation commands."""

    universe = store.get("universe", {})
    interface = universe.get("xctx_interface", {})
    root = universe.get("root", {})
    guidance = root.get("next_move_guidance") or {}
    return [
        command_hint(
            str(interface.get("discover_domains_run_cmd", "./xctx discover")),
            "Discover configured agent domains in this universe.",
        ),
        command_hint(
            str(guidance.get("audit_root_run_cmd", "./xctx audit root")),
            "Audit loaded configuration, live adapters, and offline/maintenance findings.",
        ),
    ]
