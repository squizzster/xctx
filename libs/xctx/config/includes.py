"""Config normalization and include helpers."""

from __future__ import annotations

from typing import Any

from xctx.errors import XctxError


def require_config(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise XctxError(f"next valid move: add {key} to {context}")
    return mapping[key]


def normalize_data_spec(name: str, raw_spec: Any) -> dict[str, Any]:
    if isinstance(raw_spec, str):
        return {"path": raw_spec, "root_key": name, "kind": "resource"}
    if isinstance(raw_spec, dict):
        spec = dict(raw_spec)
        spec.setdefault("root_key", name)
        spec.setdefault("kind", "resource")
        return spec
    raise XctxError(f"next valid move: inspect data config for collection {name}")


def normalize_subsystem_refs(raw_refs: Any) -> list[dict[str, Any]]:
    if isinstance(raw_refs, list):
        return [dict(item) if isinstance(item, dict) else {"path": str(item)} for item in raw_refs]
    if isinstance(raw_refs, dict):
        refs: list[dict[str, Any]] = []
        for subsystem_id, raw_ref in raw_refs.items():
            if isinstance(raw_ref, str):
                refs.append({"id": subsystem_id, "path": raw_ref})
            elif isinstance(raw_ref, dict):
                ref = dict(raw_ref)
                ref.setdefault("id", subsystem_id)
                refs.append(ref)
            else:
                raise XctxError(f"next valid move: inspect subsystem registry entry {subsystem_id}")
        return refs
    raise XctxError("next valid move: inspect subsystem registry")
