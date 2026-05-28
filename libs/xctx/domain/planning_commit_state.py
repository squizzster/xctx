"""Commit execution claim state helpers for planned-effect execution."""

from __future__ import annotations

import os
import secrets
import socket
from datetime import timedelta
from typing import Any

from xctx.store.runtime_artifacts import (
    isoformat_utc,
    parse_utc_timestamp,
    utc_now,
    write_commit_execution_claim,
)


RUNNING_CLAIM_STALE_SECONDS = 3600
TERMINAL_CLAIM_STATUSES = frozenset({"succeeded", "failed"})


def claim_owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(8)}"


def new_execution_claim(
    *,
    plan: dict[str, Any],
    receipt: str,
    commit_id: str,
    result_id: str,
    current_context_sha: str | None,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "object_type": "commit_execution_claim",
        "plan_id": plan.get("plan_id"),
        "commit_id": commit_id,
        "result_id": result_id,
        "receipt_sha256": receipt,
        "owner_id": claim_owner_id(),
        "claim_nonce": secrets.token_hex(32),
        "config_fingerprint": current_context_sha,
        "status": "claimed",
        "claimed_at": isoformat_utc(now),
        "started_at": None,
        "heartbeat_at": isoformat_utc(now),
        "completed_at": None,
        "recovery_policy": "never_reinvoke_adapter_without_operator_repair",
    }


def claim_status(claim: dict[str, Any] | None) -> str:
    return str((claim or {}).get("status") or "").strip().lower()


def claim_is_stale(claim: dict[str, Any], *, now: Any | None = None) -> bool:
    heartbeat = parse_utc_timestamp(claim.get("heartbeat_at")) or parse_utc_timestamp(claim.get("claimed_at"))
    if heartbeat is None:
        return True
    current = now or utc_now()
    return current - heartbeat > timedelta(seconds=RUNNING_CLAIM_STALE_SECONDS)


def mark_claim_abandoned_if_stale(store: dict[str, Any], receipt: str, claim: dict[str, Any]) -> dict[str, Any]:
    status = claim_status(claim)
    if status in TERMINAL_CLAIM_STATUSES or not claim_is_stale(claim):
        return claim
    now = isoformat_utc(utc_now())
    abandoned = {
        **claim,
        "status": "abandoned",
        "abandoned_at": now,
        "heartbeat_at": now,
        "recovery_policy": "operator_repair_required_before_reinvoke",
    }
    write_commit_execution_claim(store, receipt, abandoned)
    return abandoned
