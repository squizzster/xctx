"""Runtime plan ledger for binding xctx plan receipts to execute.

The ledger is protocol-local evidence, not domain/business state. Set
``XCTX_RUNTIME_DIR`` to keep runtime artifacts outside the checkout or isolate
tests and subprocess smoke runs.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HEX_DIGITS = set("0123456789abcdef")
FULL_RECEIPT_LENGTH = 64
SHORT_RECEIPT_LENGTH = 5
PLAN_RECEIPT_PREFIX = "plan:sha256:"
REQUIRED_PLAN_KEYS = frozenset({"plan_id", "receipt_sha256", "planner_id", "operation", "status"})


@dataclass(frozen=True)
class ResolvedPlan:
    ok: bool
    error: str | None
    requested_plan: str
    plan: dict[str, Any] | None
    matches: list[str]


def _is_hex(value: str, *, length: int) -> bool:
    return len(value) == length and all(ch in HEX_DIGITS for ch in value)


def plan_store_dir(store: dict[str, Any]) -> Path:
    root = Path(store["root"])
    configured = os.environ.get("XCTX_RUNTIME_DIR")
    runtime_root = Path(configured) if configured else root / ".xctx_runtime"
    if not runtime_root.is_absolute():
        runtime_root = root / runtime_root
    return runtime_root / "plans"


def _plan_path(store: dict[str, Any], receipt_sha256: str) -> Path:
    return plan_store_dir(store) / f"{receipt_sha256}.json"


def canonical_plan_id(receipt_sha256: str) -> str:
    return f"{PLAN_RECEIPT_PREFIX}{receipt_sha256}"


def validate_plan_record(plan: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate the generic ledger shape for a loaded plan record."""

    missing = sorted(REQUIRED_PLAN_KEYS - set(plan))
    if missing:
        return False, f"missing_plan_keys:{','.join(missing)}"
    receipt = str(plan.get("receipt_sha256", "")).lower()
    if not _is_hex(receipt, length=FULL_RECEIPT_LENGTH):
        return False, "invalid_receipt_sha256"
    if str(plan.get("planner_id", "")).lower() != receipt:
        return False, "planner_id_receipt_mismatch"
    if str(plan.get("plan_id")) != canonical_plan_id(receipt):
        return False, "plan_id_receipt_mismatch"
    return True, None


def write_plan(store: dict[str, Any], plan: dict[str, Any]) -> None:
    receipt = str(plan["receipt_sha256"]).lower()
    if not _is_hex(receipt, length=FULL_RECEIPT_LENGTH):
        raise ValueError("plan receipt_sha256 must be a 64-character lowercase hex digest")
    ok, reason = validate_plan_record(plan)
    if not ok:
        raise ValueError(f"invalid xctx plan record: {reason}")
    directory = plan_store_dir(store)
    directory.mkdir(parents=True, exist_ok=True)
    path = _plan_path(store, receipt)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_plan(store: dict[str, Any], receipt_sha256: str) -> dict[str, Any] | None:
    normalized = receipt_sha256.lower()
    if not _is_hex(normalized, length=FULL_RECEIPT_LENGTH):
        return None
    path = _plan_path(store, normalized)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("receipt_sha256", "")).lower() != normalized:
        return None
    ok, _reason = validate_plan_record(payload)
    return payload if ok else None


def _known_receipts(store: dict[str, Any]) -> list[str]:
    directory = plan_store_dir(store)
    if not directory.exists():
        return []
    receipts: list[str] = []
    for path in directory.glob("*.json"):
        stem = path.stem.lower()
        if _is_hex(stem, length=FULL_RECEIPT_LENGTH):
            receipts.append(stem)
    return sorted(receipts)


def _extract_receipt(value: str) -> tuple[str | None, str]:
    requested = value.strip()
    lowered = requested.lower()
    if lowered.startswith(PLAN_RECEIPT_PREFIX):
        return lowered[len(PLAN_RECEIPT_PREFIX) :], requested
    return lowered, requested


def resolve_plan(store: dict[str, Any], value: str) -> ResolvedPlan:
    extracted, requested = _extract_receipt(value)
    if not extracted:
        return ResolvedPlan(False, "invalid_plan_receipt", requested, None, [])

    if _is_hex(extracted, length=FULL_RECEIPT_LENGTH):
        plan = read_plan(store, extracted)
        if plan is None:
            return ResolvedPlan(False, "unknown_plan_receipt", requested, None, [])
        return ResolvedPlan(True, None, requested, plan, [extracted])

    if _is_hex(extracted, length=SHORT_RECEIPT_LENGTH):
        matches = [receipt for receipt in _known_receipts(store) if receipt.startswith(extracted)]
        if not matches:
            return ResolvedPlan(False, "unknown_plan_receipt", requested, None, [])
        if len(matches) > 1:
            return ResolvedPlan(False, "ambiguous_plan_receipt", requested, None, matches)
        plan = read_plan(store, matches[0])
        if plan is None:
            return ResolvedPlan(False, "unknown_plan_receipt", requested, None, matches)
        return ResolvedPlan(True, None, requested, plan, matches)

    return ResolvedPlan(False, "invalid_plan_receipt", requested, None, [])
