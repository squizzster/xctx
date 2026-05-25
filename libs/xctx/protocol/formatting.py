"""Safe formatting helpers for protocol run-command hints."""

from __future__ import annotations

from typing import Any


class _SafeFormatDict(dict[str, Any]):
    """Mapping that leaves unknown named fields visible instead of failing."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def format_cmd(template: str, **context: Any) -> str:
    """Format a command template with a tolerant context.

    Protocol YAML may include guidance templates shared across scopes. A missing
    optional placeholder should not crash discovery/observation; preserving the
    token keeps the guidance inspectable while allowing known context to render.
    """
    try:
        return template.format_map(_SafeFormatDict(context))
    except (IndexError, KeyError, ValueError):
        return template
