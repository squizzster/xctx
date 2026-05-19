"""Path helpers for project-root-relative xctx configuration."""

from __future__ import annotations

from pathlib import Path


def project_root_from_module() -> Path:
    """Return the project root for the installed-in-place workspace layout."""
    return Path(__file__).resolve().parents[3]


def as_project_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())
