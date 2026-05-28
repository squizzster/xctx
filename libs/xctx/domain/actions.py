"""Configured action and action-argument utilities for xctx domains."""

from __future__ import annotations

import shlex
from typing import Any

from xctx.errors import XctxError
from xctx.protocol.actions import action_matches, action_tokens


## Protocol boundary: action names, aliases, controls, and projections are declared
## by scoped YAML packs. This module validates declared structure, not meaning.
def _domain_action_name(action_name: str, action: dict[str, Any]) -> str:
    return str(action.get("domain_action_name") or action_name)

def _domain_action_candidate(
    domain_id: str,
    subdomain_id: str,
    action_name: str,
    action: dict[str, Any],
) -> dict[str, Any]:
    """Build a domain-scoped action config from a subdomain action.

    Domain-scoped affordances are deliberately opt-in from subdomain YAML via
    ``domain_affordance: true``. This keeps the universe/root protocol surface
    generic while still allowing scoped conveniences once an agent has entered
    a named domain.
    """
    public_name = _domain_action_name(action_name, action)
    implemented_by = f"{domain_id}::{subdomain_id}::{action_name}"
    domain_run_cmd = f"./xctx discover {domain_id}::{public_name}"
    return {
        **action,
        "agent_domain": domain_id,
        "agent_subdomain": subdomain_id,
        "implemented_by": implemented_by,
        "implemented_by_run_cmd": f"./xctx discover {implemented_by}",
        "domain_run_cmd": domain_run_cmd,
        "run_cmd": str(action.get("run_cmd") or domain_run_cmd).replace(f"./xctx discover {implemented_by}", domain_run_cmd),
        "_source_action_name": action_name,
        "_action_name": public_name,
    }

def iter_domain_action_configs(store: dict[str, Any], domain_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Return opt-in affordance shortcuts for an already-scoped agent domain."""
    domain = store.get("agent_domains", {}).get(domain_id)
    if not domain:
        return []
    items: list[tuple[str, dict[str, Any]]] = []
    for subdomain_id, subdomain in sorted(
        (domain.get("_subdomains") or {}).items(),
        key=lambda item: item[1].get("_priority", 9999),
    ):
        for action_name, action in sorted(
            (subdomain.get("actions") or {}).items(),
            key=lambda item: item[1].get("priority", 9999),
        ):
            if not action.get("domain_affordance"):
                continue
            candidate = _domain_action_candidate(domain_id, subdomain_id, action_name, action)
            items.append((str(candidate["_action_name"]), candidate))
    return items

def _domain_action_source_ref(domain_id: str, public_name: str, action: dict[str, Any]) -> str:
    source_action = str(action.get("_source_action_name") or public_name)
    return f"{domain_id}::{action.get('agent_subdomain')}::{source_action}"


def _disambiguation_run_cmd(ref: str, action_args: list[str] | None = None) -> str:
    parts = ["./xctx", "discover", ref, *(action_args or [])]
    return shlex.join(parts)


def domain_action_config(
    store: dict[str, Any],
    domain_id: str,
    action_name: str,
    action_args: list[str] | None = None,
) -> dict[str, Any] | None:
    """Resolve a named affordance inside an explicit agent-domain scope."""
    domain = store.get("agent_domains", {}).get(domain_id) or {}
    subdomains = domain.get("_subdomains") or {}
    matches: list[tuple[str, dict[str, Any]]] = []
    for name, action in iter_domain_action_configs(store, domain_id):
        if action_matches(name, action, action_name):
            matches.append((name, action))
    if not matches:
        return None
    if action_name in subdomains:
        sources = sorted(_domain_action_source_ref(domain_id, name, action) for name, action in matches)
        subdomain_ref = f"{domain_id}::{action_name}"
        sources.insert(0, subdomain_ref)
        message = (
            f"ambiguous scoped target: {domain_id}::{action_name} conflicts with configured subdomain "
            f"and domain affordance shortcut ({', '.join(sources)})"
        )
        raise XctxError(
            message,
            next_moves=[
                _disambiguation_run_cmd(subdomain_ref),
                *[_disambiguation_run_cmd(source, action_args) for source in sources[1:]],
            ],
        )
    if len(matches) > 1:
        sources = sorted(_domain_action_source_ref(domain_id, name, action) for name, action in matches)
        raise XctxError(
            f"duplicate domain affordance shortcut: {domain_id}::{action_name} ({', '.join(sources)})",
            next_moves=[_disambiguation_run_cmd(source, action_args) for source in sources],
        )
    name, action = matches[0]
    return {**action, "_action_name": name, "_matched_as": action_name}

def domain_affordance_config_check(store: dict[str, Any]) -> dict[str, Any]:
    """Return an audit check for ambiguous domain-scoped affordance names."""

    duplicates: list[dict[str, Any]] = []
    affordance_count = 0
    for domain_id in sorted((store.get("agent_domains") or {}).keys()):
        sources_by_token: dict[str, list[str]] = {}
        domain = store.get("agent_domains", {}).get(domain_id) or {}
        for subdomain_id in sorted((domain.get("_subdomains") or {}).keys()):
            sources_by_token.setdefault(str(subdomain_id), []).append(f"{domain_id}::{subdomain_id}")
        for public_name, action in iter_domain_action_configs(store, domain_id):
            affordance_count += 1
            subdomain_id = str(action.get("agent_subdomain", ""))
            source_action = str(action.get("_source_action_name") or public_name)
            source = f"{domain_id}::{subdomain_id}::{source_action}"
            for token in action_tokens(public_name, action):
                sources_by_token.setdefault(str(token), []).append(source)
        for token, sources in sorted(sources_by_token.items()):
            if len(sources) > 1:
                duplicates.append(
                    {
                        "agent_domain": domain_id,
                        "token": token,
                        "sources": sorted(sources),
                    }
                )

    return {
        "id": "audit:xctx:domain_affordances",
        "status": "pass" if not duplicates else "fail",
        "configured_affordance_count": affordance_count,
        "duplicate_affordances": duplicates,
    }

def subdomain_action_config(subdomain: dict[str, Any], action_name: str) -> tuple[str | None, dict[str, Any] | None]:
    for name, action in (subdomain.get("actions") or {}).items():
        if action_matches(name, action, action_name):
            return name, {**action, "_action_name": name, "_matched_as": action_name}
    return None, None

def canonical_action_for_structural_token(subdomain: dict[str, Any], token: str) -> str | None:
    for name, action in (subdomain.get("actions") or {}).items():
        structural_tokens = {
            str(value)
            for value in (action.get("entrypoint_command"), action.get("domain_action_name"))
            if value
        }
        if token in structural_tokens and token != name:
            return name
    return None

def parse_scoped_subdomain_mode_ref(
    store: dict[str, Any],
    token: str | None,
) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    """Parse <agent_domain>::<agent_subdomain>::<mode> structurally."""
    ## Boundary guard: this parser validates only configured reference grammar.
    ## The resolved mode's meaning is owned by YAML metadata and its adapter.
    if not token or "::" not in token:
        return None, None, None, None
    parts = token.split("::")
    if len(parts) != 3:
        return None, None, None, None
    domain_id, subdomain_token, action_token = parts
    if not domain_id or not subdomain_token or not action_token:
        return None, None, None, None
    domains = store.get("agent_domains", {})
    if domain_id not in domains:
        return None, None, None, None
    subdomain_id = str(subdomain_token)
    subdomain = (domains[domain_id].get("_subdomains") or {}).get(subdomain_id)
    if not subdomain:
        return None, None, None, None
    mode_name, mode = subdomain_action_config(subdomain, action_token)
    if not mode_name or not mode:
        raise XctxError(f"unknown action for {domain_id}::{subdomain_id}: {action_token}")
    return domain_id, subdomain_id, mode_name, mode

def _collection_contract(action: dict[str, Any]) -> dict[str, Any]:
    collection = action.get("collection") or {}
    return collection if isinstance(collection, dict) else {}

def _has_collection_cursor(collection: dict[str, Any]) -> bool:
    return str(collection.get("cursor", "none")).lower() not in {"", "none", "false", "no"}

def _action_projection_contract(action: dict[str, Any]) -> dict[str, Any]:
    raw = action.get("projections")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {"allowed": raw}
    collection = _collection_contract(action)
    if collection:
        return {
            "default": collection.get("default_projection", collection.get("default")),
            "allowed": collection.get("item_projections", collection.get("projections", [])),
        }
    return {}

def _action_projections(action: dict[str, Any]) -> set[str]:
    contract = _action_projection_contract(action)
    raw = contract.get("item_projections", contract.get("allowed", contract.get("projections", []))) or []
    if isinstance(raw, str):
        raw = [raw]
    return {str(item) for item in raw}

def selected_action_projection(action: dict[str, Any] | None, action_args: list[str]) -> str | None:
    if not action:
        return None
    contract = _action_projection_contract(action)
    if not contract:
        return None
    projection = contract.get("default_projection", contract.get("default"))
    index = 0
    while index < len(action_args):
        if action_args[index] == "--projection" and index + 1 < len(action_args):
            projection = action_args[index + 1]
            index += 2
            continue
        index += 1
    return str(projection) if projection else None

def _declared_option_flags(action: dict[str, Any]) -> set[str]:
    flags = {"--limit", "--cursor", "--projection"}
    collection = _collection_contract(action)
    if collection:
        flags.update(str(flag) for flag in collection.get("filters") or [] if str(flag).startswith("--"))
    raw_cli_options = action.get("cli_options") or []
    if isinstance(raw_cli_options, dict):
        cli_specs = []
        for key, value in raw_cli_options.items():
            spec = dict(value or {}) if isinstance(value, dict) else {}
            if str(key).startswith("-") and not any(name in spec for name in ("flags", "flag", "name")):
                spec["flags"] = [key]
            cli_specs.append(spec)
    else:
        cli_specs = list(raw_cli_options) if isinstance(raw_cli_options, (list, tuple)) else [raw_cli_options]
    for spec in cli_specs:
        if not isinstance(spec, dict):
            spec = {"flags": [spec]}
        raw_flags = spec.get("flags", spec.get("flag", spec.get("name")))
        if raw_flags is None and spec.get("dest"):
            raw_flags = ["--" + str(spec["dest"]).replace("_", "-")]
        if raw_flags is None:
            raw_flags = []
        elif not isinstance(raw_flags, (list, tuple)):
            raw_flags = [raw_flags]
        flags.update(str(flag) for flag in raw_flags if str(flag).startswith("--"))
    for pattern in action.get("argument_patterns") or []:
        parts = shlex.split(str(pattern).strip("[]"))
        if parts and parts[0].startswith("--"):
            flags.add(parts[0])
    return flags


def _declared_positional_prefixes(action: dict[str, Any]) -> set[str]:
    prefixes: set[str] = set()
    for pattern in action.get("argument_patterns") or []:
        raw = str(pattern).strip().strip("[]")
        if raw.startswith("--"):
            continue
        first = raw.split()[0] if raw.split() else ""
        if ":<" in first:
            prefixes.add(first.split(":<", 1)[0] + ":")
    return prefixes


def compact_action_index(actions: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, action in sorted(actions.items(), key=lambda item: item[1].get("priority", 9999)):
        entry = {
            "priority": action.get("priority"),
            "mode_kind": action.get("mode_kind"),
            "query_required": action.get("query_required"),
            "desc": action.get("desc"),
            "run_cmd": action.get("run_cmd"),
        }
        if action.get("domain_affordance"):
            entry["domain_affordance"] = True
            if action.get("domain_action_name"):
                entry["domain_action_name"] = action.get("domain_action_name")
        out[name] = {key: value for key, value in entry.items() if value is not None}
    return out

def validate_declared_action_args(action: dict[str, Any], action_args: list[str]) -> None:
    ## Protocol boundary: validate generic controls only when a scoped pack
    ## declares them. Cursor and projection values stay opaque to xctx.
    collection = _collection_contract(action)
    declared_options = _declared_option_flags(action)
    declared_positionals = _declared_positional_prefixes(action)
    arbitrary_query_allowed = bool(action.get("allow_arbitrary_query", action.get("query_required", True)))
    index = 0
    while index < len(action_args):
        token = action_args[index]
        if token == "--shape":
            raise XctxError("unsupported --shape; use --projection compact|full")
        if token.startswith("--") and token not in declared_options:
            raise XctxError(f"unsupported action option for this action: {token}")
        if token not in {"--limit", "--cursor", "--projection"}:
            if token in declared_options:
                if index + 1 >= len(action_args):
                    raise XctxError(f"missing value for {token}")
                index += 2
                continue
            if not arbitrary_query_allowed and not any(token.startswith(prefix) for prefix in declared_positionals):
                raise XctxError(f"unexpected argument for non-query action: {token}")
            index += 1
            continue
        if index + 1 >= len(action_args):
            raise XctxError(f"missing value for {token}")
        value = action_args[index + 1]
        if token == "--cursor":
            if not collection:
                raise XctxError(f"unsupported collection control for this action: {token}")
            if not _has_collection_cursor(collection):
                raise XctxError("--cursor is not supported by this collection")
        elif token == "--projection":
            projections = _action_projections(action)
            if not projections:
                raise XctxError("--projection is not supported by this action")
            if value not in projections:
                raise XctxError(f"unsupported --projection value: {value} (allowed: {'|'.join(sorted(projections))})")
        elif token == "--limit":
            if not collection:
                raise XctxError(f"unsupported collection control for this action: {token}")
            try:
                limit = int(value)
            except ValueError as exc:
                raise XctxError("--limit requires an integer") from exc
            if limit < 1:
                raise XctxError("--limit must be at least 1")
            max_limit = collection.get("max_limit")
            if max_limit is not None and limit > int(max_limit):
                raise XctxError(f"--limit exceeds maximum {max_limit}")
        index += 2
