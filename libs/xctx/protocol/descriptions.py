"""Description projection helpers for xctx protocol payloads."""

from __future__ import annotations

from typing import Any


def detail_enabled(store: dict[str, Any]) -> bool:
    return bool(store.get("detail"))


def selected_description(store: dict[str, Any], mapping: dict[str, Any]) -> str:
    if detail_enabled(store):
        return str(
            mapping.get("full_description")
            or mapping.get("description")
            or mapping.get("basic_description")
            or mapping.get("desc")
            or ""
        )
    return str(
        mapping.get("basic_description")
        or mapping.get("description")
        or mapping.get("desc")
        or mapping.get("full_description")
        or ""
    )


def strip_description_variants(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_description_variants(child)
            for key, child in value.items()
            if key not in {"basic_description", "full_description"}
        }
    if isinstance(value, list):
        return [strip_description_variants(child) for child in value]
    return value


def with_description(store: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    payload = strip_description_variants({key: value for key, value in mapping.items() if not key.startswith("_")})
    if not detail_enabled(store):
        payload.pop("data_description", None)
    description = selected_description(store, mapping)
    if description:
        payload["description"] = description
    return payload
