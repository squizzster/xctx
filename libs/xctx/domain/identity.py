"""Identity enumeration and lookup."""

from __future__ import annotations

from typing import Any

from xctx.errors import XctxError
from xctx.protocol.accessors import run_cmd_key, guidance_cmd
from xctx.protocol.descriptions import selected_description
from xctx.store.resolver import find_by_id, record_lookup_id, record_source_id


def identity_query_fields(store: dict[str, Any]) -> list[str]:
    configured = (store.get("universe", {}).get("identity_resolution", {}) or {}).get("query_fields")
    if configured:
        return [str(field) for field in configured]
    return ["name", "id", "aliases"]


def _field_values(record: dict[str, Any], field: str) -> list[Any]:
    value = record.get(field)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return list(value.values())
    return [value]


def record_matches_query(record: dict[str, Any], query: str, fields: list[str]) -> bool:
    lowered = query.lower()
    for field in fields:
        for value in _field_values(record, field):
            if lowered in str(value).lower():
                return True
    return False


def record_has_exact_name(record: dict[str, Any], query: str, fields: list[str]) -> bool:
    lowered = query.lower()
    for field in fields:
        for value in _field_values(record, field):
            if lowered == str(value).lower():
                return True
    return False


def _agent_domain_identity_records(store: dict[str, Any], run_key: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for domain_id, domain in store.get("agent_domains", {}).items():
        domain_record = {
            "category": "agent_domain",
            "name": domain.get("name", domain_id),
            "id": domain_id,
            "kind": domain.get("kind", "agent_domain"),
            "status": domain.get("status", "unknown"),
            "desc": selected_description(store, domain),
            "trusted": True,
            run_key: f"./xctx discover {domain_id}::",
        }
        if domain.get("health"):
            domain_record["health"] = domain["health"]
        if domain.get("offline_reason"):
            domain_record["offline_reason"] = domain["offline_reason"]
        records.append(domain_record)

        for subdomain_id, subdomain in sorted(
            (domain.get("_subdomains") or {}).items(),
            key=lambda item: item[1].get("_priority", 9999),
        ):
            subdomain_record = {
                "category": "agent_subdomain",
                "name": subdomain.get("name", subdomain_id),
                "id": f"{domain_id}::{subdomain_id}",
                "kind": subdomain.get("kind", "agent_subdomain"),
                "agent_domain": domain_id,
                "subdomain_id": subdomain_id,
                "status": subdomain.get("status", "unknown"),
                "desc": selected_description(store, subdomain),
                "aliases": subdomain.get("aliases", []),
                "trusted": True,
                run_key: f"./xctx discover {domain_id}::{subdomain_id}",
            }
            if subdomain.get("offline_reason"):
                subdomain_record["offline_reason"] = subdomain["offline_reason"]
            records.append(subdomain_record)

    return records


def identity_records(store: dict[str, Any], category: str = "all") -> list[dict[str, Any]]:
    run_key = run_cmd_key(store)
    records: list[dict[str, Any]] = []
    if store.get("system"):
        records.append(
            {
                "category": "system",
                "name": store["system"]["name"],
                "id": store["system"]["id"],
                "desc": store["system"]["desc"],
                "trusted": True,
            }
        )
    records.extend(_agent_domain_identity_records(store, run_key))
    records.extend(
        {
            "category": "available_system",
            "name": item.get("name", item.get("id")),
            "id": item.get("id"),
            "desc": item.get("desc", ""),
            "trusted": True,
            run_key: f"./xctx --system {item.get('id')} status",
        }
        for item in store.get("all_systems", [])
    )
    records.extend(
        {
            "category": "subsystem",
            "name": subsystem["name"],
            "id": subsystem["id"],
            "desc": subsystem["desc"],
            "trusted": True,
        }
        for subsystem in store["subsystems"]
    )

    for collection in store["collections"].values():
        spec = collection["spec"]
        if spec.get("kind") != "identity":
            continue
        for record in collection["records"]:
            identity_category = record.get(spec.get("category_field", ""), spec.get("default_category", collection["name"]))
            source_id = record_source_id(collection, record)
            identity = {
                "category": identity_category,
                "name": record.get("name", str(record_lookup_id(collection, record))),
                "id": str(record_lookup_id(collection, record)),
                "trusted": bool(record.get("trusted", True)),
            }
            if source_id and str(source_id) != identity["id"]:
                identity["source_id"] = source_id
            for optional_key in spec.get("optional_identity_fields", []):
                if optional_key in record:
                    identity[optional_key] = record[optional_key]
            records.append(identity)

    if category == "all":
        return records
    return [record for record in records if record.get("category") == category]


def find_identity(store: dict[str, Any], identity_id: str | None, name: str | None) -> dict[str, Any]:
    candidates = identity_records(store)
    if identity_id:
        match = find_by_id(candidates, identity_id)
        if match:
            return match
        run_cmd = guidance_cmd(store, "identify_query_run_cmd", query=identity_id)
        raise XctxError(f"next valid move: {run_cmd}" if run_cmd else "next valid move: identify")
    if name:
        fields = identity_query_fields(store)
        for record in candidates:
            if record_has_exact_name(record, name, fields):
                return record
        run_cmd = guidance_cmd(store, "identify_query_run_cmd", query=name)
        raise XctxError(f"next valid move: {run_cmd}" if run_cmd else "next valid move: identify")
    run_cmd = guidance_cmd(store, "discover_root_run_cmd")
    raise XctxError(f"next valid move: {run_cmd}" if run_cmd else "next valid move: discover")
