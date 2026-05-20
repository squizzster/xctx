"""Structural diagnostics for the xctx workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xctx.config.paths import as_project_path
from xctx.ports.external_command import CONNECTOR_SUPERVISOR_ENTRYPOINT
from xctx.protocol.accessors import canonical_command, command_aliases, configured_command_names
from xctx.store.resolver import record_lookup_id, resolve_collection, subsystem_by_id


def _entrypoint_resolution_error(root: Path, raw: Any) -> str | None:
    if raw is None or str(raw).strip() == "":
        return "online without entrypoint.file"
    candidate = Path(str(raw))
    if candidate.is_absolute():
        return "entrypoint must be workspace-relative"
    workspace_root = root.resolve()
    resolved = (workspace_root / candidate).resolve()
    if resolved != workspace_root and workspace_root not in resolved.parents:
        return "entrypoint escapes workspace"
    if not resolved.exists():
        return "entrypoint missing"
    if not resolved.is_file():
        return "entrypoint is not a file"
    return None


def _expected_layout(root: Path) -> list[Path]:
    return [
        root / "libs/xctx/cli.py",
        root / "libs/xctx/process/runtime.py",
        root / "libs/xctx/process/argv.py",
        root / "libs/xctx/process/parser.py",
        root / "libs/xctx/process/signals.py",
        root / "libs/xctx/config/loader.py",
        root / "libs/xctx/io/yaml_io.py",
        root / "libs/xctx/io/jsonl.py",
        root / "libs/xctx/io/stdout.py",
        root / "libs/xctx/protocol/emitter.py",
        root / "libs/xctx/ports/external_command.py",
        root / "libs/xctx/store/resolver.py",
        root / "libs/xctx/domain/agent_domains.py",
        root / "libs/xctx/domain/discovery.py",
        root / "libs/xctx/commands/audit.py",
        root / "libs/xctx/commands/discover.py",
        root / "libs/xctx/commands/execute.py",
        root / "libs/xctx/commands/plan.py",
        root / "libs/xctx/commands/repair.py",
        root / "bin/xctx",
    ]


def run_diagnostics(store: dict[str, Any], handled_commands: set[str]) -> list[dict[str, Any]]:
    root: Path = store["root"]
    missing_layout = [as_project_path(root, path) for path in _expected_layout(root) if not path.exists()]
    diagnostics: list[dict[str, Any]] = [
        {
            "id": "doctor:modular_libs_layout_present",
            "status": "fail" if missing_layout else "pass",
            "desc": "engine implementation is broken into libs/xctx modules instead of a monolithic script",
            "missing": missing_layout,
        },
        {
            "id": "doctor:process_layer_externalized",
            "status": "pass" if (root / "libs/xctx/process/runtime.py").exists() else "fail",
            "desc": "process concerns are separated from command, domain, IO, and protocol modules",
            "process_modules": [
                "argv.py",
                "parser.py",
                "signals.py",
                "runtime.py",
            ],
        },
        {
            "id": "doctor:yaml_config_files_present",
            "status": "pass" if all(path.exists() for path in store["config_files"]) else "fail",
            "desc": "all loaded YAML config files are present",
        },
    ]

    agent_domain_errors: list[dict[str, Any]] = []
    for ref in store.get("universe", {}).get("agent_domains", []) or []:
        domain_id = ref.get("id")
        if not domain_id:
            agent_domain_errors.append({"reason": "missing id", "ref": ref})
            continue
        if domain_id not in store.get("agent_domains", {}):
            agent_domain_errors.append({"id": domain_id, "reason": "domain did not load"})
    diagnostics.append(
        {
            "id": "doctor:agent_domain_refs_resolve",
            "status": "fail" if agent_domain_errors else "pass",
            "desc": "agent-domain references from universe resolve to loaded domain definitions",
            "agent_domain_errors": agent_domain_errors,
        }
    )

    adapter_errors: list[dict[str, Any]] = []
    for domain_id, domain in store.get("agent_domains", {}).items():
        for subdomain_id, subdomain in domain.get("_subdomains", {}).items():
            entrypoint = subdomain.get("entrypoint") or {}
            executable = entrypoint.get("file")
            if subdomain.get("status") != "online":
                continue
            if not isinstance(subdomain.get("connector"), dict):
                adapter_errors.append({"target": f"{domain_id}::{subdomain_id}", "reason": "online without connector block"})
                continue
            resolution_error = _entrypoint_resolution_error(root, executable)
            if resolution_error:
                adapter_errors.append(
                    {"target": f"{domain_id}::{subdomain_id}", "reason": resolution_error, "entrypoint": executable}
                )
                continue
            if Path(str(executable)).as_posix() != CONNECTOR_SUPERVISOR_ENTRYPOINT:
                adapter_errors.append(
                    {
                        "target": f"{domain_id}::{subdomain_id}",
                        "reason": "entrypoint must use connector supervisor",
                        "entrypoint": executable,
                    }
                )
    diagnostics.append(
        {
            "id": "doctor:external_command_entrypoints_resolve",
            "status": "fail" if adapter_errors else "pass",
            "desc": "online agent subdomains route live execution through the connector supervisor",
            "adapter_errors": adapter_errors,
        }
    )

    system_config = store["system"].get("config", {})
    registry_externalized = "subsystems" not in store["system"] and bool(system_config.get("subsystems"))
    diagnostics.append(
        {
            "id": "doctor:subsystem_registry_externalized",
            "status": "pass" if registry_externalized else "fail",
            "desc": "system config points to a subsystem registry instead of inlining subsystem membership",
            "registry_file": as_project_path(root, store["subsystem_registry_file"]),
            "inline_subsystems_present": "subsystems" in store["system"],
        }
    )

    registry_ref_errors: list[dict[str, Any]] = []
    ref_ids: list[str] = []
    for ref in store["subsystem_refs"]:
        ref_id = ref.get("id")
        if not ref_id:
            registry_ref_errors.append({"reason": "missing id", "ref": ref})
            continue
        ref_ids.append(str(ref_id))
        subsystem = subsystem_by_id(store, str(ref_id))
        if not subsystem:
            registry_ref_errors.append({"id": ref_id, "reason": "loaded subsystem id mismatch"})
    duplicate_ref_ids = sorted({ref_id for ref_id in ref_ids if ref_ids.count(ref_id) > 1})
    for ref_id in duplicate_ref_ids:
        registry_ref_errors.append({"id": ref_id, "reason": "duplicate registry id"})
    diagnostics.append(
        {
            "id": "doctor:subsystem_registry_refs_resolve",
            "status": "fail" if registry_ref_errors else "pass",
            "desc": "subsystem registry entries resolve to loaded subsystem definitions",
            "registry_ref_errors": registry_ref_errors,
        }
    )

    root_discovery_errors: list[dict[str, Any]] = []
    root_actions = store.get("subsystem_registry", {}).get("root_discovery", {}).get("actions", {})
    for action_name, config in root_actions.items():
        if not isinstance(config, dict):
            root_discovery_errors.append({"action": action_name, "reason": "action config is not a map"})
            continue
        source_subsystem = config.get("from_subsystem")
        source_action = config.get("from_action", action_name)
        subsystem = subsystem_by_id(store, str(source_subsystem)) if source_subsystem else None
        if not subsystem:
            root_discovery_errors.append(
                {"action": action_name, "reason": "from_subsystem does not resolve", "from_subsystem": source_subsystem}
            )
            continue
        if source_action not in subsystem.get("discovery", {}).get("actions", {}):
            root_discovery_errors.append(
                {
                    "action": action_name,
                    "reason": "from_action does not resolve",
                    "from_subsystem": source_subsystem,
                    "from_action": source_action,
                }
            )
    diagnostics.append(
        {
            "id": "doctor:root_discovery_actions_resolve",
            "status": "fail" if root_discovery_errors else "pass",
            "desc": "root discovery affordances resolve through the subsystem registry",
            "root_discovery_errors": root_discovery_errors,
        }
    )

    configured = configured_command_names(store)
    handled = handled_commands | set(command_aliases(store).keys())
    unhandled = sorted(name for name in configured if canonical_command(store, name) not in handled)
    diagnostics.append(
        {
            "id": "doctor:configured_commands_have_handlers",
            "status": "fail" if unhandled else "pass",
            "desc": "configured xctx commands map to protocol handlers",
            "unhandled_commands": unhandled,
        }
    )

    all_ids: list[str] = []
    for collection in store["collections"].values():
        all_ids.extend(str(record["id"]) for record in collection["records"] if "id" in record)
    duplicate_ids = sorted({item_id for item_id in all_ids if all_ids.count(item_id) > 1})
    diagnostics.append(
        {
            "id": "doctor:ids_unique",
            "status": "fail" if duplicate_ids else "pass",
            "desc": "all collection ids are unique",
            "duplicate_ids": duplicate_ids,
        }
    )

    lookup_ids: list[str] = []
    for collection in store["collections"].values():
        for record in collection["records"]:
            lookup_value = record_lookup_id(collection, record)
            if lookup_value is not None:
                lookup_ids.append(str(lookup_value))
    duplicate_lookup_ids = sorted({item_id for item_id in lookup_ids if lookup_ids.count(item_id) > 1})
    diagnostics.append(
        {
            "id": "doctor:configured_lookup_ids_unique",
            "status": "fail" if duplicate_lookup_ids else "pass",
            "desc": "all configured lookup ids are unique",
            "duplicate_lookup_ids": duplicate_lookup_ids,
        }
    )

    bad_refs: list[dict[str, Any]] = []
    for collection in store["collections"].values():
        for join in collection["spec"].get("observe", {}).get("joins", {}).values():
            target = resolve_collection(store, join["collection"], collection["subsystem_id"])
            target_values = {record.get(join.get("foreign_field", "id")) for record in target["records"]}
            for record in collection["records"]:
                local_value = record.get(join["local_field"])
                if local_value not in target_values:
                    bad_refs.append(
                        {
                            "collection": collection["name"],
                            "id": record.get("id"),
                            "field": join["local_field"],
                            "value": local_value,
                        }
                    )
    diagnostics.append(
        {
            "id": "doctor:configured_joins_resolve",
            "status": "fail" if bad_refs else "pass",
            "desc": "configured observe joins resolve to known records",
            "bad_refs": bad_refs,
        }
    )

    min_system_count = int(store.get("universe", {}).get("expectations", {}).get("min_system_count", 1))
    diagnostics.append(
        {
            "id": "doctor:multi_system_universe_present",
            "status": "pass" if len(store.get("all_systems", [])) >= min_system_count else "fail",
            "desc": "universe contains multiple top-level systems for future expansion",
            "system_count": len(store.get("all_systems", [])),
            "min_system_count": min_system_count,
        }
    )
    diagnostics.append(
        {
            "id": "doctor:subsystem_sections_externalized",
            "status": "pass" if all(sub.get("_section_files") for sub in store["subsystems"]) else "fail",
            "desc": "subsystem data/discovery/relationship sections are external files",
        }
    )
    return diagnostics
