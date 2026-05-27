"""CLI option declaration parsing for the xctx protocol surface.

This module owns generic option grammar, not domain meaning: YAML can declare flags,
destinations, primitive types, choices, and target scoping. The values are only
interpreted after routing has resolved a concrete domain/subdomain/action.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from xctx.errors import XctxError
from xctx.protocol.actions import action_matches
from xctx.protocol.accessors import canonical_command

SUPPORTED_OPTION_TYPES = {"str", "int", "float", "bool"}


# Boundary guard: the protocol core parses option *syntax* declared by scoped
# packs. It does not own business semantics for options such as ranges, bars, or
# exports.
def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _option_flags(spec: dict[str, Any]) -> list[str]:
    raw_flags = spec.get("flags")
    if raw_flags is None:
        raw_flags = spec.get("flag", spec.get("name"))
    flags = [str(flag).strip() for flag in _as_list(raw_flags) if str(flag).strip()]
    if not flags and spec.get("dest"):
        flags = ["--" + str(spec["dest"]).replace("_", "-")]
    return flags


def _option_dest(spec: dict[str, Any]) -> str:
    if spec.get("dest"):
        return str(spec["dest"]).replace("-", "_")
    for flag in _option_flags(spec):
        if flag.startswith("--"):
            return flag[2:].replace("-", "_")
    flags = _option_flags(spec)
    if flags:
        return flags[0].lstrip("-").replace("-", "_")
    name = str(spec.get("name", "")).strip()
    return name.lstrip("-").replace("-", "_")


def _primary_flag(spec: dict[str, Any]) -> str:
    flags = _option_flags(spec)
    if not flags:
        return "--" + _option_dest(spec).replace("_", "-")
    for flag in flags:
        if flag.startswith("--"):
            return flag
    return flags[0]


def _coerce_scalar(value: Any, option_type: str, *, label: str) -> Any:
    if option_type == "int":
        if isinstance(value, bool):
            raise XctxError(f"invalid integer for {label}")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise XctxError(f"invalid integer for {label}") from exc
    if option_type == "float":
        if isinstance(value, bool):
            raise XctxError(f"invalid number for {label}")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise XctxError(f"invalid number for {label}") from exc
    if option_type == "bool":
        return bool(value) if isinstance(value, bool) else str(value)
    return str(value)


def _normalise_min_max(spec: dict[str, Any], option_type: str, dest: str) -> None:
    has_min = spec.get("min") is not None
    has_max = spec.get("max") is not None
    if not has_min and not has_max:
        return
    if option_type not in {"int", "float"}:
        raise XctxError(f"non-numeric cli_option has min/max: {dest}")
    lower = _coerce_scalar(spec.get("min"), option_type, label=f"cli_option {dest}.min") if has_min else None
    upper = _coerce_scalar(spec.get("max"), option_type, label=f"cli_option {dest}.max") if has_max else None
    if lower is not None:
        spec["min"] = lower
    if upper is not None:
        spec["max"] = upper
    if lower is not None and upper is not None and lower > upper:
        raise XctxError(f"invalid cli_option bounds: {dest}.min is greater than max")


def _normalise_choices(spec: dict[str, Any], option_type: str, dest: str) -> None:
    if spec.get("choices") is None:
        return
    if option_type == "bool":
        raise XctxError(f"bool cli_option cannot declare choices: {dest}")
    spec["choices"] = [
        _coerce_scalar(choice, option_type, label=f"cli_option {dest}.choices")
        for choice in _as_list(spec.get("choices"))
    ]


def _normalise_option_spec(raw: dict[str, Any], *, source: dict[str, Any], index: int) -> dict[str, Any]:
    spec = dict(raw)
    flags = _option_flags(spec)
    dest = _option_dest(spec)
    if not dest:
        raise XctxError("configured cli_option is missing dest or flags")
    if not flags:
        flags = ["--" + dest.replace("_", "-")]
    invalid_flags = [flag for flag in flags if not flag.startswith("-") or flag in {"-", "--"}]
    if invalid_flags:
        raise XctxError(
            "configured cli_option flags must start with '-' "
            f"for {dest} ({', '.join(invalid_flags)})"
        )
    option_type = str(spec.get("type", "str"))
    if option_type not in SUPPORTED_OPTION_TYPES:
        supported = ", ".join(sorted(SUPPORTED_OPTION_TYPES))
        raise XctxError(f"unsupported cli_option type for {dest}: {option_type} (supported: {supported})")
    _normalise_min_max(spec, option_type, dest)
    _normalise_choices(spec, option_type, dest)
    spec["_flags"] = flags
    spec["_dest"] = dest
    spec["_primary_flag"] = _primary_flag(spec)
    spec["_option_type"] = option_type
    spec["_source"] = source
    spec["_order"] = index
    return spec


def _iter_raw_cli_options(container: dict[str, Any]) -> Iterable[tuple[str | None, dict[str, Any]]]:
    raw = container.get("cli_options", []) or []
    if isinstance(raw, dict):
        for key, value in raw.items():
            spec = dict(value or {})
            if "dest" not in spec and not str(key).startswith("-"):
                spec["dest"] = str(key)
            if not any(name in spec for name in ("flags", "flag", "name")) and str(key).startswith("-"):
                spec["flags"] = [str(key)]
            yield str(key), spec
        return
    if isinstance(raw, list):
        for value in raw:
            if isinstance(value, dict):
                yield None, value
            else:
                yield None, {"flags": [str(value)]}
        return
    raise XctxError("cli_options must be a list or mapping")


def _commands_declared(spec: dict[str, Any]) -> set[str]:
    values = spec.get("commands", spec.get("command"))
    return {str(value) for value in _as_list(values)}


def _spec_applies_to_command(
    store: dict[str, Any],
    spec: dict[str, Any],
    command: str,
    *,
    action_name: str | None = None,
    action: dict[str, Any] | None = None,
) -> bool:
    canonical = canonical_command(store, command)
    declared = {canonical_command(store, value) for value in _commands_declared(spec)}
    if declared:
        return canonical in declared
    if action_name and action and action_matches(action_name, action, canonical):
        return True
    return False


def _dedupe_specs(specs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_flags: set[str] = set()
    seen_dests: set[str] = set()
    for spec in specs:
        flags = tuple(spec.get("_flags", []))
        dest = str(spec.get("_dest", ""))
        flag_collision = any(flag in seen_flags for flag in flags)
        dest_collision = dest in seen_dests
        if flag_collision or dest_collision:
            continue
        deduped.append(spec)
        seen_flags.update(flags)
        seen_dests.add(dest)
    return deduped


def _normalised_specs_for_container(
    container: dict[str, Any],
    *,
    source: dict[str, Any],
    start_index: int,
) -> list[dict[str, Any]]:
    return [
        _normalise_option_spec(raw_spec, source=source, index=start_index + offset)
        for offset, (_key, raw_spec) in enumerate(_iter_raw_cli_options(container))
    ]


def _command_cli_option_specs_raw(store: dict[str, Any], command: str) -> list[dict[str, Any]]:
    """Return parser-level option specs before duplicate filtering."""
    specs: list[dict[str, Any]] = []
    index = 0

    for domain_id, domain in (store.get("agent_domains") or {}).items():
        for subdomain_id, subdomain in sorted(
            (domain.get("_subdomains") or {}).items(),
            key=lambda item: item[1].get("_priority", 9999),
        ):
            source = {"kind": "agent_subdomain", "agent_domain": domain_id, "agent_subdomain": subdomain_id}
            for spec in _normalised_specs_for_container(subdomain, source=source, start_index=index):
                index += 1
                if _spec_applies_to_command(store, spec, command):
                    specs.append(spec)

            for action_name, action in sorted(
                (subdomain.get("actions") or {}).items(),
                key=lambda item: item[1].get("priority", 9999),
            ):
                source = {
                    "kind": "agent_subdomain_action",
                    "agent_domain": domain_id,
                    "agent_subdomain": subdomain_id,
                    "action": action_name,
                }
                for spec in _normalised_specs_for_container(action, source=source, start_index=index):
                    index += 1
                    if _spec_applies_to_command(store, spec, command, action_name=action_name, action=action):
                        specs.append(spec)

    return specs


def command_cli_option_specs(store: dict[str, Any], command: str) -> list[dict[str, Any]]:
    """Return unique parser-level option specs configured for an xctx command."""
    return _dedupe_specs(_command_cli_option_specs_raw(store, command))


def target_cli_option_specs(
    store: dict[str, Any],
    subdomain: dict[str, Any],
    command: str,
    *,
    action_name: str | None = None,
    action: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return option specs valid for a resolved subdomain/action target."""
    domain_id = str(subdomain.get("_domain_id", ""))
    subdomain_id = str(subdomain.get("id", ""))
    specs: list[dict[str, Any]] = []
    index = 0

    source = {"kind": "agent_subdomain", "agent_domain": domain_id, "agent_subdomain": subdomain_id}
    for spec in _normalised_specs_for_container(subdomain, source=source, start_index=index):
        index += 1
        if _spec_applies_to_command(store, spec, command):
            specs.append(spec)

    if action:
        source = {
            "kind": "agent_subdomain_action",
            "agent_domain": domain_id,
            "agent_subdomain": subdomain_id,
            "action": action_name,
        }
        for spec in _normalised_specs_for_container(action, source=source, start_index=index):
            index += 1
            if _spec_applies_to_command(store, spec, command, action_name=action_name, action=action):
                specs.append(spec)

    return _dedupe_specs(specs)


def collect_cli_option_values(store: dict[str, Any], command: str, args: Any) -> dict[str, Any]:
    """Collect configured option values from an argparse namespace."""
    values: dict[str, Any] = {}
    for spec in command_cli_option_specs(store, command):
        dest = spec["_dest"]
        if not hasattr(args, dest):
            continue
        value = getattr(args, dest)
        if value is None:
            continue
        values[dest] = value
    return values
