"""Audit payload construction for xctx root/domain/subdomain scopes."""

from __future__ import annotations

from typing import Any

from xctx.config.paths import as_project_path
from xctx.domain.actions import domain_affordance_config_check
from xctx.domain.routing import parse_ref
from xctx.store.fingerprints import config_fingerprint_payload
from xctx.errors import XctxError
from xctx.ports.external_command import call_external_command
from xctx.protocol.command_policy import command_surface_check
from xctx.protocol.option_surface import option_config_checks


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

def _known_audit_scope_guidance(store: dict[str, Any], domain_id: str | None = None) -> str:
    if domain_id and domain_id in store.get("agent_domains", {}):
        subdomains = sorted((store["agent_domains"][domain_id].get("_subdomains") or {}).keys())
        examples = [f"{domain_id}::{subdomain_id}" for subdomain_id in subdomains[:5]]
        return f"next valid move: choose a known audit scope ({', '.join(examples)})"
    domains = sorted(store.get("agent_domains", {}).keys())
    examples = ["root", *domains[:5]]
    return f"next valid move: choose a known audit scope ({', '.join(examples)})"

def audit_domain_level(store: dict[str, Any], scope: str) -> str:
    scope = scope or "root"
    if scope in {"root", "all", "*"}:
        return "root"

    domains = store.get("agent_domains", {})
    if "::" in scope:
        domain_id, subdomain_id = scope.split("::", 1)
        if not domain_id or not subdomain_id:
            raise XctxError(_known_audit_scope_guidance(store, domain_id or None))
        domain = domains.get(domain_id)
        if not domain:
            raise XctxError(_known_audit_scope_guidance(store))
        if subdomain_id not in (domain.get("_subdomains") or {}):
            raise XctxError(_known_audit_scope_guidance(store, domain_id))
        return "agent_subdomain"

    if scope not in domains:
        raise XctxError(_known_audit_scope_guidance(store))
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

    for _domain_id, _subdomain_id, subdomain in _live_audit_subdomains(store, scope):
        live = call_external_command(store, subdomain, ["audit"])
        checks.extend(live.get("checks", []))

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
