"""Record and collection resolution helpers."""

from __future__ import annotations

from typing import Any

from xctx.errors import XctxError
from xctx.protocol.accessors import guidance_cmd


def resolve_collection(
    store: dict[str, Any],
    name: str,
    subsystem_id: str | None = None,
) -> dict[str, Any]:
    if name in store["collections"]:
        return store["collections"][name]
    if subsystem_id:
        scoped_name = f"{subsystem_id}.{name}"
        if scoped_name in store["collections"]:
            return store["collections"][scoped_name]
    aliases = store["collection_aliases"].get(name, [])
    if len(aliases) == 1:
        return store["collections"][aliases[0]]
    if aliases and subsystem_id:
        for collection_id in aliases:
            collection = store["collections"][collection_id]
            if collection["subsystem_id"] == subsystem_id:
                return collection
    guidance = guidance_cmd(store, "discover_root_run_cmd")
    raise XctxError(f"next valid move: {guidance}" if guidance else "next valid move: discover")


def collection_records(
    store: dict[str, Any],
    name: str,
    subsystem_id: str | None = None,
) -> list[dict[str, Any]]:
    return resolve_collection(store, name, subsystem_id)["records"]


def find_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((item for item in items if str(item.get("id", "")) == str(item_id)), None)


def subsystem_by_id(store: dict[str, Any], subsystem_id: str) -> dict[str, Any] | None:
    return store.get("subsystems_by_id", {}).get(subsystem_id)


def record_lookup_id(collection: dict[str, Any], record: dict[str, Any]) -> Any:
    spec = collection["spec"]
    return record.get(spec.get("identity_id_field", "id"), record.get("id"))


def record_source_id(collection: dict[str, Any], record: dict[str, Any]) -> Any:
    spec = collection["spec"]
    return record.get(spec.get("source_id_field", "id"), record.get("id"))


def find_record_by_configured_id(collection: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for record in collection["records"]:
        candidates = {str(record.get("id", "")), str(record_lookup_id(collection, record))}
        if str(item_id) in candidates:
            return record
    return None


def find_collection_record(
    store: dict[str, Any],
    item_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for collection in store["collections"].values():
        match = find_record_by_configured_id(collection, item_id)
        if match:
            return collection, match
    return None


def find_collection_record_in_subsystem(
    store: dict[str, Any],
    subsystem_id: str,
    item_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for collection in store["collections"].values():
        if collection["subsystem_id"] != subsystem_id:
            continue
        match = find_record_by_configured_id(collection, item_id)
        if match:
            return collection, match
    return None


def clean_subsystem(subsystem: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in subsystem.items() if not key.startswith("_")}
