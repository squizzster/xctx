"""YAML file IO helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from xctx.errors import XctxError


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from *path* or raise a protocol-guidance error."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise XctxError(f"next valid move: create or inspect YAML file {path}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise XctxError(f"next valid move: inspect YAML mapping at {path}")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write a YAML mapping while preserving human-editable order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=False, width=88)
