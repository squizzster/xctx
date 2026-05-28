"""Plan rehearsal and execute binding for the protocol-local xctx ledger."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from xctx.config.paths import as_project_path
from xctx.domain.actions import parse_scoped_subdomain_mode_ref, validate_declared_action_args
from xctx.domain.core import resolve_subdomain
from xctx.domain.execution_contract import parse_execute_request, parse_plan_request
from xctx.domain.routing import parse_scoped_action
from xctx.protocol.guidance import command_hints
from xctx.protocol.option_encoding import encode_cli_options_for_target
from xctx.protocol.option_specs import target_cli_option_specs
from xctx.ports.external_command import call_external_command
from xctx.errors import XctxError
from xctx.store.fingerprints import config_fingerprint_payload
from xctx.store.plans import PLAN_RECEIPT_PREFIX, plan_store_dir, resolve_plan, write_plan
from xctx.store.runtime_artifacts import (
    isoformat_utc,
    read_runtime_artifact,
    runtime_artifact_dir,
    runtime_artifact_ref,
    utc_now,
    write_runtime_artifact,
)


## Protocol boundary: the plan ledger is xctx-local evidence. It binds execute
## requests to recorded dry-runs or planned effects. Business/domain mutation is
## still owned by scoped adapters and only happens after explicit execute --commit.
def _receipt_for_payload(payload: dict[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _plan_context(store: dict[str, Any]) -> dict[str, Any]:
    fingerprint = config_fingerprint_payload(store)
    return {
        "config_sha256": fingerprint["sha256"],
        "protocol_version": fingerprint["protocol_version"],
        "config_file_count": fingerprint["config_file_count"],
        "fingerprint_algorithm": fingerprint["algorithm"],
    }


@dataclass(frozen=True)
class PlannedAction:
    domain_id: str
    subdomain_id: str
    action_name: str
    action: dict[str, Any]
    planning: dict[str, Any]
    domain_action_name: str | None = None


@dataclass(frozen=True)
class PlannedActionArgs:
    values: dict[str, Any]
    adapter_args: list[str]
    positional_args: list[str]


def _planning_contract(action: dict[str, Any]) -> dict[str, Any]:
    planning = action.get("planning") or {}
    if not isinstance(planning, dict):
        return {}
    if planning.get("planned_effect") is True:
        return planning
    if str(planning.get("mode") or "").strip() == "planned_effect":
        return planning
    return {}


def _resolve_planned_action(store: dict[str, Any], operation_token: str, action_args: list[str]) -> PlannedAction | None:
    if "::" not in operation_token:
        return None

    domain_id, subdomain_id, action_name, action = parse_scoped_subdomain_mode_ref(store, operation_token)
    if domain_id and subdomain_id and action_name and action:
        planning = _planning_contract(action)
        if planning:
            return PlannedAction(domain_id, subdomain_id, action_name, action, planning)
        return None

    domain_id, domain_action_name, domain_action = parse_scoped_action(store, operation_token, action_args=action_args)
    if domain_id and domain_action_name and domain_action:
        planning = _planning_contract(domain_action)
        if not planning:
            return None
        return PlannedAction(
            domain_id,
            str(domain_action["agent_subdomain"]),
            str(domain_action.get("_source_action_name") or domain_action_name),
            domain_action,
            planning,
            domain_action_name=domain_action_name,
        )
    return None


def _coerce_plan_option(value: Any, spec: dict[str, Any]) -> Any:
    option_type = str(spec.get("_option_type", "str"))
    flag = str(spec.get("_primary_flag") or spec.get("_dest") or "option")
    if option_type == "int":
        if isinstance(value, bool):
            raise XctxError(f"invalid integer for {flag}")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise XctxError(f"invalid integer for {flag}") from exc
    if option_type == "float":
        if isinstance(value, bool):
            raise XctxError(f"invalid number for {flag}")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise XctxError(f"invalid number for {flag}") from exc
    if option_type == "bool":
        return bool(value) if isinstance(value, bool) else str(value).lower() not in {"0", "false", "no", "off"}
    return str(value)


def _parse_planned_action_args(
    store: dict[str, Any],
    planned: PlannedAction,
    action_args: list[str],
) -> PlannedActionArgs:
    subdomain = resolve_subdomain(store, planned.domain_id, planned.subdomain_id)
    validate_declared_action_args(planned.action, action_args)
    specs = target_cli_option_specs(
        store,
        subdomain,
        "plan",
        action_name=planned.action_name,
        action=planned.action,
    )
    by_flag = {str(flag): spec for spec in specs for flag in spec.get("_flags", [])}
    values: dict[str, Any] = {}
    positional: list[str] = []
    index = 0
    while index < len(action_args):
        token = action_args[index]
        if token.startswith("-"):
            spec = by_flag.get(token)
            if not spec:
                raise XctxError(
                    f"unsupported option {token} for {planned.domain_id}::{planned.subdomain_id} plan",
                    next_moves=[
                        str(
                            planned.action.get("run_cmd")
                            or f"./xctx plan {planned.domain_id}::{planned.subdomain_id}::{planned.action_name}"
                        )
                    ],
                )
            dest = str(spec["_dest"])
            option_type = str(spec.get("_option_type", "str"))
            action = str(spec.get("action", "")).strip()
            if option_type == "bool" or action in {"store_true", "store_false"}:
                values[dest] = action != "store_false"
                index += 1
                continue
            if index + 1 >= len(action_args):
                raise XctxError(f"missing value for {token}")
            values[dest] = _coerce_plan_option(action_args[index + 1], spec)
            index += 2
            continue
        positional.append(token)
        index += 1

    for spec in specs:
        dest = str(spec["_dest"])
        if dest in values:
            continue
        if "default" in spec:
            values[dest] = _coerce_plan_option(spec["default"], spec)
    missing = [str(spec.get("_primary_flag") or spec["_dest"]) for spec in specs if spec.get("required") and spec["_dest"] not in values]
    if missing:
        raise XctxError(f"missing required plan option: {missing[0]}")

    option_args = encode_cli_options_for_target(
        store,
        subdomain,
        "plan",
        action_name=planned.action_name,
        action=planned.action,
        values=values,
    )
    return PlannedActionArgs(values=values, adapter_args=[*positional, *option_args], positional_args=positional)


def _planning_default(
    store: dict[str, Any],
    planned: PlannedAction,
    key: str,
    default: Any,
) -> Any:
    domain = store.get("agent_domains", {}).get(planned.domain_id) or {}
    subdomain = resolve_subdomain(store, planned.domain_id, planned.subdomain_id)
    for container in (
        planned.planning,
        subdomain.get("planning_defaults") or {},
        domain.get("planning_defaults") or {},
    ):
        if isinstance(container, dict) and container.get(key) is not None:
            return container[key]
    return default


def _render_template(template: str, values: dict[str, Any]) -> str:
    rendered = str(template)
    for key, value in sorted(values.items(), key=lambda item: len(str(item[0])), reverse=True):
        rendered = rendered.replace("{{ " + str(key) + " }}", str(value))
        rendered = rendered.replace("{{" + str(key) + "}}", str(value))
    return rendered


def _plan_is_committed(plan: dict[str, Any]) -> bool:
    return str(plan.get("execution_status") or "").lower() == "committed"


def _mark_plan_committed(
    store: dict[str, Any],
    plan: dict[str, Any],
    *,
    committed_at: str,
    commit_id: str | None = None,
    result_id: str | None = None,
) -> None:
    updated = dict(plan)
    updated["execution_status"] = "committed"
    updated["committed_at"] = committed_at
    if commit_id:
        updated["commit_id"] = commit_id
    if result_id:
        updated["result_id"] = result_id
    write_plan(store, updated)


def _plan_already_committed_payload(
    *,
    requested_plan: str,
    plan: dict[str, Any],
    resolved: Any,
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
) -> dict[str, Any]:
    result_id = str(plan.get("result_id") or plan.get("expected_result_id") or "")
    return {
        "ok": False,
        "error": "plan_already_committed",
        "requested_plan": requested_plan,
        "commit_requested": True,
        "status": "refused",
        "description": "This plan has already been committed. Plans are one-shot; observe the existing result or create a new plan.",
        "planner_binding": {
            "verified": True,
            "requested": requested_plan,
            "canonical_plan_id": plan.get("plan_id"),
            "receipt_sha256": plan.get("receipt_sha256"),
            "operation": plan.get("operation"),
            "short_receipt_matches": resolved.matches,
            "context_fingerprint_verified": context_matches,
            "planned_context_sha256": planned_context_sha,
            "current_context_sha256": current_context_sha,
        },
        "commit_id": plan.get("commit_id") or plan.get("expected_commit_id"),
        "result_id": result_id or None,
        "observe_result_cmd": f"./xctx observe {result_id}" if result_id else None,
        "mutations_applied": 0,
        "next_move": f"./xctx observe {result_id}" if result_id else "./xctx plan <operation> <target>",
    }


def _planned_effect_full_payload(args: list[str], store: dict[str, Any], planned: PlannedAction) -> dict[str, Any]:
    request = parse_plan_request(args)
    context = _plan_context(store)
    action_args = list(request.raw_args[1:])
    parsed_args = _parse_planned_action_args(store, planned, action_args)
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
    receipt = _receipt_for_payload(plan_material)
    plan_id = f"plan:sha256:{receipt}"
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
    description = _render_template(
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
    ttl_seconds = int(_planning_default(store, planned, "result_ttl_seconds", 300))
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
        "writes_to_db": bool(_planning_default(store, planned, "writes_to_db", False)),
        "can_be_reversed": bool(_planning_default(store, planned, "can_be_reversed", False)),
        "can_be_repaired": bool(_planning_default(store, planned, "can_be_repaired", False)),
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
            "commit": as_project_path(store["root"], runtime_artifact_dir(store, "commit")),
            "result": as_project_path(store["root"], runtime_artifact_dir(store, "result")),
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
    write_plan(store, payload)
    master_plan = {
        "master_plan_id": master_plan_id,
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
        "plan_id": plan_id,
        "master_plan_id": master_plan_id,
        "status": "planned",
        "execution_status": "planned",
        "expected_commit_id": commit_id,
        "expected_result_id": result_id,
        "planned_effect": planned_effect,
        "description_of_what_will_happen": description,
    }
    write_runtime_artifact(store, "master_plan", receipt, master_plan)
    write_runtime_artifact(store, "sub_plan", receipt, sub_plan)
    return payload


def _plan_full_payload(args: list[str], store: dict[str, Any]) -> dict[str, Any]:
    request = parse_plan_request(args)
    planned = _resolve_planned_action(store, request.operation, list(request.raw_args[1:]))
    if planned:
        return _planned_effect_full_payload(args, store, planned)
    context = _plan_context(store)
    operation = request.operation_text
    plan_material = {
        "protocol": "xctx.v4.2",
        "operation": operation or None,
        "operation_token": request.operation,
        "target": request.target,
        "surface": "read_only_external_adapter_surface",
        "mutation_policy": "no_state_change_planned",
        "planner_context": context,
    }
    receipt = _receipt_for_payload(plan_material)
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
        "description": "xctx rehearsed the requested operation against the current protocol surface and recorded a deterministic execute binding. This read-only build performs no domain mutation.",
        "receipt_sha256": receipt,
        "receipt_sha5": receipt[:5],
        "receipt_note": "receipt_sha5 is a debug prefix only; execute requires the canonical plan_id.",
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


def plan_payload(args: list[str], store: dict[str, Any]) -> dict[str, Any]:
    return _plan_full_payload(args, store)

def _context_match(store: dict[str, Any], plan: dict[str, Any] | None) -> tuple[bool, str | None, str | None]:
    if not plan:
        return False, None, _plan_context(store)["config_sha256"]
    current = _plan_context(store)["config_sha256"]
    stored_context = plan.get("planner_context")
    if not isinstance(stored_context, dict):
        return False, None, current
    planned = stored_context.get("config_sha256")
    return planned == current, str(planned) if planned else None, current


def _heartbeat(planned_effect: dict[str, Any], key: str, fallback_phase: str, fallback_message: str) -> dict[str, Any]:
    configured = planned_effect.get(key)
    if isinstance(configured, dict):
        return {
            "phase": configured.get("phase") or fallback_phase,
            "message": configured.get("message") or fallback_message,
        }
    return {"phase": fallback_phase, "message": fallback_message}


def _adapter_payload_failed(payload: dict[str, Any]) -> bool:
    object_type = str(payload.get("object_type", "")).lower()
    if object_type.endswith("_error"):
        return True
    command_status = payload.get("command_status")
    return isinstance(command_status, dict) and command_status.get("ok") is False


def _failed_result_payload(
    *,
    plan: dict[str, Any],
    planned_effect: dict[str, Any],
    receipt: str,
    message: str,
) -> dict[str, Any]:
    now = utc_now()
    ttl_seconds = int(planned_effect.get("result_ttl_seconds") or 300)
    expires_at = now + timedelta(seconds=ttl_seconds)
    return {
        "result_id": runtime_artifact_ref("result", receipt),
        "commit_id": runtime_artifact_ref("commit", receipt),
        "plan_id": plan.get("plan_id"),
        "status": "failed",
        "created_at": isoformat_utc(now),
        "expires_at": isoformat_utc(expires_at),
        "heartbeat_at": isoformat_utc(now),
        "heartbeat": {"phase": "failed", "message": message},
        "payload": None,
    }


def _execute_planned_effect_payload(
    *,
    requested_plan: str,
    resolved: Any,
    store: dict[str, Any],
    context_matches: bool,
    planned_context_sha: str | None,
    current_context_sha: str | None,
) -> dict[str, Any]:
    plan = dict(resolved.plan or {})
    receipt = str(plan["receipt_sha256"]).lower()
    planned_effect = plan.get("planned_effect") if isinstance(plan.get("planned_effect"), dict) else {}
    canonical_plan_id = str(plan.get("plan_id"))
    commit_id = str(plan.get("expected_commit_id") or runtime_artifact_ref("commit", receipt))
    result_id = str(plan.get("expected_result_id") or runtime_artifact_ref("result", receipt))
    existing_commit = read_runtime_artifact(store, "commit", receipt)
    existing_result = read_runtime_artifact(store, "result", receipt)
    if _plan_is_committed(plan) or (existing_commit and existing_result):
        return _plan_already_committed_payload(
            requested_plan=requested_plan,
            plan={**plan, "commit_id": commit_id, "result_id": result_id},
            resolved=resolved,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
        )

    now = utc_now()
    ttl_seconds = int(planned_effect.get("result_ttl_seconds") or 300)
    expires_at = now + timedelta(seconds=ttl_seconds)
    running_result = {
        "result_id": result_id,
        "commit_id": commit_id,
        "plan_id": canonical_plan_id,
        "status": "running",
        "created_at": isoformat_utc(now),
        "expires_at": isoformat_utc(expires_at),
        "heartbeat_at": isoformat_utc(now),
        "heartbeat": _heartbeat(
            planned_effect,
            "running_heartbeat",
            "commit_running",
            "Commit accepted; adapter work is running.",
        ),
        "payload": None,
    }
    commit = {
        "commit_id": commit_id,
        "plan_id": canonical_plan_id,
        "result_id": result_id,
        "status": "accepted",
        "created_at": isoformat_utc(now),
        "planned_effect": {
            key: planned_effect.get(key)
            for key in ("agent_domain", "agent_subdomain", "action", "implemented_by", "commit_adapter_command")
            if planned_effect.get(key) is not None
        },
    }
    write_runtime_artifact(store, "commit", receipt, commit)
    write_runtime_artifact(store, "result", receipt, running_result)
    master_plan = read_runtime_artifact(store, "master_plan", receipt)
    if master_plan:
        updated_master_plan = {
            **master_plan,
            "status": "committing",
            "execution_status": "committing",
            "commit_id": commit_id,
            "result_id": result_id,
            "committed_at": running_result["created_at"],
        }
        write_runtime_artifact(store, "master_plan", receipt, updated_master_plan)
    sub_plan = read_runtime_artifact(store, "sub_plan", receipt)
    if sub_plan:
        write_runtime_artifact(
            store,
            "sub_plan",
            receipt,
            {
                **sub_plan,
                "status": "committing",
                "execution_status": "committing",
                "commit_id": commit_id,
                "result_id": result_id,
                "committed_at": running_result["created_at"],
            },
        )

    try:
        subdomain = resolve_subdomain(
            store,
            str(planned_effect["agent_domain"]),
            str(planned_effect["agent_subdomain"]),
        )
        commit_context_args = [
            "--xctx-plan-id",
            canonical_plan_id,
            "--xctx-commit-id",
            commit_id,
            "--xctx-result-id",
            result_id,
        ]
        live = call_external_command(
            store,
            subdomain,
            [
                str(planned_effect["commit_adapter_command"]),
                *[str(arg) for arg in planned_effect.get("adapter_args") or []],
                *commit_context_args,
            ],
        )
    except Exception as exc:  # keep the committed result handle observable
        message = str(exc)
        failed = _failed_result_payload(plan=plan, planned_effect=planned_effect, receipt=receipt, message=message)
        commit["status"] = "failed"
        commit["error"] = message
        write_runtime_artifact(store, "commit", receipt, commit)
        write_runtime_artifact(store, "result", receipt, failed)
        _mark_plan_committed(
            store,
            plan,
            committed_at=failed["created_at"],
            commit_id=commit_id,
            result_id=result_id,
        )
        if master_plan:
            write_runtime_artifact(
                store,
                "master_plan",
                receipt,
                {
                    **master_plan,
                    "status": "committed",
                    "execution_status": "committed",
                    "commit_id": commit_id,
                    "result_id": result_id,
                    "committed_at": failed["created_at"],
                    "failed": True,
                },
            )
        if sub_plan:
            write_runtime_artifact(
                store,
                "sub_plan",
                receipt,
                {
                    **sub_plan,
                    "status": "committed",
                    "execution_status": "committed",
                    "commit_id": commit_id,
                    "result_id": result_id,
                    "committed_at": failed["created_at"],
                    "failed": True,
                },
            )
        return {
            "ok": False,
            "error": "planned_effect_commit_failed",
            "requested_plan": requested_plan,
            "commit_requested": True,
            "status": "failed",
            "description": "Execute accepted the planned effect boundary, but the scoped adapter failed. The result handle records the failure state.",
            "planner_binding": {
                "verified": True,
                "requested": requested_plan,
                "canonical_plan_id": canonical_plan_id,
                "receipt_sha256": receipt,
                "operation": plan.get("operation"),
                "short_receipt_matches": resolved.matches,
                "context_fingerprint_verified": context_matches,
                "planned_context_sha256": planned_context_sha,
                "current_context_sha256": current_context_sha,
            },
            "commit_id": commit_id,
            "result_id": result_id,
            "observe_result_cmd": f"./xctx observe {result_id}",
            "mutations_applied": 0,
            "next_move": f"./xctx observe {result_id}",
        }

    finished = utc_now()
    failed = _adapter_payload_failed(live)
    result_payload = {
        "result_id": result_id,
        "commit_id": commit_id,
        "plan_id": canonical_plan_id,
        "status": "failed" if failed else "ready",
        "created_at": running_result["created_at"],
        "completed_at": isoformat_utc(finished),
        "expires_at": running_result["expires_at"],
        "heartbeat_at": isoformat_utc(finished),
        "heartbeat": (
            {"phase": "failed", "message": "Scoped adapter returned a failure payload."}
            if failed
            else _heartbeat(planned_effect, "complete_heartbeat", "complete", "Result is ready.")
        ),
        "payload": None if failed else live,
    }
    if failed:
        result_payload["failure_payload"] = live
        commit["status"] = "failed"
    else:
        commit["status"] = "committed"
        commit["completed_at"] = isoformat_utc(finished)
    write_runtime_artifact(store, "commit", receipt, commit)
    write_runtime_artifact(store, "result", receipt, result_payload)
    _mark_plan_committed(
        store,
        plan,
        committed_at=isoformat_utc(finished),
        commit_id=commit_id,
        result_id=result_id,
    )
    if master_plan:
        write_runtime_artifact(
            store,
            "master_plan",
            receipt,
            {
                **master_plan,
                "status": "committed",
                "execution_status": "committed",
                "commit_id": commit_id,
                "result_id": result_id,
                "committed_at": isoformat_utc(finished),
            },
        )
    if sub_plan:
        write_runtime_artifact(
            store,
            "sub_plan",
            receipt,
            {
                **sub_plan,
                "status": "committed",
                "execution_status": "committed",
                "commit_id": commit_id,
                "result_id": result_id,
                "committed_at": isoformat_utc(finished),
            },
        )
    return {
        "ok": not failed,
        "error": "planned_effect_commit_failed" if failed else None,
        "requested_plan": requested_plan,
        "commit_requested": True,
        "status": "committed" if not failed else "failed",
        "description": "Execute committed a recorded planned effect through its scoped adapter and wrote a protocol-local result handle.",
        "planner_binding": {
            "verified": True,
            "requested": requested_plan,
            "canonical_plan_id": canonical_plan_id,
            "receipt_sha256": receipt,
            "operation": plan.get("operation"),
            "short_receipt_matches": resolved.matches,
            "context_fingerprint_verified": context_matches,
            "planned_context_sha256": planned_context_sha,
            "current_context_sha256": current_context_sha,
        },
        "commit_id": commit_id,
        "result_id": result_id,
        "observe_result_cmd": f"./xctx observe {result_id}",
        "mutations_applied": 1 if not failed and planned_effect.get("writes_to_db") else 0,
        "execution_receipt_sha256": _receipt_for_payload(
            {
                "execute": requested_plan,
                "bound_plan": canonical_plan_id,
                "commit": True,
                "commit_id": commit_id,
                "result_id": result_id,
                "mutations_applied": 1 if not failed and planned_effect.get("writes_to_db") else 0,
                "context_verified": True,
            }
        ),
        "next_move": f"./xctx observe {result_id}",
    }


def _execute_full_payload(args: list[str], commit: bool, store: dict[str, Any]) -> dict[str, Any]:
    cleaned = [str(arg).strip() for arg in args if str(arg).strip()]
    if not cleaned:
        return {
            "ok": False,
            "error": "plan_required",
            "requested_plan": None,
            "commit_requested": commit,
            "status": "refused",
            "description": "Execute requires a canonical plan id.",
            "next_move": "./xctx plan <operation> <target>",
        }
    if len(cleaned) != 1:
        return {
            "ok": False,
            "error": "invalid_execute_command",
            "requested_plan": " ".join(cleaned),
            "commit_requested": commit,
            "status": "refused",
            "description": "Execute accepts exactly one plan id.",
            "next_move": "./xctx execute <PLAN_ID> --commit",
        }
    request = parse_execute_request(args, commit=commit)
    requested_plan = request.plan_identifier
    if not str(requested_plan).startswith(PLAN_RECEIPT_PREFIX):
        return {
            "ok": False,
            "error": "plan_id_required",
            "requested_plan": requested_plan,
            "commit_requested": commit,
            "status": "refused",
            "description": "Execute requires a canonical plan id. Raw receipt hashes and short receipts are not executable.",
            "next_move": "./xctx execute plan:sha256:<sha256> --commit",
        }
    if not request.commit:
        return {
            "ok": False,
            "error": "commit_required",
            "requested_plan": requested_plan,
            "commit_requested": False,
            "status": "refused",
            "description": "Execute requires explicit --commit before any recorded plan can be accepted.",
            "next_move": f"./xctx execute {requested_plan} --commit",
        }

    resolved = resolve_plan(store, requested_plan)
    accepted = resolved.ok
    canonical_plan_id = None
    bound_operation = None
    bound_receipt = None
    context_matches = False
    planned_context_sha = None
    current_context_sha = None
    if resolved.plan:
        bound_receipt = resolved.plan.get("receipt_sha256")
        canonical_plan_id = resolved.plan.get("plan_id")
        bound_operation = resolved.plan.get("operation")
        context_matches, planned_context_sha, current_context_sha = _context_match(store, resolved.plan)
        if not context_matches:
            accepted = False
            resolved = resolved.__class__(False, "stale_plan_context", resolved.requested_plan, resolved.plan, resolved.matches)

    if accepted and resolved.plan and _plan_is_committed(resolved.plan):
        return _plan_already_committed_payload(
            requested_plan=requested_plan,
            plan=resolved.plan,
            resolved=resolved,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
        )

    if accepted and resolved.plan and isinstance(resolved.plan.get("planned_effect"), dict):
        return _execute_planned_effect_payload(
            requested_plan=requested_plan,
            resolved=resolved,
            store=store,
            context_matches=context_matches,
            planned_context_sha=planned_context_sha,
            current_context_sha=current_context_sha,
        )

    payload = {
        "ok": accepted,
        "error": None if accepted else resolved.error,
        "requested_plan": requested_plan,
        "commit_requested": True,
        "status": "accepted_read_only_noop" if accepted else "refused",
        "description": "Execute accepts only receipts that bind to a recorded xctx plan made against the current protocol surface. No domain mutation was performed because the bundled adapters expose read-only operations.",
        "planner_binding": {
            "verified": accepted,
            "requested": requested_plan,
            "canonical_plan_id": canonical_plan_id,
            "receipt_sha256": bound_receipt,
            "operation": bound_operation,
            "short_receipt_matches": resolved.matches,
            "context_fingerprint_verified": context_matches if resolved.plan else False,
            "planned_context_sha256": planned_context_sha,
            "current_context_sha256": current_context_sha,
        },
        "mutations_applied": 0,
        "execution_receipt_sha256": _receipt_for_payload(
            {
                "execute": requested_plan,
                "bound_plan": canonical_plan_id,
                "commit": True,
                "mutations_applied": 0,
                "context_verified": accepted,
            }
        ),
        "next_move": "./xctx audit root" if accepted else "./xctx plan <operation> <target>",
    }
    if accepted and resolved.plan:
        _mark_plan_committed(
            store,
            resolved.plan,
            committed_at=isoformat_utc(utc_now()),
        )
    return payload


def execute_payload(args: list[str], commit: bool, store: dict[str, Any]) -> dict[str, Any]:
    return _execute_full_payload(args, commit, store)
