"""Audit payload construction for xctx root/domain/subdomain scopes."""

from __future__ import annotations

from typing import Any

from xctx.config.paths import as_project_path
from xctx.domain.actions import domain_affordance_config_check
from xctx.domain.routing import parse_ref
from xctx.store.fingerprints import config_fingerprint_payload
from xctx.errors import XctxError
from xctx.ports.external_command import call_external_command
from xctx.process.redaction import redact_preview
from xctx.protocol.command_policy import command_surface_check
from xctx.protocol.option_surface import option_config_checks

VALID_AUDIT_CHECK_STATUSES = frozenset({"pass", "fail", "warn", "warning", "skip"})


## Protocol boundary: audits prove framework/config/adapter health; repairs are
## described elsewhere and real domain mutation remains outside this layer.
def availability_findings(store: dict[str, Any], scope: str = "root") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def include_domain(domain_id: str) -> bool:
        if scope in {"root", "all", "*"}:
            return True
        parsed_domain, _parsed_subdomain = parse_ref(store, scope)
        return parsed_domain == domain_id or scope == domain_id

    for domain_id, domain in store.get("agent_domains", {}).items():
        if not include_domain(domain_id):
            continue
        status = domain.get("status")
        if status in {"offline", "down_for_maintenance"}:
            repair_path = domain.get("repair_path")
            findings.append(
                {
                    "id": f"{status}:{domain_id}",
                    "target": domain_id,
                    "target_kind": "agent_domain",
                    "status": status,
                    "severity": "terminal" if status == "down_for_maintenance" else "repairable",
                    "repairable": bool(repair_path),
                    "repair_cmd": repair_path.get("run_cmd") if repair_path else None,
                    "reason": domain.get("offline_reason"),
                }
            )

        parsed_domain, parsed_subdomain = parse_ref(store, scope)
        for subdomain_id, subdomain in domain.get("_subdomains", {}).items():
            if scope not in {"root", "all", "*", domain_id} and not (
                parsed_domain == domain_id and parsed_subdomain in {None, subdomain_id}
            ):
                continue
            subdomain_status = subdomain.get("status")
            if subdomain_status in {"offline", "down_for_maintenance"}:
                repair_path = subdomain.get("repair_path")
                findings.append(
                    {
                        "id": f"{subdomain_status}:{domain_id}::{subdomain_id}",
                        "target": f"{domain_id}::{subdomain_id}",
                        "target_kind": "agent_subdomain",
                        "status": subdomain_status,
                        "severity": "terminal" if subdomain_status == "down_for_maintenance" else "repairable",
                        "repairable": bool(repair_path),
                        "repair_cmd": repair_path.get("run_cmd") if repair_path else None,
                        "reason": subdomain.get("offline_reason"),
                    }
                )
    return findings

def _known_audit_scope_next_moves(store: dict[str, Any], domain_id: str | None = None) -> list[str]:
    if domain_id and domain_id in store.get("agent_domains", {}):
        subdomains = sorted((store["agent_domains"][domain_id].get("_subdomains") or {}).keys())
        return [f"./xctx audit {domain_id}::{subdomain_id}" for subdomain_id in subdomains[:5]]
    domains = sorted(store.get("agent_domains", {}).keys())
    examples = ["root", *domains[:5]]
    return [f"./xctx audit {example}" for example in examples]

def audit_domain_level(store: dict[str, Any], scope: str) -> str:
    scope = scope or "root"
    if scope in {"root", "all", "*"}:
        return "root"

    domains = store.get("agent_domains", {})
    if "::" in scope:
        domain_id, subdomain_id = scope.split("::", 1)
        if not domain_id or not subdomain_id:
            raise XctxError("malformed audit scope", next_moves=_known_audit_scope_next_moves(store, domain_id or None))
        domain = domains.get(domain_id)
        if not domain:
            raise XctxError(f"unknown audit scope: {scope}", next_moves=_known_audit_scope_next_moves(store))
        if subdomain_id not in (domain.get("_subdomains") or {}):
            raise XctxError(f"unknown audit scope: {scope}", next_moves=_known_audit_scope_next_moves(store, domain_id))
        return "agent_subdomain"

    if scope not in domains:
        raise XctxError(f"unknown audit scope: {scope}", next_moves=_known_audit_scope_next_moves(store))
    return "agent_domain"

def _live_audit_subdomains(store: dict[str, Any], scope: str) -> list[tuple[str, str, dict[str, Any]]]:
    parsed_domain, parsed_subdomain = parse_ref(store, scope)
    domains = store.get("agent_domains", {})
    selected: list[tuple[str, str, dict[str, Any]]] = []
    for domain_id, domain in domains.items():
        if scope not in {"root", "all", "*"} and parsed_domain != domain_id:
            continue
        for subdomain_id, subdomain in (domain.get("_subdomains") or {}).items():
            if parsed_subdomain and parsed_subdomain != subdomain_id:
                continue
            if subdomain.get("status") == "online" and subdomain.get("entrypoint"):
                selected.append((domain_id, subdomain_id, subdomain))
    return selected


def _live_payload_failed(payload: dict[str, Any]) -> bool:
    object_type = str(payload.get("object_type", "")).lower()
    if object_type.endswith("_error"):
        return True
    command_status = payload.get("command_status")
    return isinstance(command_status, dict) and (
        command_status.get("timed_out") is True or command_status.get("ok") is False
    )


def _live_audit_failure_check(domain_id: str, subdomain_id: str, message: str) -> dict[str, Any]:
    return {
        "id": f"audit:{domain_id}:{subdomain_id}:live_adapter_contract",
        "status": "fail",
        "message": redact_preview(message),
    }


def audit_check_failed(check: Any) -> bool:
    """Return true when an audit check is malformed or explicitly failing."""

    if not isinstance(check, dict):
        return True
    status = str(check.get("status", "")).lower()
    return status == "fail" or status not in VALID_AUDIT_CHECK_STATUSES


def _normalise_live_audit_checks(
    domain_id: str,
    subdomain_id: str,
    live: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return fail-closed, framework-safe audit checks from a live adapter."""

    checks = live.get("checks")
    normalised: list[dict[str, Any]] = []

    if checks is None:
        if _live_payload_failed(live):
            return [_live_audit_failure_check(domain_id, subdomain_id, "live adapter returned an error payload")]
        return []
    if not isinstance(checks, list):
        return [_live_audit_failure_check(domain_id, subdomain_id, "live adapter checks must be a list")]

    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            normalised.append(
                _live_audit_failure_check(
                    domain_id,
                    subdomain_id,
                    f"live adapter check at index {index} must be a mapping",
                )
            )
            continue
        status = str(check.get("status", "")).lower()
        if status not in VALID_AUDIT_CHECK_STATUSES:
            normalised.append(
                _live_audit_failure_check(
                    domain_id,
                    subdomain_id,
                    f"live adapter check at index {index} has invalid status {check.get('status')!r}",
                )
            )
            continue
        normalized_check = dict(check)
        normalized_check["status"] = "warn" if status == "warning" else status
        normalised.append(normalized_check)

    if _live_payload_failed(live) and not any(check.get("status") == "fail" for check in normalised):
        normalised.append(_live_audit_failure_check(domain_id, subdomain_id, "live adapter returned an error payload"))
    return normalised


def audit_payload(store: dict[str, Any], scope: str) -> dict[str, Any]:
    scope = scope or "root"
    audit_domain_level(store, scope)
    findings = availability_findings(store, scope)
    checks: list[dict[str, Any]] = [
        {
            "id": "audit:xctx:config_loaded",
            "status": "pass",
            "loaded_config_files": [
                as_project_path(store["root"], path) if not isinstance(path, str) else path
                for path in store.get("config_files", [])
            ],
        },
        {
            "id": "audit:xctx:agent_domains_loaded",
            "status": "pass" if store.get("agent_domains") else "fail",
            "agent_domain_count": len(store.get("agent_domains", {})),
        },
        {
            "id": "audit:xctx:config_fingerprint",
            "status": "pass",
            "fingerprint": config_fingerprint_payload(store),
        },
    ]
    checks.append(command_surface_check(store))
    checks.append(domain_affordance_config_check(store))
    checks.extend(option_config_checks(store))

    for domain_id, subdomain_id, subdomain in _live_audit_subdomains(store, scope):
        try:
            live = call_external_command(store, subdomain, ["audit"])
        except XctxError as exc:
            checks.append(_live_audit_failure_check(domain_id, subdomain_id, str(exc)))
            continue
        checks.extend(_normalise_live_audit_checks(domain_id, subdomain_id, live))

    return {
        "scope": scope,
        "summary": {
            "checks": len(checks),
            "findings": len(findings),
            "repairable_findings": sum(1 for finding in findings if finding.get("repairable")),
            "terminal_maintenance_findings": sum(
                1 for finding in findings if finding.get("status") == "down_for_maintenance"
            ),
        },
        "checks": checks,
        "findings": findings,
    }
