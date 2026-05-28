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
PLAN_RECEIPT_PREFIX = "plan:sha256:"
REQUIRED_PLAN_KEYS = frozenset({"plan_id", "receipt_sha256", "planner_id", "operation", "status"})


@dataclass(frozen=True)
class ResolvedPlan:
    ok: bool
    error: str | None
    requested_plan: str
    plan: dict[str, Any] | None
    matches: list[str]


@dataclass(frozen=True)
class PlanRef:
    ok: bool
    error: str | None
    requested: str
    receipt_sha256: str | None


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


def parse_plan_ref(value: str) -> PlanRef:
    """Parse the only executable plan reference form.

    Short receipts and raw sha256 values are useful debug identifiers, but the
    execute contract requires the explicit ``plan:sha256:<digest>`` bearer id.
    """

    requested = value.strip()
    lowered = requested.lower()
    if not lowered.startswith(PLAN_RECEIPT_PREFIX):
        return PlanRef(False, "plan_id_required", requested, None)
    receipt = lowered[len(PLAN_RECEIPT_PREFIX) :]
    if not _is_hex(receipt, length=FULL_RECEIPT_LENGTH):
        return PlanRef(False, "invalid_plan_receipt", requested, None)
    return PlanRef(True, None, requested, receipt)


def resolve_plan(store: dict[str, Any], value: str) -> ResolvedPlan:
    parsed = parse_plan_ref(value)
    if not parsed.ok or not parsed.receipt_sha256:
        return ResolvedPlan(False, parsed.error or "invalid_plan_receipt", parsed.requested, None, [])
    plan = read_plan(store, parsed.receipt_sha256)
    if plan is None:
        return ResolvedPlan(False, "unknown_plan_receipt", parsed.requested, None, [])
    return ResolvedPlan(True, None, parsed.requested, plan, [parsed.receipt_sha256])
