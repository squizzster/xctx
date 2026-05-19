"""Observation expansion behavior."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from xctx.store.resolver import resolve_collection


def apply_observe_expansions(
    store: dict[str, Any],
    collection: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    payload = deepcopy(record)
    observe = collection["spec"].get("observe", {})
    subsystem_id = collection["subsystem_id"]

    for _name, join in observe.get("joins", {}).items():
        target = resolve_collection(store, join["collection"], subsystem_id)
        local_value = record.get(join["local_field"])
        payload[join.get("output_key", join["collection"])] = next(
            (item for item in target["records"] if item.get(join.get("foreign_field", "id")) == local_value),
            None,
        )

    for _name, reverse in observe.get("reverse", {}).items():
        target = resolve_collection(store, reverse["collection"], subsystem_id)
        local_value = record.get(reverse["local_field"])
        payload[reverse.get("output_key", reverse["collection"])] = [
            item for item in target["records"] if item.get(reverse["foreign_field"]) == local_value
        ]
    return payload
