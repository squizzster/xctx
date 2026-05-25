"""Path helpers for workspace-root-relative xctx configuration."""

from __future__ import annotations

from pathlib import Path


def _is_workspace_root(path: Path) -> bool:
    return (path / "yaml_dynamic_config").exists() and (path / "data").exists()


def project_root_from_module(module_file: str | Path | None = None) -> Path:
    """Return the workspace root for source-tree and installed package layouts."""
    path = Path(module_file).resolve() if module_file is not None else Path(__file__).resolve()
    for candidate in path.parents:
        if _is_workspace_root(candidate):
            return candidate
        installed_workspace = candidate / "xctx_workspace"
        if _is_workspace_root(installed_workspace):
            return installed_workspace
    return path.parents[3]


def as_project_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())
