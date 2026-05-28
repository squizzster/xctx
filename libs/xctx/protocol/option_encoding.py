"""Target-scoped CLI option validation and adapter-argv encoding."""

from __future__ import annotations

import re
from typing import Any

from xctx.errors import XctxError
from xctx.protocol.option_specs import command_cli_option_specs, target_cli_option_specs


def _display_flag_for_dest(store: dict[str, Any], command: str, dest: str) -> str:
    for spec in command_cli_option_specs(store, command):
        if spec.get("_dest") == dest:
            return str(spec.get("_primary_flag") or ("--" + dest.replace("_", "-")))
    return "--" + dest.replace("_", "-")


def _is_present(value: Any) -> bool:
    return value is not None


def _coerce_bound(spec: dict[str, Any], key: str) -> Any:
    raw = spec.get(key)
    if raw is None:
        return None
    option_type = str(spec.get("_option_type", "str"))
    if option_type == "int":
        return int(raw)
    if option_type == "float":
        return float(raw)
    return raw


def _validate_min_max(spec: dict[str, Any], value: Any) -> None:
    lower = _coerce_bound(spec, "min")
    upper = _coerce_bound(spec, "max")
    if lower is not None and value < lower:
        raise XctxError(f"{spec['_primary_flag']} is below minimum {lower}")
    if upper is not None and value > upper:
        raise XctxError(f"{spec['_primary_flag']} is above maximum {upper}")


def _validate_pattern(spec: dict[str, Any], value: Any) -> None:
    pattern = spec.get("pattern")
    if pattern is None:
        return
    if not re.fullmatch(str(pattern), str(value)):
        raise XctxError(f"{spec['_primary_flag']} must match pattern {pattern}")


def encode_cli_options_for_target(
    store: dict[str, Any],
    subdomain: dict[str, Any],
    command: str,
    *,
    action_name: str | None,
    action: dict[str, Any] | None,
    values: dict[str, Any],
) -> list[str]:
    """Validate parsed options for a target and encode adapter argv fragments."""
    if not values:
        return []

    target_ref = f"{subdomain.get('_domain_id')}::{subdomain.get('id')}"
    specs = target_cli_option_specs(store, subdomain, command, action_name=action_name, action=action)
    by_dest = {spec["_dest"]: spec for spec in specs}

    unsupported = [dest for dest, value in values.items() if _is_present(value) and dest not in by_dest]
    if unsupported:
        flag = _display_flag_for_dest(store, command, unsupported[0])
        raise XctxError(f"unsupported option {flag} for {target_ref} {command}")

    present_specs: list[tuple[str, dict[str, Any], Any]] = []
    for dest, value in values.items():
        if not _is_present(value):
            continue
        spec = by_dest[dest]
        _validate_min_max(spec, value)
        if spec.get("choices") and str(value) not in {str(choice) for choice in spec.get("choices") or []}:
            choices = "|".join(str(choice) for choice in spec.get("choices") or [])
            raise XctxError(f"unsupported value for {spec['_primary_flag']}: {value} (allowed: {choices})")
        _validate_pattern(spec, value)
        present_specs.append((dest, spec, value))

    groups: dict[str, list[dict[str, Any]]] = {}
    for _dest, spec, _value in present_specs:
        group = spec.get("mutex_group") or spec.get("mutually_exclusive_group")
        if group:
            groups.setdefault(str(group), []).append(spec)
    for group_specs in groups.values():
        if len(group_specs) > 1:
            message = next((str(spec.get("conflict_message")) for spec in group_specs if spec.get("conflict_message")), "")
            if not message:
                options = " or ".join(str(spec["_primary_flag"]) for spec in group_specs)
                message = f"choose either {options}"
            raise XctxError(f"mutually exclusive options conflict: {message}")

    encoded: list[str] = []
    for _dest, spec, value in sorted(present_specs, key=lambda item: item[1].get("_order", 9999)):
        adapter_arg = str(spec.get("adapter_arg") or spec["_primary_flag"])
        action = str(spec.get("action", "store"))
        if spec.get("_option_type") == "bool" or action in {"store_true", "store_false"}:
            if action == "store_false":
                if value is False:
                    encoded.append(adapter_arg)
            elif bool(value):
                encoded.append(adapter_arg)
        else:
            encoded.extend([adapter_arg, str(value)])
    return encoded
