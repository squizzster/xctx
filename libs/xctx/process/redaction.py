"""Redaction helpers for protocol-facing text, argv, and nested payloads."""

from __future__ import annotations

import re
import shlex
from typing import Any

SECRET_TEXT_NAME_PATTERN = (
    r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|private[_-]?key|credentials?|secret|token|password|passwd|authorization)"
)
SECRET_PATTERNS = (
    re.compile(
        rf"(?i)(?P<prefix>(?:-{{1,2}}{SECRET_TEXT_NAME_PATTERN})"
        r"(?:=|\s+)(?:bearer\s+)?)(?P<secret>[^\s;&]+)"
    ),
    re.compile(
        rf"(?i)(?P<prefix>(?<![A-Za-z0-9_-]){SECRET_TEXT_NAME_PATTERN}"
        r"\s*[=:]\s*(?:bearer\s+)?)(?P<secret>[^\s;&]+)"
    ),
    re.compile(r"(?i)(?P<prefix>bearer\s+)(?P<secret>[a-z0-9._~+/=-]+)"),
)
SECRET_ARG_NAMES = frozenset(
    {
        "access-token",
        "access_token",
        "api-key",
        "api_key",
        "apikey",
        "authorization",
        "auth-token",
        "auth_token",
        "bearer-token",
        "bearer_token",
        "client-secret",
        "client_secret",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private-key",
        "private_key",
        "refresh-token",
        "refresh_token",
        "secret",
        "secret-key",
        "secret_key",
        "token",
    }
)
NORMALIZED_SECRET_NAMES = frozenset(name.replace("_", "-") for name in SECRET_ARG_NAMES)


def _normalise_secret_name(value: str) -> str:
    return value.strip().lower().lstrip("-").replace("_", "-")


def is_secret_argument_name(value: str) -> bool:
    """Return true when a CLI option name conventionally carries a secret."""

    normalized = _normalise_secret_name(value)
    return normalized in NORMALIZED_SECRET_NAMES


def is_secret_key(value: str) -> bool:
    """Return true for exact secret-bearing mapping keys.

    This intentionally avoids broad substring matching so protocol fields such as
    ``operation_token`` keep their non-secret value.
    """

    normalized = value.strip().lower().replace("_", "-")
    return normalized in NORMALIZED_SECRET_NAMES


def redact_argv_values(argv: list[Any] | tuple[Any, ...]) -> list[Any]:
    """Redact argv-style secret values while preserving argument shape."""

    redacted: list[Any] = []
    redact_next = False
    for raw in argv:
        if not isinstance(raw, str):
            redacted.append(redact_value(raw))
            redact_next = False
            continue
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if raw.startswith("-") and "=" in raw:
            name, _value = raw.split("=", 1)
            if is_secret_argument_name(name):
                redacted.append(f"{name}=<redacted>")
                continue
        if raw.startswith("-") and is_secret_argument_name(raw):
            redacted.append(raw)
            redact_next = True
            continue
        redacted.append(redact_preview(raw))
    return redacted


def redact_argv(argv: list[Any] | tuple[Any, ...]) -> str:
    """Return a shell-display argv string with secret values masked."""

    return shlex.join(str(item) for item in redact_argv_values(argv))


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
        if all(isinstance(item, str) for item in value):
            return [redact_preview(str(item), limit=limit) for item in redact_argv_values(value)]
        return [redact_value(item, limit=limit) for item in value]
    if isinstance(value, tuple):
        if all(isinstance(item, str) for item in value):
            return [redact_preview(str(item), limit=limit) for item in redact_argv_values(value)]
        return [redact_value(item, limit=limit) for item in value]
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and is_secret_key(key):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_value(item, limit=limit)
        return redacted
    return value
