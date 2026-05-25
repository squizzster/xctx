"""Load the xctx YAML universe into an in-memory store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xctx.config.includes import require_config
from xctx.config.paths import as_project_path, project_root_from_module
from xctx.config.validation import validate_loaded_store, validate_universe_shape
from xctx.errors import XctxError
from xctx.io.yaml_io import load_yaml


def _resolve(base: Path, maybe_relative: str) -> Path:
    path = Path(maybe_relative)
    return path if path.is_absolute() else base / path


def _resolve_workspace_config(root: Path, base: Path, maybe_relative: str, *, label: str) -> Path:
    """Resolve a YAML include and ensure it stays inside the workspace root."""

    candidate = _resolve(base, maybe_relative).resolve()
    workspace = root.resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise XctxError(f"next valid move: keep {label} inside the xctx workspace")
    return candidate


def _load_agent_domains(
    root: Path,
    config_dir: Path,
    universe: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    domains: dict[str, dict[str, Any]] = {}
    config_files: list[Path] = []
    for ref in universe.get("agent_domains", []) or []:
        domain_id = str(require_config(ref, "id", "yaml_dynamic_config/universe.yaml"))
        if domain_id in domains:
            raise XctxError(f"next valid move: remove duplicate agent_domain id {domain_id}")
        domain_file = _resolve_workspace_config(
            root,
            config_dir,
            str(require_config(ref, "path", "yaml_dynamic_config/universe.yaml")),
            label=f"agent_domain {domain_id} path",
        )
        domain = load_yaml(domain_file)
        configured_domain_id = str(domain.get("id", domain_id))
        if configured_domain_id != domain_id:
            raise XctxError(f"next valid move: align agent_domain id {configured_domain_id} with universe id {domain_id}")
        domain.setdefault("id", domain_id)
        domain["_config_path"] = as_project_path(root, domain_file)
        domain["_dir"] = domain_file.parent
        domain["_universe_ref"] = ref
        config_files.append(domain_file)

        subdomains: dict[str, dict[str, Any]] = {}
        for subdomain_id, sub_ref in (domain.get("agent_subdomains") or {}).items():
            subdomain_file = _resolve_workspace_config(
                root,
                domain_file.parent,
                str(require_config(sub_ref, "path", domain["_config_path"])),
                label=f"agent_subdomain {domain_id}::{subdomain_id} path",
            )
            subdomain = load_yaml(subdomain_file)
            configured_subdomain_id = str(subdomain.get("id", str(subdomain_id)))
            if configured_subdomain_id != str(subdomain_id):
                raise XctxError(
                    "next valid move: align agent_subdomain id "
                    f"{configured_subdomain_id} with domain ref {domain_id}::{subdomain_id}"
                )
            subdomain.setdefault("id", str(subdomain_id))
            subdomain["_config_path"] = as_project_path(root, subdomain_file)
            subdomain["_dir"] = subdomain_file.parent
            subdomain["_domain_id"] = domain["id"]
            subdomain["_domain_ref"] = sub_ref
            subdomain["_priority"] = sub_ref.get("priority", 9999)
            subdomains[subdomain["id"]] = subdomain
            config_files.append(subdomain_file)

        domain["_subdomains"] = subdomains
        domains[domain["id"]] = domain
    return domains, config_files


def load_store(root: Path | None = None) -> dict[str, Any]:
    """Load the YAML-backed xctx store."""

    root = (root or project_root_from_module()).resolve()
    config_dir = root / "yaml_dynamic_config"
    universe_file = config_dir / "universe.yaml"
    universe = load_yaml(universe_file)
    validate_universe_shape(universe)

    protocol_ref = require_config(universe, "protocol", as_project_path(root, universe_file))
    protocol_file = _resolve_workspace_config(root, config_dir, str(protocol_ref), label="protocol config")
    protocol = load_yaml(protocol_file)

    agent_domains, agent_domain_config_files = _load_agent_domains(root, config_dir, universe)

    commands_ref = require_config(universe, "commands", as_project_path(root, universe_file))
    commands_file = _resolve_workspace_config(root, config_dir, str(commands_ref), label="command-set config")
    commands = load_yaml(commands_file)

    config_files: list[Path] = [universe_file, protocol_file, commands_file, *agent_domain_config_files]

    store = {
        "root": root,
        "config_dir": config_dir,
        "universe_file": universe_file,
        "universe": universe,
        "agent_domains": agent_domains,
        "agent_domains_by_id": agent_domains,
        "protocol_file": protocol_file,
        "protocol": protocol,
        "commands_file": commands_file,
        "commands": commands,
        "config_files": sorted(set(config_files)),
    }
    validate_loaded_store(store)
    return store
