"""Shared subprocess boundary limits for xctx framework and connectors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ConnectorLimits:
    timeout_seconds: float
    max_output_bytes: int

    @classmethod
    def from_values(
        cls,
        *,
        timeout_seconds: Any = 30,
        max_output_bytes: Any = DEFAULT_MAX_OUTPUT_BYTES,
        timeout_label: str = "timeout_seconds",
        max_output_label: str = "max_output_bytes",
        error_type: type[Exception] = ValueError,
    ) -> "ConnectorLimits":
        return cls(
            timeout_seconds=validated_timeout(timeout_seconds, label=timeout_label, error_type=error_type),
            max_output_bytes=validated_max_output_bytes(
                max_output_bytes,
                label=max_output_label,
                error_type=error_type,
            ),
        )

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | None,
        *,
        default_timeout_seconds: Any = 30,
        default_max_output_bytes: Any = DEFAULT_MAX_OUTPUT_BYTES,
        label_prefix: str = "connector",
        error_type: type[Exception] = ValueError,
    ) -> "ConnectorLimits":
        source = config or {}
        return cls.from_values(
            timeout_seconds=source.get("timeout_seconds", default_timeout_seconds),
            max_output_bytes=source.get("max_output_bytes", default_max_output_bytes),
            timeout_label=f"{label_prefix}.timeout_seconds" if label_prefix else "timeout_seconds",
            max_output_label=f"{label_prefix}.max_output_bytes" if label_prefix else "max_output_bytes",
            error_type=error_type,
        )
