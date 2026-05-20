"""Generic runtime helpers for xctx connector middleware."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


CONNECTOR_VERSION = "legacy_connector.v1"


@dataclass(frozen=True)
class ConnectorContext:
    workspace_root: Path
    domain_id: str
    subdomain_id: str
    subdomain_config: Mapping[str, Any]
    connector_config: Mapping[str, Any]

    @property
    def adapter_ref(self) -> str:
        return f"{self.domain_id}::{self.subdomain_id}"


def readonly_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


def shape_guarantee(kind: str) -> dict[str, str]:
    base = {
        "xctx_receives": "single_json_object_for_live_data",
        "raw_legacy_output": "never_returned_unparsed",
        "stdout_stderr": "summarized_in_command_status_when_useful",
    }
    if kind == "legacy_command":
        return {
            **base,
            "contract": "always_json_object",
            "success_shape": "domain_object",
            "failure_shape": "legacy_connector_error",
        }
    if kind == "xctx_native_passthrough":
        return {
            **base,
            "contract": "pass_through_json_object",
            "success_shape": "target_adapter_object",
            "failure_shape": "xctx_native_passthrough_error",
        }
    return {
        **base,
        "contract": "always_json_object",
        "success_shape": "connector_object",
        "failure_shape": "legacy_connector_error",
    }


def connector_meta(
    context: ConnectorContext | None,
    connector: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    connector_config = connector or (context.connector_config if context else {})
    kind = str(connector_config.get("kind", "unknown"))
    domain_id = context.domain_id if context else None
    subdomain_id = context.subdomain_id if context else None
    payload: dict[str, Any] = {
        "version": CONNECTOR_VERSION,
        "kind": kind,
        "agent_domain": domain_id,
        "agent_subdomain": subdomain_id,
        "shape_guarantee": shape_guarantee(kind),
    }
    if domain_id and subdomain_id:
        payload["adapter_ref"] = f"{domain_id}::{subdomain_id}"
    adapter_scope = connector_config.get("adapter_scope")
    if adapter_scope:
        payload["adapter_scope"] = str(adapter_scope)
    return payload


def command_status(
    *,
    ok: bool,
    argv: list[str] | None = None,
    exit_code: int | None = None,
    timed_out: bool = False,
    error: str | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }
    if argv is not None:
        payload["argv"] = argv
    if error:
        payload["error"] = error
    if stdout is not None:
        payload["stdout_preview"] = stdout[:500]
    if stderr is not None:
        payload["stderr_preview"] = stderr[:500]
    return {key: value for key, value in payload.items() if value is not None}


def command_status_from_legacy(legacy: Mapping[str, Any], *, include_argv: bool = True) -> dict[str, Any]:
    return command_status(
        ok=bool(legacy["ok"]),
        argv=list(legacy["argv"]) if include_argv else None,
        exit_code=legacy["exit_code"],
        timed_out=bool(legacy["timed_out"]),
        error=legacy.get("error"),
        stderr=legacy.get("stderr"),
    )


def audit_failure_check(context: ConnectorContext | None, message: str) -> dict[str, Any]:
    domain_id = context.domain_id if context else "unknown_domain"
    subdomain_id = context.subdomain_id if context else "unknown_subdomain"
    return {
        "id": f"audit:{domain_id}:{subdomain_id}:middleware_connector",
        "status": "fail",
        "message": message,
    }


def connector_error_payload(
    context: ConnectorContext | None,
    message: str,
    *,
    command: str | None = None,
    args: list[str] | None = None,
    connector: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    next_moves = ["./xctx audit root"]
    if context:
        next_moves.insert(0, f"./xctx audit {context.adapter_ref}")
    payload: dict[str, Any] = {
        "object_type": "legacy_connector_error",
        "found": False,
        "connector": connector_meta(context, connector),
        "requested_command": command,
        "requested_args": args or [],
        "command_status": command_status(ok=False, error=message),
        "data_boundary": "Middleware error payload. xctx received a structured object instead of raw connector failure output.",
        "next_moves": next_moves,
    }
    if command == "audit":
        payload["checks"] = [audit_failure_check(context, message)]
    return payload


def parse_controls(args: list[str], *, default_limit: int, max_limit: int) -> tuple[list[str], dict[str, Any]]:
    rest: list[str] = []
    controls: dict[str, Any] = {"limit": default_limit, "cursor": 0, "shape": "compact"}
    index = 0
    while index < len(args):
        token = args[index]
        if token in {"--limit", "--cursor", "--shape"}:
            if index + 1 >= len(args):
                raise ValueError(f"{token} requires a value")
            value = args[index + 1]
            if token == "--limit":
                limit = int(value)
                if limit < 1:
                    raise ValueError("--limit must be at least 1")
                controls["limit"] = min(limit, max_limit)
            elif token == "--cursor":
                cursor = int(value)
                if cursor < 0:
                    raise ValueError("--cursor cannot be negative")
                controls["cursor"] = cursor
            elif token == "--shape":
                if value not in {"compact", "full"}:
                    raise ValueError("--shape must be compact or full")
                controls["shape"] = value
            index += 2
            continue
        rest.append(token)
        index += 1
    return rest, controls


def run_legacy(argv: list[str], *, timeout: float, max_output_bytes: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "argv": argv,
            "exit_code": None,
            "timed_out": True,
            "stdout": (exc.stdout or "")[:max_output_bytes] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[:max_output_bytes] if isinstance(exc.stderr, str) else "",
            "error": f"legacy command timed out after {timeout} seconds",
        }
    return {
        "ok": proc.returncode == 0,
        "argv": argv,
        "exit_code": proc.returncode,
        "timed_out": False,
        "stdout": proc.stdout[:max_output_bytes],
        "stderr": proc.stderr[:max_output_bytes],
        "error": None if proc.returncode == 0 else (proc.stderr.strip() or proc.stdout.strip() or "legacy command failed"),
    }
