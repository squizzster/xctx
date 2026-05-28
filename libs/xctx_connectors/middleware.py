"""Generic middleware for xctx-native pass-through and external command adapters."""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from xctx.config.loader import load_store
from xctx.config.paths import project_root_from_module
from xctx.process.python_subprocess import python_entrypoint_argv
from xctx.process.redaction import redact_value
from xctx.protocol.guidance import normalize_guidance
from xctx_connectors import runtime


_IMPORT_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
RESOLVED_CONTEXT_ENV = "XCTX_RESOLVED_CONTEXT_FILE"
CONFIG_FINGERPRINT_ENV = "XCTX_CONFIG_FINGERPRINT"
PASSTHROUGH_FRAMEWORK_KEYS = frozenset(
    {
        "connector",
        "command_status",
        "passthrough_target",
        "target_payload",
    }
)


def _emit_json(payload: dict[str, Any], *, compact: bool) -> None:
    payload = normalize_guidance(payload)
    if compact:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))


def _take_flag(argv: list[str], flag: str) -> tuple[bool, list[str]]:
    """Consume one middleware-owned trailing flag without stripping target args."""

    if argv and argv[-1] == flag:
        return True, argv[:-1]
    return False, list(argv)


def _project_root() -> Path:
    return project_root_from_module(__file__)


def _runtime_root_from_env(root: Path) -> Path:
    configured = os.environ.get("XCTX_RUNTIME_DIR")
    runtime_root = Path(configured) if configured else root / ".xctx_runtime"
    if not runtime_root.is_absolute():
        runtime_root = root / runtime_root
    return runtime_root.resolve()


def _resolved_subdomain_from_env(root: Path) -> dict[str, Any] | None:
    raw_path = os.environ.get(RESOLVED_CONTEXT_ENV)
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        raise ValueError(f"{RESOLVED_CONTEXT_ENV} must be an absolute path")
    runtime_root = _runtime_root_from_env(root)
    resolved = path.resolve()
    if resolved != runtime_root and runtime_root not in resolved.parents:
        raise ValueError(f"{RESOLVED_CONTEXT_ENV} must stay inside the xctx runtime directory")
    try:
        stat_result = resolved.stat()
    except OSError as exc:
        raise ValueError(f"resolved connector context is not readable: {resolved}") from exc
    if hasattr(os, "getuid") and stat_result.st_uid != os.getuid():
        raise ValueError("resolved connector context is not owned by the current user")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("resolved connector context must be valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("object_type") != "xctx_resolved_connector_context":
        raise ValueError("resolved connector context has an unsupported object_type")
    expected_fingerprint = os.environ.get(CONFIG_FINGERPRINT_ENV)
    if expected_fingerprint and payload.get("config_fingerprint") != expected_fingerprint:
        raise ValueError("resolved connector context fingerprint mismatch")
    domain_id = os.environ.get("XCTX_AGENT_DOMAIN")
    subdomain_id = os.environ.get("XCTX_AGENT_SUBDOMAIN")
    if not domain_id or not subdomain_id:
        raise ValueError("XCTX_AGENT_DOMAIN and XCTX_AGENT_SUBDOMAIN are required")
    if payload.get("domain_id") != domain_id or payload.get("subdomain_id") != subdomain_id:
        raise ValueError("resolved connector context scope mismatch")
    subdomain = payload.get("subdomain")
    if not isinstance(subdomain, dict):
        raise ValueError("resolved connector context is missing subdomain data")
    if subdomain.get("_domain_id") != domain_id or subdomain.get("id") != subdomain_id:
        raise ValueError("resolved connector context subdomain identity mismatch")
    connector = subdomain.get("connector") or {}
    if not isinstance(connector, dict):
        raise ValueError("resolved connector context subdomain is missing connector data")
    connector_kind = str(connector.get("kind") or "xctx_native_passthrough")
    if payload.get("connector_kind") != connector_kind:
        raise ValueError("resolved connector context connector kind mismatch")
    return subdomain


def _subdomain_from_env(root: Path) -> dict[str, Any]:
    resolved = _resolved_subdomain_from_env(root)
    if resolved is not None:
        return resolved
    domain_id = os.environ.get("XCTX_AGENT_DOMAIN")
    subdomain_id = os.environ.get("XCTX_AGENT_SUBDOMAIN")
    if not domain_id or not subdomain_id:
        raise ValueError("XCTX_AGENT_DOMAIN and XCTX_AGENT_SUBDOMAIN are required")
    store = load_store(root=root)
    domain = (store.get("agent_domains") or {}).get(domain_id)
    if not domain:
        raise ValueError(f"unknown connector domain: {domain_id}")
    subdomain = (domain.get("_subdomains") or {}).get(subdomain_id)
    if not subdomain:
        raise ValueError(f"unknown connector subdomain: {domain_id}::{subdomain_id}")
    return subdomain


def _context_from_subdomain(root: Path, subdomain: dict[str, Any]) -> runtime.ConnectorContext:
    domain_id = str(subdomain.get("_domain_id") or "")
    subdomain_id = str(subdomain.get("id") or "")
    if not domain_id or not subdomain_id:
        raise ValueError("connector subdomain is missing resolved domain/subdomain scope")
    connector = subdomain.get("connector") or {}
    limits = runtime.ConnectorLimits.from_config(connector)
    return runtime.ConnectorContext(
        workspace_root=root,
        domain_id=domain_id,
        subdomain_id=subdomain_id,
        subdomain_config=runtime.readonly_mapping(subdomain),
        connector_config=runtime.readonly_mapping(connector),
        limits=limits,
        detail_level=str(os.environ.get("XCTX_DETAIL_LEVEL") or "basic"),
    )


def _resolve_workspace_entrypoint(root: Path, raw: Any, *, label: str) -> Path:
    if raw is None or str(raw).strip() == "":
        raise ValueError(f"{label} is required")
    candidate = Path(str(raw))
    if candidate.is_absolute():
        raise ValueError(f"{label} must be relative to the workspace root")
    workspace_root = root.resolve()
    resolved = (workspace_root / candidate).resolve()
    if resolved != workspace_root and workspace_root not in resolved.parents:
        raise ValueError(f"{label} escapes workspace root")
    if not resolved.exists():
        raise ValueError(f"{label} does not exist: {raw}")
    if not resolved.is_file():
        raise ValueError(f"{label} must resolve to a regular file ({raw})")
    return resolved


def _include_command_argv(context: runtime.ConnectorContext) -> bool:
    return context.detail_level == "max"


def _with_capture_metadata(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.update(runtime.capture_metadata_from_result(result))
    return out


def _passthrough_env(context: runtime.ConnectorContext) -> dict[str, str | None]:
    return {
        "XCTX_AGENT_DOMAIN": context.domain_id,
        "XCTX_AGENT_SUBDOMAIN": context.subdomain_id,
        "XCTX_DETAIL_LEVEL": context.detail_level,
        "XCTX_RUNTIME_DIR": os.environ.get("XCTX_RUNTIME_DIR"),
    }


def _passthrough(context: runtime.ConnectorContext, args: list[str], *, compact: bool) -> dict[str, Any]:
    connector = context.connector_config
    target = connector.get("target_entrypoint")
    target_path = _resolve_workspace_entrypoint(context.workspace_root, target, label="target_entrypoint")
    limits = context.limits
    argv = python_entrypoint_argv(target_path, args)
    include_argv = _include_command_argv(context)
    if compact and "--compact" not in argv:
        argv.append("--compact")
    result = runtime.run_external(
        argv,
        cwd=context.workspace_root,
        env=_passthrough_env(context),
        timeout=limits.timeout_seconds,
        max_output_bytes=limits.max_output_bytes,
    )
    if result["timed_out"]:
        payload: dict[str, Any] = {
            "object_type": "xctx_native_passthrough_error",
            "found": False,
            "connector": runtime.connector_meta(context),
            "requested_args": redact_value(args),
            "passthrough_target": str(target),
            "command_status": _with_capture_metadata(
                runtime.command_status(
                    ok=False,
                    argv=argv if include_argv else None,
                    timed_out=True,
                    error=f"passthrough target timed out after {limits.timeout_seconds} seconds",
                    stdout=str(result.get("stdout") or ""),
                    stderr=str(result.get("stderr") or ""),
                ),
                result,
            ),
            "data_boundary": "Pass-through connector normalized a target adapter timeout into JSON.",
        }
        if args and args[0] == "audit":
            payload["checks"] = [runtime.audit_failure_check(context, payload["command_status"]["error"])]
        return payload

    text = str(result.get("stdout") or "").strip()
    if result["ok"]:
        try:
            payload = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            return runtime.connector_error_payload(
                context,
                f"passthrough target returned invalid JSON: {exc}",
                command=args[0] if args else "discover",
                args=args,
            )
        if isinstance(payload, dict):
            reserved = sorted(PASSTHROUGH_FRAMEWORK_KEYS.intersection(payload))
            if reserved:
                return runtime.connector_error_payload(
                    context,
                    f"passthrough target returned framework-owned keys: {', '.join(reserved)}",
                    command=args[0] if args else "discover",
                    args=args,
                )
            payload_with_connector = dict(payload)
            payload_with_connector["connector"] = runtime.connector_meta(context)
            return payload_with_connector
        return runtime.connector_error_payload(
            context,
            "passthrough target returned non-object JSON",
            command=args[0] if args else "discover",
            args=args,
        )

    try:
        target_payload = json.loads(text)
    except json.JSONDecodeError:
        target_payload = {}
    raw_exit_code = result.get("exit_code")
    exit_code = int(raw_exit_code) if raw_exit_code is not None else None
    payload = {
        "object_type": "xctx_native_passthrough_error",
        "found": False,
        "connector": runtime.connector_meta(context),
        "requested_args": redact_value(args),
        "passthrough_target": str(target),
        "target_payload": redact_value(target_payload) if isinstance(target_payload, dict) else {},
        "command_status": _with_capture_metadata(
            runtime.command_status(
                ok=False,
                argv=argv if include_argv else None,
                exit_code=exit_code,
                error=(
                    str(result.get("stderr") or "").strip()
                    or (target_payload.get("error") if isinstance(target_payload, dict) else None)
                    or "passthrough target failed"
                ),
                stdout=str(result.get("stdout") or ""),
                stderr=str(result.get("stderr") or ""),
            ),
            result,
        ),
        "data_boundary": "Pass-through connector normalized a target adapter failure into JSON.",
    }
    if args and args[0] == "audit":
        payload["checks"] = [runtime.audit_failure_check(context, payload["command_status"]["error"])]
    return payload


def _adapter_module_name(context: runtime.ConnectorContext) -> str:
    for label, value in (("domain", context.domain_id), ("subdomain", context.subdomain_id)):
        if not _IMPORT_SAFE_ID.fullmatch(value):
            raise ValueError(f"{label} id is not import-safe for connector adapter dispatch: {value}")
    adapter_scope = str(context.connector_config.get("adapter_scope", "subdomain"))
    if adapter_scope == "domain":
        return f"xctx_connectors.domains.{context.domain_id}.external_command_adapter"
    if adapter_scope != "subdomain":
        raise ValueError(f"unsupported external command adapter_scope: {adapter_scope}")
    return (
        "xctx_connectors.domains."
        f"{context.domain_id}.subdomains.{context.subdomain_id}.external_command_adapter"
    )


def _external_command_adapter(context: runtime.ConnectorContext, command: str, rest: list[str]) -> dict[str, Any]:
    module_name = _adapter_module_name(context)
    module = importlib.import_module(module_name)
    adapter_run = getattr(module, "run", None)
    if not callable(adapter_run):
        raise ValueError(f"external command adapter has no callable run(context, command, rest, runtime): {module_name}")
    payload = adapter_run(context, command, rest, runtime)
    if not isinstance(payload, dict):
        raise ValueError(f"external command adapter returned non-object payload: {module_name}")
    if "connector" in payload:
        raise ValueError(f"external command adapter must not construct connector metadata: {module_name}")
    payload_with_connector = dict(payload)
    payload_with_connector["connector"] = runtime.connector_meta(context)
    return payload_with_connector


def _run_with_context(
    context: runtime.ConnectorContext,
    argv: list[str],
    *,
    compact: bool,
) -> dict[str, Any]:
    kind = str(context.connector_config.get("kind", "xctx_native_passthrough"))
    if kind == "xctx_native_passthrough":
        return _passthrough(context, argv, compact=compact)
    command = argv[0] if argv else "discover"
    rest = argv[1:]
    if kind == "external_command":
        return _external_command_adapter(context, command, rest)
    raise ValueError(f"unsupported connector kind: {kind}")


def run(argv: list[str], *, root: Path | None = None, compact: bool = True) -> dict[str, Any]:
    root = root or _project_root()
    context = _context_from_subdomain(root, _subdomain_from_env(root))
    return _run_with_context(context, argv, compact=compact)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # Connector stdout is compact internal transport by default. Public xctx
    # verbosity is carried by XCTX_DETAIL_LEVEL, not a middleware flag.
    compact = True
    args = raw
    root = _project_root()
    context: runtime.ConnectorContext | None = None
    connector: dict[str, Any] | None = None
    try:
        subdomain = _subdomain_from_env(root)
        connector = subdomain.get("connector") or {}
        context = _context_from_subdomain(root, subdomain)
        payload = _run_with_context(context, args, compact=compact)
    except Exception as exc:  # always return a structured object to xctx
        payload = runtime.connector_error_payload(
            context,
            str(exc),
            command=args[0] if args else "discover",
            args=args,
            connector=connector,
        )
    _emit_json(payload, compact=compact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
