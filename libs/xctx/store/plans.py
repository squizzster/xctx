"""Runtime plan ledger for binding xctx plan receipts to execute.

The ledger is intentionally local to the project checkout. It is not domain state
and it does not mutate any business data; it records the exact non-mutating plan
material that xctx emitted so execute can distinguish a real receipt from a
string that merely looks like one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResolvedPlan:
    ok: bool
    error: str | None
    requested_plan: str
    plan: dict[str, Any] | None
    matches: list[str]


def plan_store_dir(store: dict[str, Any]) -> Path:
    root = Path(store["root"])
    return root / ".xctx_runtime" / "plans"


def _plan_path(store: dict[str, Any], receipt_sha256: str) -> Path:
    return plan_store_dir(store) / f"{receipt_sha256}.json"


def write_plan(store: dict[str, Any], plan: dict[str, Any]) -> None:
    receipt = str(plan["receipt_sha256"])
    directory = plan_store_dir(store)
    directory.mkdir(parents=True, exist_ok=True)
    path = _plan_path(store, receipt)
    # Atomic enough for this local PoC and portable without extra deps.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_plan(store: dict[str, Any], receipt_sha256: str) -> dict[str, Any] | None:
    path = _plan_path(store, receipt_sha256.lower())
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if str(payload.get("receipt_sha256", "")).lower() != receipt_sha256.lower():
        return None
    return payload


def _known_receipts(store: dict[str, Any]) -> list[str]:
    directory = plan_store_dir(store)
    if not directory.exists():
        return []
    receipts: list[str] = []
    for path in directory.glob("*.json"):
        stem = path.stem.lower()
        if len(stem) == 64 and all(ch in "0123456789abcdef" for ch in stem):
            receipts.append(stem)
    return sorted(receipts)


def _extract_receipt(value: str) -> tuple[str | None, str]:
    requested = value.strip()
    lowered = requested.lower()
    prefix = "plan:sha256:"
    if lowered.startswith(prefix):
        return lowered[len(prefix) :], requested
    return lowered, requested


def resolve_plan(store: dict[str, Any], value: str) -> ResolvedPlan:
    extracted, requested = _extract_receipt(value)
    if not extracted:
        return ResolvedPlan(False, "invalid_plan_receipt", requested, None, [])

    if len(extracted) == 64 and all(ch in "0123456789abcdef" for ch in extracted):
        plan = read_plan(store, extracted)
        if plan is None:
            return ResolvedPlan(False, "unknown_plan_receipt", requested, None, [])
        return ResolvedPlan(True, None, requested, plan, [extracted])

    if len(extracted) == 5 and all(ch in "0123456789abcdef" for ch in extracted):
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
