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
from xctx_connectors import runtime


_IMPORT_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def _emit_json(payload: dict[str, Any], *, compact: bool) -> None:
    if compact:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))


def _take_flag(argv: list[str], flag: str) -> tuple[bool, list[str]]:
    present = flag in argv
    return present, [item for item in argv if item != flag]


def _project_root() -> Path:
    path = Path(__file__).resolve()
    for candidate in path.parents:
        if (candidate / "yaml_dynamic_config").exists() and (candidate / "data").exists():
            return candidate
    return path.parents[2]


def _subdomain_from_env(root: Path) -> dict[str, Any]:
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
    return runtime.ConnectorContext(
        workspace_root=root,
        domain_id=domain_id,
        subdomain_id=subdomain_id,
        subdomain_config=runtime.readonly_mapping(subdomain),
        connector_config=runtime.readonly_mapping(connector),
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


def _full_shape_requested(args: list[str]) -> bool:
    shape: str | None = None
    index = 0
    while index < len(args):
        if args[index] == "--shape" and index + 1 < len(args):
            shape = args[index + 1]
            index += 2
            continue
        index += 1
    return shape == "full"


def _passthrough(context: runtime.ConnectorContext, args: list[str], *, compact: bool) -> dict[str, Any]:
    connector = context.connector_config
    target = connector.get("target_entrypoint")
    target_path = _resolve_workspace_entrypoint(context.workspace_root, target, label="target_entrypoint")
    timeout = runtime.validated_timeout(connector.get("timeout_seconds", 30))
    max_output_bytes = runtime.validated_max_output_bytes(connector.get("max_output_bytes", runtime.DEFAULT_MAX_OUTPUT_BYTES))
    argv = [sys.executable, str(target_path), *args]
    include_argv = _full_shape_requested(args)
    if compact and "--compact" not in argv:
        argv.append("--compact")
    result = runtime.run_external(argv, cwd=context.workspace_root, timeout=timeout, max_output_bytes=max_output_bytes)
    if result["timed_out"]:
        payload: dict[str, Any] = {
            "object_type": "xctx_native_passthrough_error",
            "found": False,
            "connector": runtime.connector_meta(context),
            "requested_args": args,
            "passthrough_target": str(target),
            "command_status": runtime.command_status(
                ok=False,
                argv=argv if include_argv else None,
                timed_out=True,
                error=f"passthrough target timed out after {timeout} seconds",
                stdout=str(result.get("stdout") or ""),
                stderr=str(result.get("stderr") or ""),
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
            return payload
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
    payload = {
        "object_type": "xctx_native_passthrough_error",
        "found": False,
        "connector": runtime.connector_meta(context),
        "requested_args": args,
        "passthrough_target": str(target),
        "target_payload": target_payload if isinstance(target_payload, dict) else {},
        "command_status": runtime.command_status(
            ok=False,
            argv=argv if include_argv else None,
            exit_code=int(result.get("exit_code") or 0),
            error=(
                str(result.get("stderr") or "").strip()
                or (target_payload.get("error") if isinstance(target_payload, dict) else None)
                or "passthrough target failed"
            ),
            stdout=str(result.get("stdout") or ""),
            stderr=str(result.get("stderr") or ""),
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
    shaped = dict(payload)
    shaped["connector"] = runtime.connector_meta(context)
    return shaped


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
    compact, args = _take_flag(raw, "--compact")
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
