"""Plan materialization manifest helpers for planned-effect execution."""

from __future__ import annotations

from typing import Any

from xctx.store.runtime_artifacts import (
    isoformat_utc,
    read_runtime_artifact,
    runtime_artifact_ref,
    utc_now,
    write_runtime_artifact,
)


def plan_manifest_id(receipt: str) -> str:
    return runtime_artifact_ref("plan_manifest", receipt)


def plan_materialization_manifest(
    *,
    plan_id: str,
    receipt: str,
    master_plan_id: str,
    sub_plan_id: str,
    commit_id: str,
    result_id: str,
) -> dict[str, Any]:
    published_at = isoformat_utc(utc_now())
    return {
        "object_type": "plan_materialization_manifest",
        "schema_version": "xctx.plan_materialization.v1",
        "status": "complete",
        "plan_id": plan_id,
        "receipt_sha256": receipt,
        "manifest_id": plan_manifest_id(receipt),
        "published_at": published_at,
        "artifacts": {
            "master_plan": master_plan_id,
            "sub_plan": sub_plan_id,
            "expected_commit": commit_id,
            "expected_result": result_id,
        },
        "publish_order": ["master_plan", "sub_plan", "plan_manifest", "plan_record"],
    }


def write_plan_materialization_bundle(
    store: dict[str, Any],
    *,
    receipt: str,
    master_plan: dict[str, Any],
    sub_plan: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    write_runtime_artifact(store, "master_plan", receipt, master_plan)
    write_runtime_artifact(store, "sub_plan", receipt, sub_plan)
    write_runtime_artifact(store, "plan_manifest", receipt, manifest)


def verify_plan_materialization(
    store: dict[str, Any],
    plan: dict[str, Any],
    receipt: str,
) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    materialized = plan.get("materialized_artifacts")
    if not isinstance(materialized, dict):
        errors.append("plan_missing_materialized_artifacts")
        materialized = {}
    expected_manifest_id = plan_manifest_id(receipt)
    if materialized.get("status") != "complete":
        errors.append("plan_materialization_not_complete")
    if materialized.get("manifest_id") != expected_manifest_id:
        errors.append("plan_manifest_ref_mismatch")

    manifest = read_runtime_artifact(store, "plan_manifest", receipt)
    master_plan = read_runtime_artifact(store, "master_plan", receipt)
    sub_plan = read_runtime_artifact(store, "sub_plan", receipt)
    if manifest is None:
        errors.append("missing_plan_manifest")
    if master_plan is None:
        errors.append("missing_master_plan")
    if sub_plan is None:
        errors.append("missing_sub_plan")
    if manifest is not None:
        if manifest.get("object_type") != "plan_materialization_manifest":
            errors.append("invalid_plan_manifest_object_type")
        if manifest.get("status") != "complete":
            errors.append("plan_manifest_not_complete")
        if manifest.get("plan_id") != plan.get("plan_id"):
            errors.append("plan_manifest_plan_id_mismatch")
        if manifest.get("receipt_sha256") != receipt:
            errors.append("plan_manifest_receipt_mismatch")
        artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
        if artifacts.get("master_plan") != plan.get("master_plan_id"):
            errors.append("plan_manifest_master_plan_mismatch")
        if artifacts.get("sub_plan") != plan.get("sub_plan_id"):
            errors.append("plan_manifest_sub_plan_mismatch")
        if artifacts.get("expected_commit") != plan.get("expected_commit_id"):
            errors.append("plan_manifest_expected_commit_mismatch")
        if artifacts.get("expected_result") != plan.get("expected_result_id"):
            errors.append("plan_manifest_expected_result_mismatch")
    if master_plan is not None:
        if master_plan.get("master_plan_id") != plan.get("master_plan_id"):
            errors.append("master_plan_id_mismatch")
        if master_plan.get("plan_id") != plan.get("plan_id"):
            errors.append("master_plan_plan_id_mismatch")
    if sub_plan is not None:
        if sub_plan.get("sub_plan_id") != plan.get("sub_plan_id"):
            errors.append("sub_plan_id_mismatch")
        if sub_plan.get("plan_id") != plan.get("plan_id"):
            errors.append("sub_plan_plan_id_mismatch")
    return not errors, master_plan, sub_plan, manifest, errors
