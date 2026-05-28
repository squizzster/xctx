"""Central output projection boundary for protocol detail levels.

Every stdout payload passes through this module immediately before emission.
Domain modules and adapters may build rich internal payloads; only this projector
chooses which framework diagnostics, provenance, and guidance survive into public
``basic``/``more`` output. ``max`` remains the forensic/developer packet, still
subject to normal redaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from xctx.protocol.detail import detail_controls, detail_hint, detail_level, is_max, orientation_surface

DIAGNOSTIC_KEYS = frozenset(
    {
        "argv",
        "command_status",
        "connector",
        "external_command",
        "external_commands",
        "passthrough_target",
        "target_payload",
        "loaded_config_files",
        "fingerprint",
        "config_fingerprint",
        "planner_context",
        "planner_ledger",
        "planner_binding",
        "execution_receipt_sha256",
        "planned_context_sha256",
        "current_context_sha256",
        "config_sha256",
        "stdout_preview",
        "stderr_preview",
        "safe_root",
        "payload_contract",
        "stdout",
        "stderr",
        "exit_code",
        "timed_out",
        "workspace_root",
        "root_path",
        "resolved_path",
        "target_entrypoint",
        "adapter_scope",
        "adapter_ref",
        "raw_external_output",
    }
)

PUBLIC_KEY_RENAMES = {
    "shape": "projection",
    "full_shape_cmd": "full_projection_cmd",
    "id_shape": "id_pattern",
    "observe_shape": "observe_cmd_pattern",
    "query_shape": "query_pattern",
    "argument_shapes": "argument_patterns",
    "identity_shapes": "identity_patterns",
    "shape_guarantee": "payload_contract",
    "success_shape": "success_payload",
    "failure_shape": "failure_payload",
    "accepted_execute_shape": "accepted_execute_cmd",
    "default_shape": "default_projection",
    "item_shapes": "item_projections",
    "discovery_shapes": "discovery_projections",
    "output_shapes": "output_projections",
    "shapes": "projections",
}
OPAQUE_ADAPTER_PAYLOAD_KEYS = frozenset({"payload", "failure_payload"})
LIVE_DATA_DIAGNOSTIC_KEYS = frozenset(
    {
        "argv",
        "command_status",
        "connector",
        "external_command",
        "external_commands",
        "passthrough_target",
        "target_payload",
        "raw_external_output",
    }
)


def _replace_public_text(value: str) -> str:
    return (
        value.replace("--shape", "--projection")
        .replace("full_shape_cmd", "full_projection_cmd")
        .replace("shape compact|full", "projection compact|full")
        .replace("Shape compact|full", "Projection compact|full")
    )


def _workspace_markers(store: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    root = store.get("root")
    if root:
        try:
            resolved = Path(root).resolve().as_posix()
            markers.append(resolved)
        except Exception:
            markers.append(str(root))
    return [marker for marker in dict.fromkeys(markers) if marker]


def _relativize_workspace_paths(store: dict[str, Any], value: Any) -> Any:
    """Replace absolute workspace-root occurrences with a stable marker.

    This is deliberately a final, framework-owned pass. Adapters may return
    diagnostics in ``max`` output, but raw machine-local workspace paths should
    never be required for agent operation and should not leak by accident.
    """

    markers = _workspace_markers(store)
    if not markers:
        return value

    def convert(item: Any) -> Any:
        if isinstance(item, str):
            text = item
            for marker in markers:
                text = text.replace(marker, "<workspace_root>")
            return text
        if isinstance(item, list):
            return [convert(child) for child in item]
        if isinstance(item, tuple):
            return [convert(child) for child in item]
        if isinstance(item, Mapping):
            out: dict[Any, Any] = {}
            for key, child in item.items():
                if isinstance(key, str) and key in OPAQUE_ADAPTER_PAYLOAD_KEYS:
                    out[key] = child
                    continue
                if key == "live_data" and isinstance(child, Mapping):
                    out[key] = {
                        live_key: convert(live_child) if live_key in LIVE_DATA_DIAGNOSTIC_KEYS else live_child
                        for live_key, live_child in child.items()
                    }
                    continue
                out[key] = convert(child)
            return out
        return item

    return convert(value)


def _normalize_public_terms(value: Any) -> Any:
    if isinstance(value, str):
        return _replace_public_text(value)
    if isinstance(value, list):
        return [_normalize_public_terms(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_public_terms(item) for item in value]
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            new_key = PUBLIC_KEY_RENAMES.get(key, key) if isinstance(key, str) else key
            if isinstance(key, str) and key in OPAQUE_ADAPTER_PAYLOAD_KEYS:
                out[new_key] = item
                continue
            if key == "live_data" and isinstance(item, Mapping):
                out[new_key] = {
                    live_key: _normalize_public_terms(live_child)
                    if live_key in LIVE_DATA_DIAGNOSTIC_KEYS
                    else live_child
                    for live_key, live_child in item.items()
                }
                continue
            normalized = _normalize_public_terms(item)
            if new_key == "full_projection_cmd":
                out["projection_controls"] = {
                    "current": "compact",
                    "available": [{"projection": "full", "run_cmd": normalized}],
                }
                continue
            out[new_key] = normalized
        return out
    return value


def _contains_diagnostics(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key in OPAQUE_ADAPTER_PAYLOAD_KEYS:
                continue
            if key == "live_data" and isinstance(item, Mapping):
                if any(live_key in LIVE_DATA_DIAGNOSTIC_KEYS for live_key in item):
                    return True
                continue
            if isinstance(key, str) and key in DIAGNOSTIC_KEYS:
                return True
            if _contains_diagnostics(item):
                return True
    elif isinstance(value, list | tuple):
        return any(_contains_diagnostics(item) for item in value)
    return False


def _strip_diagnostics(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_diagnostics(item) for item in value]
    if isinstance(value, tuple):
        return [_strip_diagnostics(item) for item in value]
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if key == "omitted":
                out[key] = item
                continue
            if isinstance(key, str) and key in OPAQUE_ADAPTER_PAYLOAD_KEYS:
                out[key] = item
                continue
            if key == "live_data" and isinstance(item, Mapping):
                out[key] = {
                    live_key: live_child
                    for live_key, live_child in item.items()
                    if live_key not in LIVE_DATA_DIAGNOSTIC_KEYS
                }
                continue
            if isinstance(key, str) and key in DIAGNOSTIC_KEYS:
                continue
            out[key] = _strip_diagnostics(item)
        return out
    return value


def _status(check: Any) -> str:
    if not isinstance(check, Mapping):
        return "fail"
    status = str(check.get("status", "")).lower()
    return "warn" if status == "warning" else status


def _audit_summary(scope: str, checks: list[Any], findings: list[Any], existing: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if existing:
        base = dict(existing)
        base.setdefault("scope", scope)
        return base
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0, "other": 0}
    for check in checks:
        status = _status(check)
        counts[status if status in counts else "other"] += 1
    return {
        "scope": scope,
        "checks_total": len(checks),
        "pass": counts["pass"],
        "warn": counts["warn"],
        "fail": counts["fail"] + counts["other"],
        "skip": counts["skip"],
        "findings": len(findings),
        "repairable_findings": sum(1 for finding in findings if isinstance(finding, Mapping) and finding.get("repairable")),
        "terminal_maintenance_findings": sum(
            1 for finding in findings if isinstance(finding, Mapping) and finding.get("status") == "down_for_maintenance"
        ),
    }


def _audit_status(summary: Mapping[str, Any], existing: Any = None) -> str:
    if existing:
        return str(existing)
    if int(summary.get("fail", 0) or 0) > 0:
        return "failed"
    if int(summary.get("warn", 0) or 0) > 0:
        return "warnings_present"
    if int(summary.get("findings", 0) or 0) > 0:
        return "findings_present"
    return "pass"


def _project_audit(store: dict[str, Any], payload: Mapping[str, Any], *, cmdline_arg: str | None) -> dict[str, Any]:
    scope = str(payload.get("scope") or "root")
    audit_scope = str(payload.get("audit_scope") or "all")
    checks = list(payload.get("checks") or [])
    findings = list(payload.get("findings") or [])
    summary = _audit_summary(scope, checks, findings, payload.get("summary") if isinstance(payload.get("summary"), Mapping) else None)
    summary.setdefault("audit_scope", audit_scope)
    status = _audit_status(summary, payload.get("audit_status"))
    if is_max(store):
        out = dict(payload)
        out["summary"] = summary
        out["audit_scope"] = audit_scope
        out["audit_status"] = status
        return out

    visible_checks = [check for check in checks if _status(check) not in {"pass", "skip"}]
    visible_checks = _strip_diagnostics(visible_checks)
    if detail_level(store) == "more":
        pass_check_ids = [str(check.get("id")) for check in checks if isinstance(check, Mapping) and _status(check) == "pass"]
        out = {
            "scope": scope,
            "audit_scope": audit_scope,
            "audit_status": status,
            "summary": summary,
            "checks": visible_checks,
            "pass_check_ids": pass_check_ids,
            "findings": findings,
            "omitted": {
                "pass_checks": len(pass_check_ids),
                "diagnostic_fields": ["config_fingerprint", "config_file_details"],
            },
        }
        if hint := detail_hint(store, cmdline_arg, omitted=["config_fingerprint", "config_file_details"], max_only=True):
            out["detail_hint"] = hint
        return out

    omitted = ["pass_checks", "config_fingerprint", "config_file_details"]
    out = {
        "scope": scope,
        "audit_scope": audit_scope,
        "audit_status": status,
        "summary": summary,
        "checks": visible_checks,
        "findings": findings,
        "omitted": {
            "pass_checks": int(summary.get("pass", 0) or 0) + int(summary.get("skip", 0) or 0),
            "config_fingerprint": True,
            "diagnostic_fields": ["config_file_details"],
        },
        "detail_hint": detail_hint(store, cmdline_arg, omitted=omitted),
    }
    return out


def _project_plan(store: dict[str, Any], payload: Mapping[str, Any], *, cmdline_arg: str | None) -> dict[str, Any]:
    if is_max(store):
        return dict(payload)
    keys = [
        "operation",
        "operation_token",
        "target",
        "planner_id",
        "plan_id",
        "materialization_manifest_id",
        "master_plan_id",
        "sub_plan_id",
        "expected_commit_id",
        "expected_result_id",
        "status",
        "execution_status",
        "decision",
        "description_of_what_will_happen",
        "writes_to_db",
        "can_be_reversed",
        "can_be_repaired",
        "materialized_artifacts",
        "receipt_sha256",
        "receipt_sha5",
        "accepted_execute_cmd",
        "discover_master_plan_cmd",
        "observe_result_cmd",
        "lawful_next_moves",
    ]
    out = {key: payload[key] for key in keys if key in payload}
    out.setdefault("domain_mutations_planned", 1 if payload.get("writes_to_db") else 0)
    out.setdefault("protocol_local_effects", ["plan_recorded"])
    if detail_level(store) == "more":
        for key in ("description", "receipt_note"):
            if key in payload:
                out[key] = payload[key]
        context = payload.get("planner_context") if isinstance(payload.get("planner_context"), Mapping) else {}
        if context:
            out["planner_context_summary"] = {
                key: context.get(key)
                for key in ("protocol_version", "config_file_count", "fingerprint_algorithm")
                if context.get(key) is not None
            }
        out["detail_hint"] = detail_hint(store, cmdline_arg, omitted=["planner_context", "planner_ledger"], max_only=True)
    else:
        out["detail_hint"] = detail_hint(store, cmdline_arg, omitted=["description", "planner_context", "planner_ledger"])
    return {key: value for key, value in out.items() if value is not None}


def _project_execute(store: dict[str, Any], payload: Mapping[str, Any], *, cmdline_arg: str | None) -> dict[str, Any]:
    if is_max(store):
        return dict(payload)
    keys = [
        "requested_plan",
        "commit_requested",
        "status",
        "commit_id",
        "result_id",
        "observe_result_cmd",
        "mutations_applied",
        "next_move",
    ]
    out = {key: payload[key] for key in keys if key in payload}
    if detail_level(store) == "more":
        if "description" in payload:
            out["description"] = payload["description"]
        binding = payload.get("planner_binding") if isinstance(payload.get("planner_binding"), Mapping) else {}
        if binding:
            out["planner_binding_summary"] = {
                key: binding.get(key)
                for key in ("verified", "requested", "canonical_plan_id", "operation", "context_fingerprint_verified")
                if binding.get(key) is not None
            }
        out["detail_hint"] = detail_hint(store, cmdline_arg, omitted=["planner_binding", "execution_receipt_sha256"], max_only=True)
    else:
        out["detail_hint"] = detail_hint(store, cmdline_arg, omitted=["description", "planner_binding", "execution_receipt_sha256"])
    return {key: value for key, value in out.items() if value is not None}


def _project_repair(store: dict[str, Any], payload: Mapping[str, Any], *, cmdline_arg: str | None) -> dict[str, Any]:
    if is_max(store):
        return dict(payload)
    keys = [
        "target",
        "current_status",
        "finding_id",
        "final",
        "message",
        "execution_state",
        "next_moves",
        "next_move",
    ]
    out = {key: payload[key] for key in keys if key in payload}
    repair_path = payload.get("repair_path") if isinstance(payload.get("repair_path"), Mapping) else None
    if repair_path:
        out["repairable"] = True
        out["repair_cmd"] = repair_path.get("run_cmd")
        steps = repair_path.get("steps") if isinstance(repair_path.get("steps"), list) else []
        out["repair_step_count"] = len(steps)
        if detail_level(store) == "more":
            out["repair_steps"] = steps
            out["detail_hint"] = detail_hint(store, cmdline_arg, omitted=["repair_path"], max_only=True)
        else:
            out["detail_hint"] = detail_hint(store, cmdline_arg, omitted=["repair_path", "repair_steps"])
    elif "repair_path" in payload:
        out["repairable"] = False
    return {key: value for key, value in out.items() if value is not None}


def _project_extension(store: dict[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    if is_max(store):
        return dict(payload)
    keys = ["topic", "status", "next_moves"] if detail_level(store) == "basic" else ["topic", "reason", "status", "note", "next_moves"]
    return {key: payload[key] for key in keys if key in payload}


def _strip_option_sources(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_option_sources(item) for item in value]
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if key == "source":
                continue
            out[key] = _strip_option_sources(item)
        return out
    return value


def _project_discovery_like(
    store: dict[str, Any],
    payload: Mapping[str, Any],
    *,
    cmdline_arg: str | None,
    record_type: str,
    command: str | None,
    domain_level: str | None,
) -> dict[str, Any]:
    had_diagnostics = _contains_diagnostics(payload)
    out = dict(payload)
    if not is_max(store):
        out = _strip_diagnostics(out)
        if detail_level(store) == "basic":
            for key in (
                "configured_options",
                "configured_actions",
                "configured_action_index",
                "domain_affordances",
                "data_description",
                "next_move_context",
            ):
                out.pop(key, None)
        else:
            if "configured_options" in out:
                out["configured_options"] = _strip_option_sources(out["configured_options"])
            out.pop("configured_actions", None)
    if orientation_surface(record_type, domain_level, command):
        out["detail_controls"] = detail_controls(store, cmdline_arg)
    elif not is_max(store) and had_diagnostics:
        if hint := detail_hint(store, cmdline_arg, omitted=["diagnostics"]):
            out["detail_hint"] = hint
    return out


def project_record_payload(
    store: dict[str, Any],
    record_type: str,
    payload: Any,
    *,
    command: str | None = None,
    cmdline_arg: str | None = None,
    domain_level: str | None = None,
) -> Any:
    """Return the public payload for the selected protocol detail level."""

    normalized = _normalize_public_terms(deepcopy(payload))
    if not isinstance(normalized, Mapping):
        return normalized

    if record_type == "audit":
        projected = _project_audit(store, normalized, cmdline_arg=cmdline_arg)
    elif record_type == "plan":
        projected = _project_plan(store, normalized, cmdline_arg=cmdline_arg)
    elif record_type == "execution_result":
        projected = _project_execute(store, normalized, cmdline_arg=cmdline_arg)
    elif record_type == "repair_result":
        projected = _project_repair(store, normalized, cmdline_arg=cmdline_arg)
    elif record_type == "extension":
        projected = _project_extension(store, normalized)
    elif record_type in {"discovery", "observation", "version"}:
        projected = _project_discovery_like(
            store,
            normalized,
            cmdline_arg=cmdline_arg,
            record_type=record_type,
            command=command,
            domain_level=domain_level,
        )
    else:
        projected = dict(normalized)

    if not is_max(store):
        projected = _strip_diagnostics(projected)
    return projected


def project_output_envelope(store: dict[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Final centralized public-output boundary for the complete envelope.

    Record-specific projectors build ``results``. This last pass protects the
    whole stdout record from accidental diagnostics below ``max`` and from
    machine-local absolute workspace paths. It deliberately keeps command/error
    strings literal so invalid legacy input is reported honestly.
    """

    # ``results`` has already been normalized by project_record_payload(). Keep
    # envelope command/error strings literal so invalid legacy input is reported
    # honestly instead of being rewritten into the new vocabulary.
    public = deepcopy(envelope)
    if not is_max(store):
        public = _strip_diagnostics(public)
    public = _relativize_workspace_paths(store, public)
    return dict(public) if isinstance(public, Mapping) else {"results": public}
