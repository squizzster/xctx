"""Shared subprocess boundary limits for xctx framework and connectors."""

from __future__ import annotations

from typing import Any

MIN_TIMEOUT_SECONDS = 0.05
MAX_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_OUTPUT_BYTES = 65536
MAX_CAPTURE_BYTES = 1048576


def validated_timeout(
    value: Any,
    *,
    label: str = "timeout_seconds",
    error_type: type[Exception] = ValueError,
) -> float:
    """Validate a user/config supplied timeout and return seconds as float."""
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise error_type(f"{label} must be a number") from exc
    if timeout != timeout or timeout < MIN_TIMEOUT_SECONDS or timeout > MAX_TIMEOUT_SECONDS:
        raise error_type(f"{label} must be between {MIN_TIMEOUT_SECONDS:g} and {MAX_TIMEOUT_SECONDS:g}")
    return timeout


def validated_max_output_bytes(
    value: Any,
    *,
    label: str = "max_output_bytes",
    error_type: type[Exception] = ValueError,
) -> int:
    """Validate a bounded stdout/stderr capture size."""
    try:
        max_bytes = int(value)
    except (TypeError, ValueError) as exc:
        raise error_type(f"{label} must be an integer") from exc
    if max_bytes < 1024 or max_bytes > MAX_CAPTURE_BYTES:
        raise error_type(f"{label} must be between 1024 and {MAX_CAPTURE_BYTES}")
    return max_bytes
