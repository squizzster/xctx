"""Protocol-wide output detail controls.

``detail_level`` is owned by the xctx framework envelope. It controls protocol
verbosity, guidance, and diagnostics. It never controls domain data projection,
pagination, output format, permissions, or commit boundaries.
"""

from __future__ import annotations

import shlex
from typing import Any, Sequence

from xctx.errors import XctxError

DETAIL_LEVELS: tuple[str, str, str] = ("basic", "more", "max")
DETAIL_FLAGS: dict[str, str] = {"--basic": "basic", "--more": "more", "--max": "max"}
DEFAULT_DETAIL_LEVEL = "basic"
ORIENTATION_DETAIL_LEVEL = "more"


def validate_detail_level(value: Any) -> str:
    level = str(value or "").strip().lower()
    if level not in DETAIL_LEVELS:
        raise XctxError(f"unsupported detail_level: {value} (allowed: {'|'.join(DETAIL_LEVELS)})")
    return level


def detail_level(store: dict[str, Any]) -> str:
    value = store.get("detail_level", DEFAULT_DETAIL_LEVEL)
    try:
        return validate_detail_level(value)
    except XctxError:
        return DEFAULT_DETAIL_LEVEL


def is_basic(store: dict[str, Any]) -> bool:
    return detail_level(store) == "basic"


def is_more(store: dict[str, Any]) -> bool:
    return detail_level(store) == "more"


def is_max(store: dict[str, Any]) -> bool:
    return detail_level(store) == "max"


def is_more_or_max(store: dict[str, Any]) -> bool:
    return detail_level(store) in {"more", "max"}


def diagnostics_allowed(store: dict[str, Any]) -> bool:
    return is_max(store)


def detail_at_least(store: dict[str, Any], minimum: str) -> bool:
    minimum = validate_detail_level(minimum)
    order = {level: index for index, level in enumerate(DETAIL_LEVELS)}
    return order[detail_level(store)] >= order[minimum]


# Compatibility inside the refactor only: this is the desired semantic name used
# by some callers. It is not a public CLI/API compatibility surface.
at_least_more = is_more_or_max


def _configured_discover_names(store: dict[str, Any]) -> set[str]:
    configured = store.get("commands", {}).get("xctx", {}) or {}
    names = {"discover"}
    for name, spec in configured.items():
        if name == "discover" or str(spec.get("canonical") or "") == "discover":
            names.add(str(name))
    return names


def default_detail_level(store: dict[str, Any], argv: Sequence[str]) -> str:
    """Choose the framework default for a normalized command invocation."""

    if not argv:
        return ORIENTATION_DETAIL_LEVEL
    first = str(argv[0])
    if first in {"--version", "-V"}:
        return ORIENTATION_DETAIL_LEVEL
    if first in _configured_discover_names(store) and len(argv) == 1:
        return ORIENTATION_DETAIL_LEVEL
    return DEFAULT_DETAIL_LEVEL


def select_detail_level(store: dict[str, Any], argv: Sequence[str], explicit: str | None) -> str:
    return validate_detail_level(explicit) if explicit else default_detail_level(store, argv)


def with_detail_level(store: dict[str, Any], explicit: str | None, argv: Sequence[str]) -> dict[str, Any]:
    """Set and return the selected detail level on a store-like mapping."""

    store["detail_level"] = select_detail_level(store, argv, explicit)
    return store


def _strip_detail_tokens(parts: list[str]) -> list[str]:
    cleaned: list[str] = []
    index = 0
    while index < len(parts):
        token = parts[index]
        if token in DETAIL_FLAGS:
            index += 1
            continue
        if token == "--detail-level":
            index += 2
            continue
        cleaned.append(token)
        index += 1
    return cleaned


def _normalise_command_parts(cmdline_arg: str | None) -> list[str]:
    raw = str(cmdline_arg or "").strip()
    if not raw or raw == "xctx":
        return ["./xctx"]
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    if not parts:
        return ["./xctx"]
    if parts[0] == "xctx":
        parts[0] = "./xctx"
    elif parts[0] != "./xctx":
        parts.insert(0, "./xctx")
    return _strip_detail_tokens(parts)


def command_with_detail(cmdline_arg: str | None, level: str) -> str:
    level = validate_detail_level(level)
    parts = _normalise_command_parts(cmdline_arg)
    if not parts:
        parts = ["./xctx"]
    return shlex.join([parts[0], f"--{level}", *parts[1:]])


def detail_controls(store: dict[str, Any], cmdline_arg: str | None = None) -> dict[str, Any]:
    current = detail_level(store)
    return {
        "current": current,
        "available": [
            {"level": level, "run_cmd": command_with_detail(cmdline_arg, level)}
            for level in DETAIL_LEVELS
            if level != current
        ],
        "rule": "detail_level controls protocol guidance and diagnostics; projection controls domain result density.",
    }


def detail_hint(
    store: dict[str, Any],
    cmdline_arg: str | None = None,
    *,
    omitted: list[str] | tuple[str, ...] | None = None,
    max_only: bool = False,
) -> dict[str, Any]:
    current = detail_level(store)
    hint: dict[str, Any] = {}
    if omitted:
        hint["omitted"] = list(omitted)
    if not max_only and current == "basic":
        hint["more"] = command_with_detail(cmdline_arg, "more")
    if current != "max":
        hint["max"] = command_with_detail(cmdline_arg, "max")
    return hint


def orientation_surface(record_type: str, domain_level: str | None, command: str | None = None) -> bool:
    if record_type == "version":
        return True
    if record_type == "discovery" and domain_level in {"universe", "root"}:
        return True
    return False
