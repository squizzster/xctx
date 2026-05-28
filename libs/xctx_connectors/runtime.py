"""Generic runtime helpers for xctx connector middleware."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from xctx.process.capture import capture_process
from xctx.process.env import SAFE_ENV_KEYS, sanitized_env
from xctx.process.limits import ConnectorLimits
from xctx.process.redaction import redact_argv_values, redact_preview, redact_value
from xctx.protocol.guidance import command_hints


CONNECTOR_VERSION = "xctx_connector.v1"
CAPTURE_METADATA_KEYS = (
    "stdout_truncated",
    "stderr_truncated",
    "stdout_captured_bytes",
    "stderr_captured_bytes",
    "stdout_total_bytes",
    "stderr_total_bytes",
    "max_output_bytes",
)


@dataclass(frozen=True)
class ConnectorContext:
    workspace_root: Path
    domain_id: str
    subdomain_id: str
    subdomain_config: Mapping[str, Any]
    connector_config: Mapping[str, Any]
    limits: ConnectorLimits = ConnectorLimits.from_values()
    detail_level: str = "basic"

    @property
    def adapter_ref(self) -> str:
        return f"{self.domain_id}::{self.subdomain_id}"


def readonly_value(value: Any) -> Any:
    if isinstance(value, MappingABC):
        return MappingProxyType({key: readonly_value(item) for key, item in value.items()})
    if isinstance(value, tuple):
        return tuple(readonly_value(item) for item in value)
    if isinstance(value, list):
        return tuple(readonly_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(readonly_value(item) for item in value)
    return value


def readonly_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen = readonly_value(value)
    if not isinstance(frozen, MappingABC):
        raise TypeError("readonly_mapping requires a mapping")
    return frozen


def payload_contract(kind: str) -> dict[str, str]:
    base = {
        "xctx_receives": "single_json_object_for_live_data",
        "raw_external_output": "never_returned_unparsed",
        "stdout_stderr": "summarized_in_command_status_when_useful",
    }
    if kind == "external_command":
        return {
            **base,
            "contract": "always_json_object",
            "success_payload": "domain_object",
            "failure_payload": "xctx_connector_error",
        }
    if kind == "xctx_native_passthrough":
        return {
            **base,
            "contract": "pass_through_json_object",
            "success_payload": "target_adapter_object",
            "failure_payload": "xctx_native_passthrough_error",
        }
    return {
        **base,
        "contract": "always_json_object",
        "success_payload": "connector_object",
        "failure_payload": "xctx_connector_error",
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
        "payload_contract": payload_contract(kind),
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
        payload["argv"] = redact_argv_values(argv)
    if error:
        payload["error"] = redact_preview(error)
    if stdout is not None:
        payload["stdout_preview"] = redact_preview(stdout)
    if stderr is not None:
        payload["stderr_preview"] = redact_preview(stderr)
    return {key: value for key, value in payload.items() if value is not None}


def sanitized_connector_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    return sanitized_env(extra)


def command_status_from_external_result(result: Mapping[str, Any], *, include_argv: bool = True) -> dict[str, Any]:
    payload = command_status(
        ok=bool(result["ok"]),
        argv=list(result["argv"]) if include_argv else None,
        exit_code=result["exit_code"],
        timed_out=bool(result["timed_out"]),
        error=result.get("error"),
        stderr=result.get("stderr"),
    )
    payload.update(capture_metadata_from_result(result))
    return payload


def capture_metadata_from_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in CAPTURE_METADATA_KEYS if key in result}


def audit_failure_check(context: ConnectorContext | None, message: str) -> dict[str, Any]:
    domain_id = context.domain_id if context else "unknown_domain"
    subdomain_id = context.subdomain_id if context else "unknown_subdomain"
    return {
        "id": f"audit:{domain_id}:{subdomain_id}:middleware_connector",
        "status": "fail",
        "message": redact_preview(message),
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
        "object_type": "xctx_connector_error",
        "found": False,
        "connector": connector_meta(context, connector),
        "requested_command": command,
        "requested_args": redact_value(args or []),
        "command_status": command_status(ok=False, error=message),
        "data_boundary": "Middleware error payload. xctx received a structured object instead of raw connector failure output.",
        "next_moves": command_hints(next_moves),
    }
    if command == "audit":
        payload["checks"] = [audit_failure_check(context, message)]
    return payload


def detail_is_max(context: ConnectorContext | None) -> bool:
    return bool(context and context.detail_level == "max")


def parse_controls(args: list[str], *, default_limit: int, max_limit: int) -> tuple[list[str], dict[str, Any]]:
    rest: list[str] = []
    controls: dict[str, Any] = {"limit": default_limit, "cursor": 0, "projection": "compact"}
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--shape":
            raise ValueError("unsupported --shape; use --projection compact|full")
        if token in {"--limit", "--cursor", "--projection"}:
            if index + 1 >= len(args):
                raise ValueError(f"{token} requires a value")
            value = args[index + 1]
            if token == "--limit":
                try:
                    limit = int(value)
                except ValueError as exc:
                    raise ValueError("--limit requires an integer") from exc
                if limit < 1:
                    raise ValueError("--limit must be at least 1")
                if limit > max_limit:
                    raise ValueError(f"--limit exceeds maximum {max_limit}")
                controls["limit"] = limit
            elif token == "--cursor":
                try:
                    cursor = int(value)
                except ValueError as exc:
                    raise ValueError("--cursor requires an integer") from exc
                if cursor < 0:
                    raise ValueError("--cursor cannot be negative")
                controls["cursor"] = cursor
            elif token == "--projection":
                if value not in {"compact", "full"}:
                    raise ValueError("--projection must be compact or full")
                controls["projection"] = value
            index += 2
            continue
        rest.append(token)
        index += 1
    return rest, controls


def run_external(
    argv: list[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    max_output_bytes: int | None = None,
) -> dict[str, Any]:
    argv = [str(part) for part in argv]
    if not argv or not argv[0].strip():
        return {
            "ok": False,
            "argv": argv,
            "exit_code": None,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "error": "external command argv must not be empty",
        }
    limit_kwargs: dict[str, Any] = {"timeout_seconds": timeout}
    if max_output_bytes is not None:
        limit_kwargs["max_output_bytes"] = max_output_bytes
    limits = ConnectorLimits.from_values(
        **limit_kwargs,
        timeout_label="timeout_seconds",
        max_output_label="max_output_bytes",
    )
    try:
        captured = capture_process(
            argv,
            cwd=cwd,
            env=sanitized_connector_env(env),
            timeout=limits.timeout_seconds,
            max_output_bytes=limits.max_output_bytes,
        )
    except OSError as exc:
        return {
            "ok": False,
            "argv": argv,
            "exit_code": None,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "error": str(exc),
        }
    if captured.timed_out:
        return {
            "ok": False,
            "argv": argv,
            "exit_code": None,
            "timed_out": True,
            "stdout": captured.stdout,
            "stderr": captured.stderr,
            "stdout_truncated": captured.stdout_truncated,
            "stderr_truncated": captured.stderr_truncated,
            "stdout_captured_bytes": captured.stdout_captured_bytes,
            "stderr_captured_bytes": captured.stderr_captured_bytes,
            "stdout_total_bytes": captured.stdout_total_bytes,
            "stderr_total_bytes": captured.stderr_total_bytes,
            "max_output_bytes": captured.max_output_bytes,
            "error": f"external command timed out after {limits.timeout_seconds:g} seconds",
        }
    return {
        "ok": captured.ok,
        "argv": argv,
        "exit_code": captured.returncode,
        "timed_out": False,
        "stdout": captured.stdout,
        "stderr": captured.stderr,
        "stdout_truncated": captured.stdout_truncated,
        "stderr_truncated": captured.stderr_truncated,
        "stdout_captured_bytes": captured.stdout_captured_bytes,
        "stderr_captured_bytes": captured.stderr_captured_bytes,
        "stdout_total_bytes": captured.stdout_total_bytes,
        "stderr_total_bytes": captured.stderr_total_bytes,
        "max_output_bytes": captured.max_output_bytes,
        "error": None
        if captured.ok
        else ((captured.stderr or "").strip() or (captured.stdout or "").strip() or "external command failed"),
    }


def run_command(argv: list[str], *, timeout: float, max_output_bytes: int) -> dict[str, Any]:
    result = run_external(argv, timeout=timeout, max_output_bytes=max_output_bytes)
    if result["timed_out"]:
        result["error"] = f"external command timed out after {timeout:g} seconds"
    elif not result["ok"] and result["error"] == "external command failed":
        result["error"] = "external command failed"
    return result
