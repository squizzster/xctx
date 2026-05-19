"""Safe formatting helpers for protocol run-command hints."""

from __future__ import annotations

from typing import Any


def format_cmd(template: str, **context: Any) -> str:
    """Format a command template with a tolerant context."""
    return template.format(**context)
