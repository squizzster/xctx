"""Generic runtime helpers for xctx connector middleware."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


CONNECTOR_VERSION = "legacy_connector.v1"
DEFAULT_MAX_OUTPUT_BYTES = 65536
MAX_CAPTURE_BYTES = 1048576
MIN_TIMEOUT_SECONDS = 0.05
MAX_TIMEOUT_SECONDS = 300.0
SAFE_ENV_KEYS = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "TMPDIR",
    "VIRTUAL_ENV",
}


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


def validated_timeout(value: Any, *, label: str = "timeout_seconds") -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if timeout != timeout or timeout < MIN_TIMEOUT_SECONDS or timeout > MAX_TIMEOUT_SECONDS:
        raise ValueError(f"{label} must be between {MIN_TIMEOUT_SECONDS:g} and {MAX_TIMEOUT_SECONDS:g}")
    return timeout


def validated_max_output_bytes(value: Any, *, label: str = "max_output_bytes") -> int:
    try:
        max_bytes = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if max_bytes < 1024 or max_bytes > MAX_CAPTURE_BYTES:
        raise ValueError(f"{label} must be between 1024 and {MAX_CAPTURE_BYTES}")
    return max_bytes


def sanitized_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
    for key, value in (extra or {}).items():
        if key in SAFE_ENV_KEYS or key.startswith("XCTX_"):
            env[key] = str(value)
    return env


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


def _append_limited(buffer: bytearray, chunk: bytes, max_output_bytes: int) -> None:
    if len(buffer) >= max_output_bytes:
        return
    remaining = max_output_bytes - len(buffer)
    buffer.extend(chunk[:remaining])


def _decode_output(buffer: bytearray) -> str:
    return bytes(buffer).decode("utf-8", errors="replace")


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
            return
        proc.kill()
    except ProcessLookupError:
        return


def run_external(
    argv: list[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    max_output_bytes: int | None = None,
) -> dict[str, Any]:
    timeout = validated_timeout(timeout)
    max_bytes = validated_max_output_bytes(max_output_bytes or DEFAULT_MAX_OUTPUT_BYTES)
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=sanitized_env(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"),
    )
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    buffers = {"stdout": stdout_buffer, "stderr": stderr_buffer}
    selector = selectors.DefaultSelector()
    assert proc.stdout is not None
    assert proc.stderr is not None
    selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
    selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
    deadline = time.monotonic() + timeout
    timed_out = False

    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            _kill_process_tree(proc)
            break
        events = selector.select(timeout=remaining)
        if not events:
            continue
        for key, _mask in events:
            stream = key.fileobj
            chunk = os.read(stream.fileno(), 8192)
            if not chunk:
                selector.unregister(stream)
                continue
            _append_limited(buffers[str(key.data)], chunk, max_bytes)

    for stream in (proc.stdout, proc.stderr):
        try:
            selector.unregister(stream)
        except Exception:
            pass
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        proc.wait(timeout=1)
    stdout = _decode_output(stdout_buffer)
    stderr = _decode_output(stderr_buffer)
    if timed_out:
        return {
            "ok": False,
            "argv": argv,
            "exit_code": None,
            "timed_out": True,
            "stdout": stdout,
            "stderr": stderr,
            "error": f"external command timed out after {timeout:g} seconds",
        }
    return {
        "ok": (proc.returncode or 0) == 0,
        "argv": argv,
        "exit_code": proc.returncode or 0,
        "timed_out": False,
        "stdout": stdout,
        "stderr": stderr,
        "error": None
        if (proc.returncode or 0) == 0
        else ((stderr or "").strip() or (stdout or "").strip() or "external command failed"),
    }


def run_legacy(argv: list[str], *, timeout: float, max_output_bytes: int) -> dict[str, Any]:
    result = run_external(argv, timeout=timeout, max_output_bytes=max_output_bytes)
    if result["timed_out"]:
        result["error"] = f"legacy command timed out after {timeout:g} seconds"
    elif not result["ok"] and result["error"] == "external command failed":
        result["error"] = "legacy command failed"
    return result
