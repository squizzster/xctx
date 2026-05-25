"""Domain object helpers for configured xctx agent-domain surfaces."""

from __future__ import annotations

from typing import Any

from xctx.errors import XctxError
from xctx.protocol.descriptions import selected_description, with_description
from xctx.protocol.guidance import command_hint


## Protocol boundary: helpers in this module know the generic domain/subdomain
## envelope only. They must not encode business-domain vocabulary.
def has_agent_domains(store: dict[str, Any]) -> bool:
    return bool(store.get("agent_domains"))

def agent_routing(store: dict[str, Any]) -> dict[str, Any]:
    return store.get("universe", {}).get("agent_routing", {}) or {}

def compact_domain(store: dict[str, Any], domain: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": domain["id"],
        "kind": domain.get("kind", "agent_domain"),
        "status": domain.get("status", "unknown"),
        "health": domain.get("health"),
        "description": selected_description(store, domain),
        "run_cmd": f"./xctx discover {domain['id']}::",
    }
    if domain.get("offline_reason"):
        payload["offline_reason"] = domain["offline_reason"]
    repair_path = domain.get("repair_path")
    if repair_path:
        payload["repair_cmd"] = repair_path.get("run_cmd")
    elif domain.get("status") == "down_for_maintenance":
        payload["repair_cmd"] = None
        payload["terminal_reason"] = "down_for_maintenance"
    return {key: value for key, value in payload.items() if value is not None}

def compact_subdomain(store: dict[str, Any], domain_id: str, subdomain: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": subdomain["id"],
        "kind": subdomain.get("kind", "agent_subdomain"),
        "status": subdomain.get("status", "unknown"),
        "description": selected_description(store, subdomain),
        "run_cmd": f"./xctx discover {domain_id}::{subdomain['id']}",
    }
    if subdomain.get("offline_reason"):
        payload["offline_reason"] = subdomain["offline_reason"]
    repair_path = subdomain.get("repair_path")
    if repair_path:
        payload["repair_cmd"] = repair_path.get("run_cmd")
    elif subdomain.get("status") == "down_for_maintenance":
        payload["repair_cmd"] = None
        payload["terminal_reason"] = "down_for_maintenance"
    return {key: value for key, value in payload.items() if value is not None}

def joined_identifier(parts: list[str | None]) -> str | None:
    text = " ".join(str(part) for part in parts if part).strip()
    return text or None

def offline_subdomain_payload(store: dict[str, Any], domain_id: str, subdomain: dict[str, Any]) -> dict[str, Any]:
    payload = with_description(store, subdomain)
    payload["agent_domain"] = domain_id
    payload["status"] = subdomain.get("status")
    if subdomain.get("status") == "offline" and subdomain.get("repair_path"):
        repair_cmd = subdomain["repair_path"].get("run_cmd")
        payload["repair_cmd"] = repair_cmd
        if repair_cmd:
            payload["next_moves"] = [command_hint(str(repair_cmd))]
    if subdomain.get("status") == "down_for_maintenance":
        payload["repair_path"] = None
        payload["terminal_reason"] = "down_for_maintenance"
    return payload

def resolve_domain(store: dict[str, Any], domain_id: str) -> dict[str, Any]:
    domain = store.get("agent_domains", {}).get(domain_id)
    if not domain:
        raise XctxError(f"next valid move: choose a known agent_domain ({domain_id})")
    return domain

def resolve_subdomain(store: dict[str, Any], domain_id: str, subdomain_id: str) -> dict[str, Any]:
    domain = resolve_domain(store, domain_id)
    subdomain = domain.get("_subdomains", {}).get(subdomain_id)
    if not subdomain:
        raise XctxError(f"next valid move: choose a known agent_subdomain ({domain_id}::{subdomain_id})")
    return subdomain
