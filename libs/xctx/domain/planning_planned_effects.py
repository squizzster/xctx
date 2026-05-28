"""Planned-effect plan construction for the xctx plan ledger."""

from __future__ import annotations

import secrets
from typing import Any

from xctx.config.paths import as_project_path
from xctx.domain.execution_contract import parse_plan_request
from xctx.domain.planning_common import plan_context, receipt_for_payload
from xctx.domain.planning_intent import PlannedAction, parse_planned_action_args, planning_default, render_template
from xctx.domain.planning_materialization import (
    plan_manifest_id,
    plan_materialization_manifest,
    write_plan_materialization_bundle,
)
from xctx.protocol.guidance import command_hints
from xctx.store.plans import plan_store_dir, write_plan
from xctx.store.runtime_artifacts import runtime_artifact_dir, runtime_artifact_ref


def planned_effect_plan_payload(args: list[str], store: dict[str, Any], planned: PlannedAction) -> dict[str, Any]:
    request = parse_plan_request(args)
    context = plan_context(store)
    action_args = list(request.raw_args[1:])
    parsed_args = parse_planned_action_args(store, planned, action_args)
    plan_material = {
        "protocol": "xctx.v4.2",
        "operation": request.operation_text,
        "operation_token": request.operation,
        "target": request.target,
        "surface": "planned_scoped_adapter_effect",
        "mutation_policy": "commit_required",
        "planner_context": context,
        "agent_domain": planned.domain_id,
        "agent_subdomain": planned.subdomain_id,
        "action": planned.action_name,
        "action_args": action_args,
        "parsed_values": parsed_args.values,
        "plan_nonce": secrets.token_hex(32),
    }
    receipt = receipt_for_payload(plan_material)
    plan_id = f"plan:sha256:{receipt}"
    materialization_manifest_id = plan_manifest_id(receipt)
    master_plan_id = runtime_artifact_ref("master_plan", receipt)
    sub_plan_id = runtime_artifact_ref("sub_plan", receipt)
    commit_id = runtime_artifact_ref("commit", receipt)
    result_id = runtime_artifact_ref("result", receipt)
    template_values = {
        **parsed_args.values,
        "agent_domain": planned.domain_id,
        "agent_subdomain": planned.subdomain_id,
        "action": planned.action_name,
        "plan_id": plan_id,
        "master_plan_id": master_plan_id,
        "sub_plan_id": sub_plan_id,
        "commit_id": commit_id,
        "result_id": result_id,
    }
    description = render_template(
        str(
            planned.planning.get("description_of_what_will_happen")
            or planned.action.get("desc")
            or "The scoped adapter effect will run after execute --commit and write a result handle."
        ),
        template_values,
    )
    commit_adapter_command = str(
        planned.planning.get("commit_adapter_command")
        or planned.action.get("entrypoint_command")
        or planned.action_name
    )
    ttl_seconds = int(planning_default(store, planned, "result_ttl_seconds", 300))
    planned_effect = {
        "kind": "scoped_adapter_commit",
        "agent_domain": planned.domain_id,
        "agent_subdomain": planned.subdomain_id,
        "action": planned.action_name,
        "domain_action_name": planned.domain_action_name,
        "implemented_by": f"{planned.domain_id}::{planned.subdomain_id}::{planned.action_name}",
        "commit_adapter_command": commit_adapter_command,
        "adapter_args": parsed_args.adapter_args,
        "input_values": parsed_args.values,
        "positional_args": parsed_args.positional_args,
        "writes_to_db": bool(planning_default(store, planned, "writes_to_db", False)),
        "can_be_reversed": bool(planning_default(store, planned, "can_be_reversed", False)),
        "can_be_repaired": bool(planning_default(store, planned, "can_be_repaired", False)),
        "result_ttl_seconds": ttl_seconds,
        "running_heartbeat": planned.planning.get("running_heartbeat") or {},
        "complete_heartbeat": planned.planning.get("complete_heartbeat") or {},
    }
    payload = {
        "operation": request.operation_text,
        "operation_token": request.operation,
        "target": request.target,
        "planner_id": receipt,
        "plan_id": plan_id,
        "materialization_manifest_id": materialization_manifest_id,
        "master_plan_id": master_plan_id,
        "sub_plan_id": sub_plan_id,
        "expected_commit_id": commit_id,
        "expected_result_id": result_id,
        "status": "planned_effect",
        "execution_status": "planned",
        "decision": "commit_required",
        "description": description,
        "description_of_what_will_happen": description,
        "writes_to_db": planned_effect["writes_to_db"],
        "can_be_reversed": planned_effect["can_be_reversed"],
        "can_be_repaired": planned_effect["can_be_repaired"],
        "receipt_sha256": receipt,
        "receipt_sha5": receipt[:5],
        "receipt_note": "receipt_sha5 is a debug prefix only; execute requires the canonical plan_id.",
        "planner_context": context,
        "planner_ledger": as_project_path(store["root"], plan_store_dir(store)),
        "runtime_artifact_ledger": {
            "master_plan": as_project_path(store["root"], runtime_artifact_dir(store, "master_plan")),
            "sub_plan": as_project_path(store["root"], runtime_artifact_dir(store, "sub_plan")),
            "plan_manifest": as_project_path(store["root"], runtime_artifact_dir(store, "plan_manifest")),
            "commit": as_project_path(store["root"], runtime_artifact_dir(store, "commit")),
            "result": as_project_path(store["root"], runtime_artifact_dir(store, "result")),
        },
        "materialized_artifacts": {
            "status": "complete",
            "manifest_id": materialization_manifest_id,
            "master_plan_id": master_plan_id,
            "sub_plan_id": sub_plan_id,
        },
        "planned_effect": planned_effect,
        "accepted_execute_cmd": f"./xctx execute {plan_id} --commit",
        "discover_master_plan_cmd": f"./xctx discover {master_plan_id}",
        "observe_result_cmd": f"./xctx observe {result_id}",
        "lawful_next_moves": command_hints(
            [
                f"./xctx discover {master_plan_id}",
                f"./xctx execute {plan_id} --commit",
                f"./xctx observe {result_id}",
                "./xctx audit root",
            ]
        ),
    }
    master_plan = {
        "master_plan_id": master_plan_id,
        "materialization_manifest_id": materialization_manifest_id,
        "plan_id": plan_id,
        "status": "planned",
        "execution_status": "planned",
        "human_masterplan": request.operation_text,
        "allowed_plans": [plan_id],
        "sub_plans": [sub_plan_id],
        "expected_commit_id": commit_id,
        "expected_result_id": result_id,
        "blocked_paths": planned.planning.get("blocked_paths") or [],
        "execute_plan_cmd": f"./xctx execute {plan_id} --commit",
        "observe_result_cmd": f"./xctx observe {result_id}",
        "lawful_next_moves": payload["lawful_next_moves"],
    }
    sub_plan = {
        "sub_plan_id": sub_plan_id,
        "materialization_manifest_id": materialization_manifest_id,
        "plan_id": plan_id,
        "master_plan_id": master_plan_id,
        "status": "planned",
        "execution_status": "planned",
        "expected_commit_id": commit_id,
        "expected_result_id": result_id,
        "planned_effect": planned_effect,
        "description_of_what_will_happen": description,
    }
    manifest = plan_materialization_manifest(
        plan_id=plan_id,
        receipt=receipt,
        master_plan_id=master_plan_id,
        sub_plan_id=sub_plan_id,
        commit_id=commit_id,
        result_id=result_id,
    )
    write_plan_materialization_bundle(
        store,
        receipt=receipt,
        master_plan=master_plan,
        sub_plan=sub_plan,
        manifest=manifest,
    )
    write_plan(store, payload)
    return payload
