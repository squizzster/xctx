"""External-command live connector port.

xctx remains the agent-facing config/protocol layer. Domain tools own their own
SQLite/YAML/API logic behind the connector supervisor, which returns one JSON
object for xctx to envelope.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from xctx.errors import XctxError
from xctx.process.capture import capture_process
from xctx.process.env import SAFE_ENV_KEYS, sanitized_env
from xctx.process.limits import ConnectorLimits
from xctx.process.python_subprocess import python_entrypoint_argv
from xctx.process.redaction import redact_preview
from xctx.protocol.actions import action_matches
from xctx.store.fingerprints import config_fingerprint_payload
from xctx.store.runtime_artifacts import isoformat_utc, runtime_root, utc_now


## Protocol boundary: this port calls scoped connector entrypoints and envelopes
## their JSON. It must not interpret scoped-pack business semantics.


CONNECTOR_SUPERVISOR_ENTRYPOINT = "connector_supervisor.py"
RESOLVED_CONTEXT_ENV = "XCTX_RESOLVED_CONTEXT_FILE"
CONFIG_FINGERPRINT_ENV = "XCTX_CONFIG_FINGERPRINT"
RESOLVED_CONTEXT_DIR_NAME = "resolved_contexts"


def _empty_capture_metadata(max_output_bytes: int) -> dict[str, Any]:
    return {
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout_captured_bytes": 0,
        "stderr_captured_bytes": 0,
        "stdout_total_bytes": 0,
        "stderr_total_bytes": 0,
        "max_output_bytes": max_output_bytes,
    }


def _capture_metadata(captured: Any) -> dict[str, Any]:
    return {
        "stdout_truncated": bool(getattr(captured, "stdout_truncated", False)),
        "stderr_truncated": bool(getattr(captured, "stderr_truncated", False)),
        "stdout_captured_bytes": int(getattr(captured, "stdout_captured_bytes", 0) or 0),
        "stderr_captured_bytes": int(getattr(captured, "stderr_captured_bytes", 0) or 0),
        "stdout_total_bytes": int(getattr(captured, "stdout_total_bytes", 0) or 0),
        "stderr_total_bytes": int(getattr(captured, "stderr_total_bytes", 0) or 0),
        "max_output_bytes": int(getattr(captured, "max_output_bytes", 0) or 0),
    }


def _output_limit_message(metadata: dict[str, Any]) -> str | None:
    if metadata.get("stdout_truncated"):
        return (
            "live adapter stdout exceeded max_output_bytes "
            f"({metadata.get('stdout_captured_bytes')}/{metadata.get('stdout_total_bytes')} bytes captured)"
        )
    if metadata.get("stderr_truncated"):
        return (
            "live adapter stderr exceeded max_output_bytes "
            f"({metadata.get('stderr_captured_bytes')}/{metadata.get('stderr_total_bytes')} bytes captured)"
        )
    return None


def _adapter_error_message_from_text(returncode: int | None, stdout: str, stderr: str, executable: str) -> str:
    for text in (stdout.strip(), stderr.strip()):
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return redact_preview(text)
        if isinstance(payload, dict) and payload.get("error"):
            return redact_preview(payload["error"])
        return redact_preview(text)
    return f"live adapter returned code {returncode}: {executable}"


def _lawful_argument_run_cmd(subdomain: dict[str, Any], args: list[str]) -> str | None:
    command = args[0] if args else "discover"
    for action_name, action in (subdomain.get("actions") or {}).items():
        if action_matches(action_name, action, command) and action.get("run_cmd"):
            return str(action["run_cmd"])
    if subdomain.get("_domain_id") and subdomain.get("id"):
        return f"./xctx discover {subdomain['_domain_id']}::{subdomain['id']}"
    return None


def _adapter_env(
    store: dict[str, Any],
    subdomain: dict[str, Any] | None = None,
    *,
    resolved_context_path: Path | None = None,
    config_fingerprint: str | None = None,
) -> dict[str, str | None]:
    """Return the sanitized connector environment for a scoped subdomain.

    ``store`` is the framework runtime store; ``subdomain`` is the resolved
    scoped subdomain. A single-argument call is tolerated for isolated private
    helper tests and is treated as ``subdomain`` with default basic detail.
    """

    if subdomain is None:
        subdomain = store
        store = {}
    env = {
        "XCTX_AGENT_DOMAIN": str(subdomain["_domain_id"]) if subdomain.get("_domain_id") else None,
        "XCTX_AGENT_SUBDOMAIN": str(subdomain["id"]) if subdomain.get("id") else None,
        "XCTX_DETAIL_LEVEL": str(store.get("detail_level") or "basic"),
        "XCTX_RUNTIME_DIR": os.environ.get("XCTX_RUNTIME_DIR"),
    }
    if resolved_context_path is not None:
        env[RESOLVED_CONTEXT_ENV] = str(resolved_context_path)
    if config_fingerprint is not None:
        env[CONFIG_FINGERPRINT_ENV] = config_fingerprint
    connector = subdomain.get("connector") or {}
    for key in connector.get("env_passthrough") or []:
        text_key = str(key)
        if text_key in os.environ and (text_key in SAFE_ENV_KEYS or text_key.startswith("XCTX_")):
            env[text_key] = os.environ[text_key]
    return env


def _as_xctx_error(message: str) -> XctxError:
    return XctxError(f"invalid connector limit: {message}")


def _resolve_entrypoint(root: Path, raw: Any) -> Path:
    if raw is None or str(raw).strip() == "":
        raise XctxError("agent_subdomain is missing entrypoint.file")
    candidate = Path(str(raw))
    if candidate.is_absolute():
        raise XctxError("connector entrypoint must be workspace-relative")
    workspace_root = root.resolve()
    resolved = (workspace_root / candidate).resolve()
    if resolved != workspace_root and workspace_root not in resolved.parents:
        raise XctxError("connector entrypoint resolves outside the workspace")
    if not resolved.exists():
        raise XctxError(f"missing live connector: {raw}")
    if not resolved.is_file():
        raise XctxError(f"live connector is not a file: {raw}")
    return resolved


def _enforce_connector_supervisor(subdomain: dict[str, Any], executable: Any) -> None:
    if not isinstance(subdomain.get("connector"), dict):
        raise XctxError(f"agent_subdomain is missing connector block: {subdomain.get('id')}")
    if Path(str(executable)).as_posix() != CONNECTOR_SUPERVISOR_ENTRYPOINT:
        raise XctxError(f"live subdomain must route through {CONNECTOR_SUPERVISOR_ENTRYPOINT}")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _write_resolved_connector_context(
    store: dict[str, Any],
    subdomain: dict[str, Any],
    args: list[str],
) -> tuple[Path, dict[str, Any]]:
    fingerprint = config_fingerprint_payload(store)
    payload = {
        "object_type": "xctx_resolved_connector_context",
        "schema_version": "xctx.connector_context.v1",
        "created_at": isoformat_utc(utc_now()),
        "config_fingerprint": fingerprint["sha256"],
        "config_fingerprint_payload": fingerprint,
        "domain_id": str(subdomain.get("_domain_id") or ""),
        "subdomain_id": str(subdomain.get("id") or ""),
        "connector_kind": str((subdomain.get("connector") or {}).get("kind") or "xctx_native_passthrough"),
        "detail_level": str(store.get("detail_level") or "basic"),
        "command_args": [str(arg) for arg in args],
        "subdomain": _json_safe(subdomain),
    }
    directory = runtime_root(store) / RESOLVED_CONTEXT_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{os.getpid()}-{secrets.token_hex(16)}.json"
    data = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        directory_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return path, payload
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return path, payload


def _call_python_entrypoint_subprocess(
    store: dict[str, Any],
    command_path: Path,
    args: list[str],
    subdomain: dict[str, Any],
    timeout: float,
    max_output_bytes: int,
    resolved_context_path: Path,
    config_fingerprint: str,
) -> tuple[int | None, str, str, dict[str, Any]]:
    try:
        captured = capture_process(
            python_entrypoint_argv(command_path, args),
            cwd=store["root"],
            env=sanitized_env(
                _adapter_env(
                    store,
                    subdomain,
                    resolved_context_path=resolved_context_path,
                    config_fingerprint=config_fingerprint,
                )
            ),
            timeout=timeout,
            max_output_bytes=max_output_bytes,
        )
    except OSError as exc:
        return 127, "", redact_preview(str(exc)), _empty_capture_metadata(max_output_bytes)
    metadata = _capture_metadata(captured)
    stderr = captured.stderr
    if captured.timed_out:
        message = f"live connector timed out after {timeout:g} seconds"
        stderr = f"{stderr.rstrip()}\n{message}" if stderr else message
        return 124, captured.stdout, stderr, metadata
    return captured.returncode, captured.stdout, stderr, metadata


def call_external_command(
    store: dict[str, Any],
    subdomain: dict[str, Any],
    args: list[str],
) -> dict[str, Any]:
    ## Boundary guard: adapter args are selected by YAML routing before this
    ## point. This function executes the declared port and validates the JSON object contract.
    entrypoint = subdomain.get("entrypoint") or {}
    executable = entrypoint.get("file")
    if not executable:
        raise XctxError(f"agent_subdomain is missing entrypoint.file: {subdomain.get('id')}")
    _enforce_connector_supervisor(subdomain, executable)

    command_path = _resolve_entrypoint(store["root"], executable)

    limits = ConnectorLimits.from_config(
        entrypoint,
        default_timeout_seconds=30,
        label_prefix="entrypoint",
        error_type=_as_xctx_error,
    )
    command_args = [*args]
    resolved_context_path, resolved_context = _write_resolved_connector_context(store, subdomain, command_args)

    subprocess_result = _call_python_entrypoint_subprocess(
        store,
        command_path,
        command_args,
        subdomain,
        limits.timeout_seconds,
        limits.max_output_bytes,
        resolved_context_path,
        str(resolved_context["config_fingerprint"]),
    )
    if len(subprocess_result) == 3:
        returncode, stdout, stderr = subprocess_result
        output_metadata = _empty_capture_metadata(limits.max_output_bytes)
    else:
        returncode, stdout, stderr, output_metadata = subprocess_result

    if returncode != 0:
        message = _output_limit_message(output_metadata) or _adapter_error_message_from_text(
            returncode,
            stdout,
            stderr,
            str(executable),
        )
        run_cmd = _lawful_argument_run_cmd(subdomain, args)
        raise XctxError(
            f"live adapter failed for {executable}: {message}",
            next_moves=[run_cmd] if run_cmd else None,
        )

    if output_metadata.get("stdout_truncated"):
        raise XctxError(_output_limit_message(output_metadata) or f"live adapter stdout exceeded max_output_bytes for {executable}")

    try:
        payload = json.loads(stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise XctxError(f"invalid live adapter JSON output for {executable}: {exc}") from exc
    if not isinstance(payload, dict):
        raise XctxError(f"live adapter output must be a JSON object: {executable}")
    return payload
