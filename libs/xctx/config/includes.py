"""Config include helpers."""

from __future__ import annotations

from typing import Any

from xctx.errors import XctxError


def require_config(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise XctxError(f"missing required config key {key} in {context}")
    return mapping[key]
