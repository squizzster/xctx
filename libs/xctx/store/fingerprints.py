"""Deterministic fingerprints for the loaded xctx operating surface.

The plan ledger is useful only when an execute request can prove it is bound to
what was rehearsed. These helpers compute a stable digest of the loaded protocol
configuration, independent of file mtimes, so stale plans can be detected without
peeking into domain-specific business state.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from xctx.config.paths import as_project_path
from xctx.protocol.accessors import protocol_version


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_snapshot(root: Path, path: Path) -> dict[str, Any]:
    """Return a stable snapshot entry for one loaded config file."""

    try:
        data = path.read_bytes()
    except OSError:
        return {
            "path": as_project_path(root, path),
            "available": False,
            "sha256": None,
            "size_bytes": None,
        }
    return {
        "path": as_project_path(root, path),
        "available": True,
        "sha256": _sha256_bytes(data),
        "size_bytes": len(data),
    }


def config_file_snapshots(store: dict[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic snapshots for the YAML files loaded into the store."""

    root = Path(store["root"])
    paths = [Path(path) for path in store.get("config_files", [])]
    return [_file_snapshot(root, path) for path in sorted(paths, key=lambda item: as_project_path(root, item))]


def config_fingerprint_payload(store: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical fingerprint object for the loaded protocol surface."""

    files = config_file_snapshots(store)
    material = {
        "protocol_version": protocol_version(store),
        "config_files": files,
    }
    digest = _sha256_bytes(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return {
        "algorithm": "sha256",
        "sha256": digest,
        "protocol_version": protocol_version(store),
        "config_file_count": len(files),
        "config_files": files,
    }


def config_fingerprint(store: dict[str, Any]) -> str:
    """Return only the sha256 digest for quick equality checks."""

    return str(config_fingerprint_payload(store)["sha256"])
