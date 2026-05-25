"""Serializable views and audit checks for configured CLI options."""

from __future__ import annotations

from collections import Counter
from typing import Any

from xctx.errors import XctxError
from xctx.protocol.option_specs import (
    _command_cli_option_specs_raw,
    _dedupe_specs,
    command_cli_option_specs,
    target_cli_option_specs,
)


def _serialisable_option_entry(spec: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "flags": spec.get("_flags", []),
        "dest": spec.get("_dest"),
        "type": spec.get("_option_type"),
        "description": spec.get("desc") or spec.get("description"),
        "source": spec.get("_source"),
    }
    for key in ("min", "max", "mutex_group", "adapter_arg", "choices"):
        if spec.get(key) is not None:
            entry[key] = spec[key]
    return {key: value for key, value in entry.items() if value is not None}


def option_surface(store: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Parser-level option inventory for audits, not root discovery/help."""
    surface: dict[str, list[dict[str, Any]]] = {}
    for command in sorted(set((store.get("protocol") or {}).get("command_groups", {}).get("main", []))):
        entries = [_serialisable_option_entry(spec) for spec in command_cli_option_specs(store, command)]
        if entries:
            surface[command] = entries
    return surface


def target_option_surface(
    store: dict[str, Any],
    subdomain: dict[str, Any],
    command: str | None = None,
    *,
    action_name: str | None = None,
    action: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return options exposed only after a concrete subdomain/action is in scope."""
    commands = [command] if command else sorted(set((store.get("protocol") or {}).get("command_groups", {}).get("main", [])))
    surface: dict[str, list[dict[str, Any]]] = {}
    for command_name in commands:
        specs = target_cli_option_specs(store, subdomain, command_name, action_name=action_name, action=action)
        if action is None:
            for sub_action_name, sub_action in sorted(
                (subdomain.get("actions") or {}).items(),
                key=lambda item: item[1].get("priority", 9999),
            ):
                specs.extend(
                    target_cli_option_specs(
                        store,
                        subdomain,
                        command_name,
                        action_name=sub_action_name,
                        action=sub_action,
                    )
                )
        entries = [_serialisable_option_entry(spec) for spec in _dedupe_specs(specs)]
        if entries:
            surface[command_name] = entries
    return surface


def option_config_checks(store: dict[str, Any]) -> list[dict[str, Any]]:
    """Audit checks proving the configured option surface is parseable."""
    checks: list[dict[str, Any]] = []
    for command in sorted(set((store.get("protocol") or {}).get("command_groups", {}).get("main", []))):
        try:
            raw_specs = _command_cli_option_specs_raw(store, command)
        except XctxError as exc:
            checks.append({"id": f"audit:xctx:cli_options:{command}", "status": "fail", "error": str(exc)})
            continue
        specs = _dedupe_specs(raw_specs)
        flags = [flag for spec in raw_specs for flag in spec.get("_flags", [])]
        dests = [str(spec.get("_dest", "")) for spec in raw_specs if spec.get("_dest")]
        flag_counts = Counter(flags)
        dest_counts = Counter(dests)
        duplicate_flags = sorted(flag for flag, count in flag_counts.items() if count > 1)
        duplicate_dests = sorted(dest for dest, count in dest_counts.items() if count > 1)
        checks.append(
            {
                "id": f"audit:xctx:cli_options:{command}",
                "status": "pass" if not duplicate_flags and not duplicate_dests else "fail",
                "configured_option_count": len(specs),
                "raw_configured_option_count": len(raw_specs),
                "duplicate_flags": duplicate_flags,
                "duplicate_dests": duplicate_dests,
            }
        )
    return checks
