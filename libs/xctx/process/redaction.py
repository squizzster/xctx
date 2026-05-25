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


def redact_preview(value: Any, limit: int = 500) -> str:
    """Return a bounded text preview with common credential shapes masked."""

    preview = str(value)[:limit]
    for pattern in SECRET_PATTERNS:
        preview = pattern.sub(lambda match: f"{match.group('prefix')}<redacted>", preview)
    return preview
