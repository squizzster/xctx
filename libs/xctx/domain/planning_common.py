"""Common plan ledger hashing and context helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from xctx.store.fingerprints import config_fingerprint_payload


def receipt_for_payload(payload: dict[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def plan_context(store: dict[str, Any]) -> dict[str, Any]:
    fingerprint = config_fingerprint_payload(store)
    return {
        "config_sha256": fingerprint["sha256"],
        "protocol_version": fingerprint["protocol_version"],
        "config_file_count": fingerprint["config_file_count"],
        "fingerprint_algorithm": fingerprint["algorithm"],
    }
