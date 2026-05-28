"""Validation for loaded xctx YAML configuration.

The loader validates structural invariants that would make the framework unsafe
or impossible to operate. Dynamic protocol policy, such as extra command names in
YAML, is still reported by audit so operators can see all local-development leaks.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any

from xctx.errors import XctxError
from xctx.process.limits import ConnectorLimits

VALID_AVAILABILITY_STATES = frozenset({"online", "offline", "down_for_maintenance"})
VALID_CONNECTOR_KINDS = frozenset({"external_command", "xctx_native_passthrough"})
VALID_ADAPTER_SCOPES = frozenset({"domain", "subdomain"})
IMPORT_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
ENTRYPOINT_SUPERVISOR = "connector_supervisor.py"


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


def _validate_id(value: Any, label: str) -> None:
    text = str(value or "")
    if not IMPORT_SAFE_ID.fullmatch(text):
        raise XctxError(f"invalid {label}: {text}")


def _validate_workspace_relative_path(root: Path, value: Any, label: str, *, must_exist: bool) -> None:
    if not isinstance(value, str) or not value.strip():
        raise XctxError(f"{label} must be a non-empty workspace-relative path")
    candidate = Path(value)
    if candidate.is_absolute():
        raise XctxError(f"{label} must be workspace-relative")
    workspace = root.resolve()
    resolved = (workspace / candidate).resolve()
    if resolved != workspace and workspace not in resolved.parents:
        raise XctxError(f"{label} resolves outside the xctx workspace")
    if must_exist and not resolved.is_file():
        raise XctxError(f"{label} does not resolve to a file: {value}")


def _validate_entrypoint(subdomain: dict[str, Any], label: str) -> None:
    entrypoint = _require_mapping(subdomain.get("entrypoint", {}), f"{label}.entrypoint")
    if str(entrypoint.get("file") or "") != ENTRYPOINT_SUPERVISOR:
        raise XctxError(f"{label}.entrypoint.file must be {ENTRYPOINT_SUPERVISOR}")
    ConnectorLimits.from_config(
        entrypoint,
        default_timeout_seconds=30,
        label_prefix=f"{label}.entrypoint",
        error_type=XctxError,
    )
    protocol = entrypoint.get("protocol")
    if protocol is not None and str(protocol) != "json_stdout":
        raise XctxError(f"unsupported {label}.entrypoint.protocol: {protocol}")


def _validate_connector(root: Path, subdomain: dict[str, Any], label: str) -> None:
    connector = _require_mapping(subdomain.get("connector", {}), f"{label}.connector")
    kind = str(connector.get("kind") or "")
    if kind not in VALID_CONNECTOR_KINDS:
        allowed = "|".join(sorted(VALID_CONNECTOR_KINDS))
        raise XctxError(f"unsupported {label}.connector.kind: {kind} (allowed: {allowed})")
    ConnectorLimits.from_config(
        connector,
        default_timeout_seconds=30,
        label_prefix=f"{label}.connector",
        error_type=XctxError,
    )
    if kind == "xctx_native_passthrough":
        _validate_workspace_relative_path(
            root,
            connector.get("target_entrypoint"),
            f"{label}.connector.target_entrypoint",
            must_exist=True,
        )
    adapter_scope = connector.get("adapter_scope")
    if adapter_scope is not None and str(adapter_scope) not in VALID_ADAPTER_SCOPES:
        allowed = "|".join(sorted(VALID_ADAPTER_SCOPES))
        raise XctxError(f"unsupported {label}.connector.adapter_scope: {adapter_scope} (allowed: {allowed})")


def _validate_actions(actions: dict[str, Any], label: str) -> None:
    for action_name, action in actions.items():
        _validate_id(action_name, f"{label}.actions action id")
        _require_mapping(action, f"{label}.actions.{action_name}")


def validate_loaded_store(store: dict[str, Any]) -> None:
    """Validate framework-level shape after all YAML includes are loaded."""

    root = Path(store["root"])
    _require_mapping(store.get("protocol", {}), "protocol")
    _require_mapping(store.get("commands", {}), "commands")
    domains = _require_mapping(store.get("agent_domains", {}), "agent_domains")
    for domain_id, domain in domains.items():
        _require_mapping(domain, f"agent_domain {domain_id}")
        _validate_id(domain_id, "agent_domain id")
        if str(domain.get("id", "")) != str(domain_id):
            raise XctxError(f"agent_domain id mismatch for {domain_id}")
        if domain.get("kind") is not None and str(domain.get("kind")) != "agent_domain":
            raise XctxError(f"unsupported agent_domain {domain_id}.kind: {domain.get('kind')}")
        _validate_availability(domain.get("status"), f"agent_domain {domain_id}")
        subdomains = _require_mapping(domain.get("_subdomains", {}), f"agent_domain {domain_id} subdomains")
        for subdomain_id, subdomain in subdomains.items():
            label = f"agent_subdomain {domain_id}::{subdomain_id}"
            _require_mapping(subdomain, f"agent_subdomain {domain_id}::{subdomain_id}")
            _validate_id(subdomain_id, f"{label} id")
            if str(subdomain.get("id", "")) != str(subdomain_id):
                raise XctxError(f"agent_subdomain id mismatch for {domain_id}::{subdomain_id}")
            if subdomain.get("kind") is not None and str(subdomain.get("kind")) != "agent_subdomain":
                raise XctxError(f"unsupported {label}.kind: {subdomain.get('kind')}")
            _validate_availability(subdomain.get("status"), f"agent_subdomain {domain_id}::{subdomain_id}")
            if subdomain.get("status") == "online":
                actions = _require_mapping(subdomain.get("actions", {}), f"{label}.actions")
                _validate_entrypoint(subdomain, label)
                _validate_connector(root, subdomain, label)
                _validate_actions(actions, label)
