"""Config-driven CLI option surface for xctx commands.

The protocol core is allowed to know that commands can have options. It should
not know what those options mean inside any domain pack. Names and semantics
live in YAML under an action's ``cli_options`` declaration.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from xctx.errors import XctxError
from xctx.protocol.actions import action_matches
from xctx.protocol.accessors import canonical_command


SUPPORTED_OPTION_TYPES = {"str", "int", "float", "bool"}

## Protocol boundary: this file parses and validates configured option shape.
## It does not own scoped-pack semantics; it only carries values to adapters.


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
    flags = [str(flag) for flag in _as_list(raw_flags) if str(flag).strip()]
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


def _normalise_option_spec(raw: dict[str, Any], *, source: dict[str, Any], index: int) -> dict[str, Any]:
    spec = dict(raw)
    flags = _option_flags(spec)
    dest = _option_dest(spec)
    if not dest:
        raise XctxError("next valid move: add dest or flags to configured cli_option")
    if not flags:
        flags = ["--" + dest.replace("_", "-")]
    option_type = str(spec.get("type", "str"))
    if option_type not in SUPPORTED_OPTION_TYPES:
        raise XctxError(f"next valid move: choose supported cli_option type for {dest} ({', '.join(sorted(SUPPORTED_OPTION_TYPES))})")
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
    elif isinstance(raw, list):
        for value in raw:
            if isinstance(value, dict):
                yield None, value
            else:
                yield None, {"flags": [str(value)]}
    else:
        raise XctxError("next valid move: make cli_options a list or mapping")


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
    specs: list[dict[str, Any]] = []
    for offset, (_key, raw_spec) in enumerate(_iter_raw_cli_options(container)):
        specs.append(_normalise_option_spec(raw_spec, source=source, index=start_index + offset))
    return specs


def command_cli_option_specs(store: dict[str, Any], command: str) -> list[dict[str, Any]]:
    """Return unique parser-level option specs configured for an xctx command."""
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

    return _dedupe_specs(specs)


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


def _display_flag_for_dest(store: dict[str, Any], command: str, dest: str) -> str:
    for spec in command_cli_option_specs(store, command):
        if spec.get("_dest") == dest:
            return str(spec.get("_primary_flag") or ("--" + dest.replace("_", "-")))
    return "--" + dest.replace("_", "-")


def _is_present(value: Any) -> bool:
    return value is not None and value is not False


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
        raise XctxError(f"next valid move: remove unsupported option {flag} for {target_ref} {command}")

    present_specs: list[tuple[str, dict[str, Any], Any]] = []
    for dest, value in values.items():
        if not _is_present(value):
            continue
        spec = by_dest[dest]
        if spec.get("min") is not None and value < spec["min"]:
            raise XctxError(f"next valid move: {spec['_primary_flag']} must be at least {spec['min']}")
        if spec.get("max") is not None and value > spec["max"]:
            raise XctxError(f"next valid move: {spec['_primary_flag']} must be at most {spec['max']}")
        if spec.get("choices") and str(value) not in {str(choice) for choice in spec.get("choices") or []}:
            choices = "|".join(str(choice) for choice in spec.get("choices") or [])
            raise XctxError(f"next valid move: {spec['_primary_flag']} must be one of {choices}")
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
            raise XctxError(f"next valid move: {message}")

    encoded: list[str] = []
    for _dest, spec, value in sorted(present_specs, key=lambda item: item[1].get("_order", 9999)):
        adapter_arg = str(spec.get("adapter_arg") or spec["_primary_flag"])
        action = str(spec.get("action", "store"))
        if spec.get("_option_type") == "bool" or action in {"store_true", "store_false"}:
            if bool(value):
                encoded.append(adapter_arg)
        else:
            encoded.extend([adapter_arg, str(value)])
    return encoded


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
    """Parser-level option inventory for audits, not for root discovery/help.

    The xctx runtime may need to parse YAML-declared options before a concrete
    target is resolved. This function remains available for internal audit checks,
    but root/universe/help payloads must not expose it because it can include
    domain-action options such as a stock range selector.
    """
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
            specs = command_cli_option_specs(store, command)
        except XctxError as exc:
            checks.append({"id": f"audit:xctx:cli_options:{command}", "status": "fail", "error": str(exc)})
            continue
        flags = [flag for spec in specs for flag in spec.get("_flags", [])]
        duplicate_flags = sorted({flag for flag in flags if flags.count(flag) > 1})
        checks.append(
            {
                "id": f"audit:xctx:cli_options:{command}",
                "status": "pass" if not duplicate_flags else "fail",
                "configured_option_count": len(specs),
                "duplicate_flags": duplicate_flags,
            }
        )
    return checks
