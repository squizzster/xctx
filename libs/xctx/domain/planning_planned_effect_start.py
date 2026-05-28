"""Startup transitions for planned-effect execution."""

from __future__ import annotations

from typing import Any

from xctx.domain.planning_execution import (
    materialized_artifact_committing,
    running_execution_artifacts,
)
from xctx.store.runtime_artifacts import (
    isoformat_utc,
    utc_now,
    write_commit_execution_claim,
    write_runtime_artifact,
)


def publish_running_execution_artifacts(
    *,
    store: dict[str, Any],
    receipt: str,
    canonical_plan_id: str,
    commit_id: str,
    result_id: str,
    planned_effect: dict[str, Any],
    master_plan: dict[str, Any],
    sub_plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    commit, running_result = running_execution_artifacts(
        canonical_plan_id=canonical_plan_id,
        commit_id=commit_id,
        result_id=result_id,
        planned_effect=planned_effect,
        now=utc_now(),
    )
    write_runtime_artifact(store, "commit", receipt, commit)
    write_runtime_artifact(store, "result", receipt, running_result)
    write_runtime_artifact(
        store,
        "master_plan",
        receipt,
        materialized_artifact_committing(
            master_plan,
            commit_id=commit_id,
            result_id=result_id,
            committed_at=running_result["created_at"],
        ),
    )
    write_runtime_artifact(
        store,
        "sub_plan",
        receipt,
        materialized_artifact_committing(
            sub_plan,
            commit_id=commit_id,
            result_id=result_id,
            committed_at=running_result["created_at"],
        ),
    )
    return commit, running_result


def mark_execution_started(
    *,
    store: dict[str, Any],
    receipt: str,
    commit: dict[str, Any],
    claim: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = isoformat_utc(utc_now())
    running_commit = {**commit, "status": "running"}
    write_runtime_artifact(store, "commit", receipt, running_commit)
    running_claim = {**claim, "status": "running", "started_at": started, "heartbeat_at": started}
    write_commit_execution_claim(store, receipt, running_claim)
    return running_commit, running_claim
