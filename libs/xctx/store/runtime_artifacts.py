"""Protocol-local runtime artifacts for planned effects.

These artifacts are xctx ledger state, not domain/business state. Domain packs
own payload meaning behind the connector boundary; this module owns only
generic artifact refs, storage, and result expiry shape.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xctx.errors import XctxError


HEX_DIGITS = set("0123456789abcdef")
FULL_SHA256_LENGTH = 64
ARTIFACT_KINDS = frozenset({"master_plan", "sub_plan", "commit", "result"})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def is_sha256_hex(value: str) -> bool:
    return len(value) == FULL_SHA256_LENGTH and all(ch in HEX_DIGITS for ch in value)


def runtime_root(store: dict[str, Any]) -> Path:
    root = Path(store["root"])
    configured = os.environ.get("XCTX_RUNTIME_DIR")
    runtime = Path(configured) if configured else root / ".xctx_runtime"
    if not runtime.is_absolute():
        runtime = root / runtime
    return runtime


def runtime_artifact_dir(store: dict[str, Any], kind: str) -> Path:
    if kind not in ARTIFACT_KINDS:
        raise ValueError(f"unsupported runtime artifact kind: {kind}")
    return runtime_root(store) / kind


def runtime_artifact_ref(kind: str, digest: str) -> str:
    if kind not in ARTIFACT_KINDS:
        raise ValueError(f"unsupported runtime artifact kind: {kind}")
    normalized = digest.lower()
    if not is_sha256_hex(normalized):
        raise ValueError(f"{kind} artifact digest must be a 64-character lowercase sha256 hex")
    return f"{kind}:{normalized}"


def _artifact_path(store: dict[str, Any], kind: str, digest: str) -> Path:
    normalized = digest.lower()
    if not is_sha256_hex(normalized):
        raise ValueError(f"{kind} artifact digest must be a 64-character lowercase sha256 hex")
    return runtime_artifact_dir(store, kind) / f"{normalized}.json"


def write_runtime_artifact(store: dict[str, Any], kind: str, digest: str, payload: dict[str, Any]) -> None:
    path = _artifact_path(store, kind, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_runtime_artifact(store: dict[str, Any], kind: str, digest: str) -> dict[str, Any] | None:
    try:
        path = _artifact_path(store, kind, digest)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def extract_runtime_ref(kind: str, value: str) -> str | None:
    prefix = f"{kind}:"
    raw = value.strip().lower()
    if not raw.startswith(prefix):
        return None
    digest = raw[len(prefix) :]
    return digest if is_sha256_hex(digest) else None


def is_runtime_ref(kind: str, value: str | None) -> bool:
    return bool(value and str(value).strip().lower().startswith(f"{kind}:"))


def read_runtime_ref(store: dict[str, Any], kind: str, value: str) -> dict[str, Any] | None:
    digest = extract_runtime_ref(kind, value)
    if not digest:
        return None
    return read_runtime_artifact(store, kind, digest)


def result_observation_payload(store: dict[str, Any], result_ref: str) -> dict[str, Any]:
    if not is_runtime_ref("result", result_ref):
        raise XctxError("invalid result reference", next_moves=["./xctx observe result:<sha256>"])
    digest = extract_runtime_ref("result", result_ref)
    if not digest:
        raise XctxError("invalid result reference", next_moves=["./xctx observe result:<sha256>"])
    result = read_runtime_artifact(store, "result", digest)
    if result is None:
        raise XctxError("unknown result reference", next_moves=["./xctx plan <operation> <target>"])

    observed = dict(result)
    now = utc_now()
    expires_at = parse_utc_timestamp(observed.get("expires_at"))
    if expires_at is not None and now >= expires_at and observed.get("status") != "expired":
        observed["status"] = "expired"
        observed["expired_at"] = isoformat_utc(now)
        observed["payload"] = None
        observed["heartbeat_at"] = isoformat_utc(now)
        observed["heartbeat"] = {
            "phase": "expired",
            "message": "Result handle has expired; payload is no longer available.",
        }
    observed.setdefault("result_id", runtime_artifact_ref("result", digest))
    observed["observed_at"] = isoformat_utc(now)
    return observed


def runtime_artifact_discovery_payload(store: dict[str, Any], artifact_ref: str) -> dict[str, Any]:
    for kind in sorted(ARTIFACT_KINDS):
        digest = extract_runtime_ref(kind, artifact_ref)
        if not digest:
            continue
        payload = read_runtime_artifact(store, kind, digest)
        if payload is None:
            raise XctxError(
                f"unknown runtime artifact: {artifact_ref}",
                next_moves=["./xctx discover", "./xctx plan <operation> <target>"],
            )
        discovered = dict(payload)
        discovered.setdefault(f"{kind}_id", runtime_artifact_ref(kind, digest))
        discovered["artifact_ref"] = runtime_artifact_ref(kind, digest)
        discovered["artifact_kind"] = kind
        discovered["discovered_at"] = isoformat_utc(utc_now())
        return discovered
    raise XctxError("invalid runtime artifact reference", next_moves=["./xctx discover master_plan:<sha256>"])
