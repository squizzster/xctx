"""Read-only plan construction for the xctx plan ledger."""

from __future__ import annotations

import secrets
from typing import Any

from xctx.config.paths import as_project_path
from xctx.domain.execution_contract import parse_plan_request
from xctx.domain.planning_common import plan_context, receipt_for_payload
from xctx.protocol.guidance import command_hints
from xctx.store.plans import plan_store_dir, write_plan


def read_only_plan_payload(args: list[str], store: dict[str, Any]) -> dict[str, Any]:
    request = parse_plan_request(args)
    context = plan_context(store)
    operation = request.operation_text
    canonical_intent_material = {
        "protocol": "xctx.v4.2",
        "operation": operation or None,
        "operation_token": request.operation,
        "target": request.target,
        "surface": "read_only_external_adapter_surface",
        "mutation_policy": "no_state_change_planned",
        "planner_context": context,
    }
    plan_material = {**canonical_intent_material, "plan_nonce": secrets.token_hex(32)}
    canonical_intent_hash = receipt_for_payload(canonical_intent_material)
    receipt = receipt_for_payload(plan_material)
    plan_id = f"plan:sha256:{receipt}"
    payload = {
        "operation": operation or None,
        "operation_token": request.operation,
        "target": request.target,
        "planner_id": receipt,
        "plan_id": plan_id,
        "status": "read_only_surface",
        "execution_status": "planned",
        "decision": "no_state_change_planned",
        "description": "xctx rehearsed the requested operation against the current protocol surface and recorded a unique execute binding. This read-only build performs no domain mutation.",
        "receipt_sha256": receipt,
        "receipt_sha5": receipt[:5],
        "receipt_note": "receipt_sha5 is a debug prefix only; execute requires the canonical plan_id.",
        "canonical_intent_hash": canonical_intent_hash,
        "plan_nonce": plan_material["plan_nonce"],
        "planner_context": context,
        "planner_ledger": as_project_path(store["root"], plan_store_dir(store)),
        "accepted_execute_cmd": f"./xctx execute {plan_id} --commit",
        "lawful_next_moves": command_hints(
            [
                "./xctx discover",
                "./xctx audit root",
                "./xctx repair <finding_id>",
                f"./xctx execute {plan_id} --commit",
            ]
        ),
    }
    write_plan(store, payload)
    return payload
