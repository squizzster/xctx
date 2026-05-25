"""Redaction helpers for bounded process previews and connector errors."""

from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS = (
    re.compile(
        r"(?i)(?P<prefix>(?:api[_-]?key|secret|token|password|passwd|authorization)"
        r"\s*[=:]\s*(?:bearer\s+)?)(?P<secret>[^\s;&]+)"
    ),
    re.compile(r"(?i)(?P<prefix>bearer\s+)(?P<secret>[a-z0-9._~+/=-]+)"),
)
SECRET_KEY_PATTERN = re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|authorization)")


def redact_preview(value: Any, limit: int = 500) -> str:
    """Return a bounded text preview with common credential shapes masked."""

    preview = str(value)[:limit]
    for pattern in SECRET_PATTERNS:
        preview = pattern.sub(lambda match: f"{match.group('prefix')}<redacted>", preview)
    return preview


def redact_value(value: Any, limit: int = 500) -> Any:
    """Recursively redact common credential shapes in protocol-facing values."""

    if isinstance(value, str):
        return redact_preview(value, limit=limit)
    if isinstance(value, list):
        return [redact_value(item, limit=limit) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item, limit=limit) for item in value]
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and SECRET_KEY_PATTERN.search(key):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_value(item, limit=limit)
        return redacted
    return value
