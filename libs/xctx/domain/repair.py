"""Repair-guidance payloads for xctx audit findings and maintenance states."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xctx.errors import XctxError
from xctx.protocol.guidance import command_hints

REPAIR_STATUS_PREFIXES = {"offline", "down_for_maintenance"}


@dataclass(frozen=True)
class RepairTarget:
    raw: str
    status_prefix: str
    domain_id: str
    subdomain_id: str | None
    obj: dict[str, Any]

    @property
    def resolved_target(self) -> str:
        return self.domain_id if not self.subdomain_id else f"{self.domain_id}::{self.subdomain_id}"

    @property
    def finding_id(self) -> str | None:
        return f"{self.status_prefix}:{self.resolved_target}" if self.status_prefix else None

    @property
    def domain_level(self) -> str:
        return "agent_subdomain" if self.subdomain_id else "agent_domain"


def target_from_repair_arg(target: str) -> tuple[str, str, str | None]:
    """Parse ``<finding_id|target>`` into status prefix plus domain scope."""

    status_prefix = ""
    raw = target
    if ":" in target and target.split(":", 1)[0] in REPAIR_STATUS_PREFIXES:
        status_prefix, raw = target.split(":", 1)
    if "::" in raw:
        domain_id, subdomain_id = raw.split("::", 1)
        return status_prefix, domain_id, subdomain_id or None
    return status_prefix, raw, None


def _resolve_repair_target(store: dict[str, Any], target: str) -> RepairTarget:
    if not target:
        raise XctxError("missing repair target", next_moves=["./xctx audit root", "./xctx repair <finding_id>"])
    status_prefix, domain_id, subdomain_id = target_from_repair_arg(target)
    if domain_id not in store.get("agent_domains", {}):
        raise XctxError(f"unknown repair target: {target}", next_moves=["./xctx audit root"])
    domain = store["agent_domains"][domain_id]
    obj = domain if not subdomain_id else domain.get("_subdomains", {}).get(subdomain_id)
    if not obj:
        raise XctxError(f"unknown repair target: {target}", next_moves=["./xctx audit root"])
    current_status = obj.get("status")
    if status_prefix and status_prefix != current_status:
        raise XctxError(
            f"stale repair finding: {target} no longer matches current status {current_status}",
            next_moves=["./xctx audit root"],
        )
    return RepairTarget(
        raw=target,
        status_prefix=status_prefix,
        domain_id=domain_id,
        subdomain_id=subdomain_id,
        obj=obj,
    )


def repair_domain_level(store: dict[str, Any], target: str) -> str:
    """Return the protocol domain level for a valid repair target."""

    return _resolve_repair_target(store, target).domain_level


def _base_payload(resolved: RepairTarget) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target": resolved.resolved_target,
        "current_status": resolved.obj.get("status"),
    }
    if resolved.finding_id:
        payload["finding_id"] = resolved.finding_id
    return payload


def repair_payload(store: dict[str, Any], target: str) -> tuple[bool, dict[str, Any], str | None]:
    resolved = _resolve_repair_target(store, target)
    obj = resolved.obj
    status = obj.get("status")
    repair_path = obj.get("repair_path")
    payload = _base_payload(resolved)

    if status == "down_for_maintenance":
        payload.update(
            {
                "repair_path": None,
                "final": True,
                "message": "down for maintenance: no repair path is exposed for this target.",
            }
        )
        return False, payload, "down_for_maintenance"
    if status == "offline":
        if not repair_path:
            payload.update(
                {
                    "repair_path": None,
                    "final": True,
                    "message": "offline target has no configured repair path.",
                }
            )
            return False, payload, "no_repair_path"
        payload.update(
            {
                "repair_path": repair_path,
                "execution_state": "not_applied_read_only_external_adapter_surface",
                "message": "Repair path exposed. xctx describes the repair; domain tools or operators perform real state changes.",
                "next_moves": command_hints(
                    [
                        f"./xctx plan bring_online {resolved.resolved_target}",
                        f"./xctx audit {resolved.resolved_target}",
                    ]
                ),
            }
        )
        return True, payload, None
    payload.update(
        {
            "repair_path": None,
            "message": "Target is online or repair is unnecessary.",
            "next_move": f"./xctx discover {resolved.resolved_target if resolved.subdomain_id else resolved.resolved_target + '::'}",
        }
    )
    return True, payload, None
