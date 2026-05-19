"""Load the xctx YAML universe into an in-memory store."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from xctx.config.includes import normalize_data_spec, normalize_subsystem_refs, require_config
from xctx.config.paths import as_project_path, project_root_from_module
from xctx.io.yaml_io import load_yaml
from xctx.errors import XctxError


def _resolve(base: Path, maybe_relative: str) -> Path:
    path = Path(maybe_relative)
    return path if path.is_absolute() else base / path


def _load_subsystem_sections(subsystem: dict[str, Any], subsystem_file: Path) -> list[Path]:
    """Merge external subsystem section files into a subsystem mapping."""
    subsystem_dir = subsystem_file.parent
    section_files: list[Path] = []
    config = subsystem.get("config", {})
    section_map = {
        "data": ("data", {}),
        "discovery": ("discovery", {}),
        "relationships": ("relationships", []),
    }
    for config_key, (payload_key, default_value) in section_map.items():
        section_ref = config.get(config_key)
        if not section_ref:
            subsystem.setdefault(payload_key, default_value)
            continue
        section_file = _resolve(subsystem_dir, str(section_ref))
        section_doc = load_yaml(section_file)
        section_files.append(section_file)
        if payload_key == "relationships":
            subsystem[payload_key] = section_doc.get(payload_key, [])
        else:
            subsystem[payload_key] = section_doc.get(payload_key, {})
    subsystem["_section_files"] = section_files
    return section_files


def _selected_system_id(universe: dict[str, Any], override_system: str | None) -> str:
    return (
        override_system
        or os.environ.get("XCTX_ACTIVE_SYSTEM")
        or str(require_config(universe, "active_system", "yaml_dynamic_config/universe.yaml"))
    )


def _selected_agent_domain_id(universe: dict[str, Any], override_agent_domain: str | None) -> str | None:
    return (
        override_agent_domain
        or os.environ.get("XCTX_ACTIVE_AGENT_DOMAIN")
        or os.environ.get("XCTX_ACTIVE_SYSTEM")
        or universe.get("active_agent_domain")
        or universe.get("active_system")
    )


def _load_agent_domains(
    root: Path,
    config_dir: Path,
    universe: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    domains: dict[str, dict[str, Any]] = {}
    config_files: list[Path] = []
    for ref in universe.get("agent_domains", []) or []:
        domain_id = str(require_config(ref, "id", "yaml_dynamic_config/universe.yaml"))
        domain_file = _resolve(config_dir, str(require_config(ref, "path", "yaml_dynamic_config/universe.yaml")))
        domain = load_yaml(domain_file)
        domain.setdefault("id", domain_id)
        domain["_config_path"] = as_project_path(root, domain_file)
        domain["_dir"] = domain_file.parent
        domain["_universe_ref"] = ref
        config_files.append(domain_file)

        subdomains: dict[str, dict[str, Any]] = {}
        aliases: dict[str, str] = {}
        for subdomain_id, sub_ref in (domain.get("agent_subdomains") or {}).items():
            subdomain_file = _resolve(domain_file.parent, str(require_config(sub_ref, "path", domain["_config_path"])))
            subdomain = load_yaml(subdomain_file)
            subdomain.setdefault("id", str(subdomain_id))
            subdomain["_config_path"] = as_project_path(root, subdomain_file)
            subdomain["_dir"] = subdomain_file.parent
            subdomain["_domain_id"] = domain["id"]
            subdomain["_domain_ref"] = sub_ref
            subdomain["_priority"] = sub_ref.get("priority", 9999)
            subdomains[subdomain["id"]] = subdomain
            aliases[subdomain["id"]] = subdomain["id"]
            for alias in subdomain.get("aliases", []) or []:
                aliases[str(alias)] = subdomain["id"]
            config_files.append(subdomain_file)

        domain["_subdomains"] = subdomains
        domain["_subdomain_aliases"] = aliases
        domains[domain["id"]] = domain
    return domains, config_files


def load_store(
    root: Path | None = None,
    override_system: str | None = None,
    override_agent_domain: str | None = None,
) -> dict[str, Any]:
    """Load a complete YAML-backed xctx store for one active top-level system."""
    root = root or project_root_from_module()
    config_dir = root / "yaml_dynamic_config"
    universe_file = config_dir / "universe.yaml"
    universe = load_yaml(universe_file)

    protocol_ref = require_config(universe, "protocol", as_project_path(root, universe_file))
    protocol_file = _resolve(config_dir, str(protocol_ref))
    protocol = load_yaml(protocol_file)

    agent_domains, agent_domain_config_files = _load_agent_domains(root, config_dir, universe)
    active_agent_domain = _selected_agent_domain_id(universe, override_agent_domain)
    if active_agent_domain and agent_domains and active_agent_domain not in agent_domains:
        raise XctxError(f"next valid move: choose a known agent_domain ({', '.join(sorted(agent_domains))})")

    systems = universe.get("systems", []) or []
    active_system: str | None = None
    system_ref: dict[str, Any] | None = None
    system_file: Path | None = None
    system_dir: Path | None = None
    system: dict[str, Any] = {}
    system_config: dict[str, Any] = {}
    if systems:
        active_system = _selected_system_id(universe, override_system)
        system_ref = next((item for item in systems if item.get("id") == active_system), None)
        if not system_ref:
            raise XctxError(f"next valid move: add active system {active_system} to universe systems")

        system_file = _resolve(config_dir, str(system_ref["path"]))
        system_dir = system_file.parent
        system = load_yaml(system_file)
        system_config = require_config(system, "config", as_project_path(root, system_file))

    commands_ref = universe.get("commands")
    if commands_ref:
        commands_file = _resolve(config_dir, str(commands_ref))
    elif system_dir and system_config:
        commands_file = _resolve(
            system_dir,
            str(require_config(system_config, "commands", as_project_path(root, system_file))),
        )
    else:
        raise XctxError("next valid move: add commands to yaml_dynamic_config/universe.yaml")
    commands = load_yaml(commands_file)

    status_file: Path | None = None
    status_checks: list[dict[str, Any]] = []
    registry_file: Path | None = None
    subsystem_registry: dict[str, Any] = {}
    subsystem_refs: list[dict[str, Any]] = []
    if system_dir and system_config:
        status_file = _resolve(
            system_dir,
            str(require_config(system_config, "status_checks", as_project_path(root, system_file))),
        )
        status_checks = load_yaml(status_file).get("status_checks", [])

        registry_file = _resolve(
            system_dir,
            str(require_config(system_config, "subsystems", as_project_path(root, system_file))),
        )
        subsystem_registry = load_yaml(registry_file)
        subsystem_refs = normalize_subsystem_refs(
            require_config(subsystem_registry, "subsystems", as_project_path(root, registry_file))
        )

    subsystems: list[dict[str, Any]] = []
    subsystems_by_id: dict[str, dict[str, Any]] = {}
    collections: dict[str, dict[str, Any]] = {}
    collection_aliases: dict[str, list[str]] = {}
    config_files: list[Path] = [universe_file, protocol_file, commands_file, *agent_domain_config_files]
    config_files.extend(path for path in (system_file, status_file, registry_file) if path is not None)

    for subsystem_ref in subsystem_refs:
        if "path" not in subsystem_ref:
            ref_id = subsystem_ref.get("id", "unknown")
            raise XctxError(f"next valid move: add path to subsystem registry entry {ref_id}")
        subsystem_file = _resolve(system_dir, str(subsystem_ref["path"]))
        subsystem_dir = subsystem_file.parent
        subsystem = load_yaml(subsystem_file)
        subsystem["_config_path"] = as_project_path(root, subsystem_file)
        subsystem["_system_ref"] = subsystem_ref
        subsystem["_dir"] = subsystem_dir
        config_files.append(subsystem_file)
        config_files.extend(_load_subsystem_sections(subsystem, subsystem_file))

        subsystems.append(subsystem)
        subsystems_by_id[subsystem["id"]] = subsystem

        for collection_name, raw_spec in subsystem.get("data", {}).items():
            spec = normalize_data_spec(collection_name, raw_spec)
            data_file = _resolve(subsystem_dir, str(spec["path"]))
            data_doc = load_yaml(data_file)
            records = data_doc.get(spec["root_key"], [])
            if not isinstance(records, list):
                raise XctxError(f"next valid move: inspect records under {spec['root_key']} in {data_file}")
            collection_id = spec.get("id", f"{subsystem['id']}.{collection_name}")
            collections[collection_id] = {
                "id": collection_id,
                "name": collection_name,
                "subsystem_id": subsystem["id"],
                "path": data_file,
                "root_key": spec["root_key"],
                "spec": spec,
                "records": records,
            }
            collection_aliases.setdefault(collection_name, []).append(collection_id)
            config_files.append(data_file)

    return {
        "root": root,
        "config_dir": config_dir,
        "universe_file": universe_file,
        "universe": universe,
        "active_agent_domain": active_agent_domain,
        "agent_domains": agent_domains,
        "agent_domains_by_id": agent_domains,
        "protocol_file": protocol_file,
        "protocol": protocol,
        "system_ref": system_ref,
        "active_system": active_system,
        "all_systems": systems,
        "system_file": system_file,
        "system_dir": system_dir,
        "system": system,
        "commands_file": commands_file,
        "commands": commands,
        "status_file": status_file,
        "status_checks": status_checks,
        "subsystem_registry_file": registry_file,
        "subsystem_registry": subsystem_registry,
        "subsystem_refs": subsystem_refs,
        "subsystems": subsystems,
        "subsystems_by_id": subsystems_by_id,
        "collections": collections,
        "collection_aliases": collection_aliases,
        "config_files": sorted(set(config_files)),
    }
