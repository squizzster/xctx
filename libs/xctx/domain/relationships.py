"""Identity-to-resource relationship expansion."""

from __future__ import annotations

from typing import Any

from xctx.protocol.accessors import format_run_cmd, run_cmd_key
from xctx.store.resolver import resolve_collection


def relationship_resources(store: dict[str, Any], identity: dict[str, Any]) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    run_key = run_cmd_key(store)
    for subsystem in store["subsystems"]:
        for relationship in subsystem.get("relationships", []):
            if relationship.get("when_identity_category") != identity.get("category"):
                continue
            collection = resolve_collection(store, relationship["collection"], subsystem["id"])
            match_value = identity.get("source_id", identity.get("id"))
            matches = [
                record
                for record in collection["records"]
                if record.get(relationship["match_field"]) == match_value
            ]
            if relationship.get("summary_count"):
                summary = {
                    "kind": relationship.get("summary_kind", collection["name"]),
                    "count": len(matches),
                }
                if relationship.get("summary_run_cmd"):
                    summary[run_key] = format_run_cmd(
                        store,
                        relationship["summary_run_cmd"],
                        identity_id=identity.get("id"),
                        identity_name=identity.get("name"),
                    )
                resources.append(summary)
            for record in matches:
                item = {"kind": relationship.get("item_kind", collection["name"])}
                for field in relationship.get("item_fields", ["id"]):
                    if field in record:
                        item[field] = record[field]
                if relationship.get("item_run_cmd"):
                    item[run_key] = format_run_cmd(
                        store,
                        relationship["item_run_cmd"],
                        identity_id=identity.get("id"),
                        identity_name=identity.get("name"),
                        **record,
                    )
                resources.append(item)
    return resources
