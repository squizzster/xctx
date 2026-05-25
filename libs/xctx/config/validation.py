"""Validation for loaded xctx YAML configuration.

The loader validates structural invariants that would make the framework unsafe
or impossible to operate. Dynamic protocol policy, such as extra command names in
YAML, is still reported by audit so operators can see all local-development leaks.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from xctx.errors import XctxError

VALID_AVAILABILITY_STATES = frozenset({"online", "offline", "down_for_maintenance"})


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise XctxError(f"{label} must be a YAML mapping")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise XctxError(f"{label} must be a YAML list")
    return value


def validate_universe_shape(universe: dict[str, Any]) -> None:
    """Validate the universe file before included domain YAML is loaded."""

    _require_mapping(universe, "universe")
    agent_domains = _require_list(universe.get("agent_domains", []), "universe.agent_domains")
    ids = [str(item.get("id")) for item in agent_domains if isinstance(item, dict) and item.get("id")]
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise XctxError(f"duplicate agent_domain ids: {', '.join(duplicates)}")


def _validate_availability(value: Any, label: str) -> None:
    status = str(value or "unknown")
    if status not in VALID_AVAILABILITY_STATES:
        allowed = "|".join(sorted(VALID_AVAILABILITY_STATES))
        raise XctxError(f"unsupported {label}.status: {status} (allowed: {allowed})")


def validate_loaded_store(store: dict[str, Any]) -> None:
    """Validate framework-level shape after all YAML includes are loaded."""

    _require_mapping(store.get("protocol", {}), "protocol")
    _require_mapping(store.get("commands", {}), "commands")
    domains = _require_mapping(store.get("agent_domains", {}), "agent_domains")
    for domain_id, domain in domains.items():
        _require_mapping(domain, f"agent_domain {domain_id}")
        if str(domain.get("id", "")) != str(domain_id):
            raise XctxError(f"agent_domain id mismatch for {domain_id}")
        _validate_availability(domain.get("status"), f"agent_domain {domain_id}")
        subdomains = _require_mapping(domain.get("_subdomains", {}), f"agent_domain {domain_id} subdomains")
        for subdomain_id, subdomain in subdomains.items():
            _require_mapping(subdomain, f"agent_subdomain {domain_id}::{subdomain_id}")
            if str(subdomain.get("id", "")) != str(subdomain_id):
                raise XctxError(f"agent_subdomain id mismatch for {domain_id}::{subdomain_id}")
            _validate_availability(subdomain.get("status"), f"agent_subdomain {domain_id}::{subdomain_id}")
            if subdomain.get("status") == "online" and not isinstance(subdomain.get("actions", {}), dict):
                raise XctxError(f"actions must be a mapping for {domain_id}::{subdomain_id}")
