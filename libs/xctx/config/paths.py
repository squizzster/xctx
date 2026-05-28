"""Path helpers for workspace-root-relative xctx configuration."""

from __future__ import annotations

import os
from pathlib import Path

from xctx.errors import XctxError


def _is_workspace_root(path: Path) -> bool:
    return (path / "yaml_dynamic_config").exists() and (path / "data").exists()


def _workspace_override() -> Path | None:
    raw = os.environ.get("XCTX_WORKSPACE")
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    if not _is_workspace_root(path):
        raise XctxError(f"XCTX_WORKSPACE is not an xctx workspace root: {path}")
    return path


def project_root_from_module(module_file: str | Path | None = None) -> Path:
    """Return the workspace root for source-tree and installed package layouts."""
    override = _workspace_override()
    if override is not None:
        return override
    path = Path(module_file).resolve() if module_file is not None else Path(__file__).resolve()
    for candidate in path.parents:
        if _is_workspace_root(candidate):
            return candidate
        installed_workspace = candidate / "xctx_workspace"
        if _is_workspace_root(installed_workspace):
            return installed_workspace
    raise XctxError("could not locate xctx workspace root; set XCTX_WORKSPACE to a valid workspace")


def as_project_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())
