"""External-command live connector port.

xctx remains the agent-facing config/protocol layer. Domain tools own their own
SQLite/YAML/API logic behind the connector supervisor, which returns one JSON
object for xctx to envelope.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from xctx.errors import XctxError
from xctx.process.capture import capture_process
from xctx.process.env import SAFE_ENV_KEYS, sanitized_env
from xctx.process.limits import (
    DEFAULT_MAX_OUTPUT_BYTES,
    MAX_CAPTURE_BYTES,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    validated_max_output_bytes,
    validated_timeout,
)
from xctx.process.python_subprocess import python_entrypoint_argv
from xctx.process.redaction import redact_preview
from xctx.protocol.actions import action_matches


## Protocol boundary: this port calls scoped connector entrypoints and envelopes
## their JSON. It must not interpret scoped-pack business semantics.


CONNECTOR_SUPERVISOR_ENTRYPOINT = "connector_supervisor.py"

def _adapter_error_message_from_text(returncode: int, stdout: str, stderr: str, executable: str) -> str:
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


def _adapter_env(subdomain: dict[str, Any]) -> dict[str, str | None]:
    return {
        "XCTX_AGENT_DOMAIN": str(subdomain["_domain_id"]) if subdomain.get("_domain_id") else None,
        "XCTX_AGENT_SUBDOMAIN": str(subdomain["id"]) if subdomain.get("id") else None,
        "XCTX_RUNTIME_DIR": os.environ.get("XCTX_RUNTIME_DIR"),
    }


def _as_xctx_error(message: str) -> XctxError:
    return XctxError(f"invalid connector limit: {message}")


def _validated_timeout(value: Any, *, label: str = "timeout_seconds") -> float:
    return validated_timeout(value, label=label, error_type=_as_xctx_error)


def _validated_max_output_bytes(value: Any, *, label: str = "max_output_bytes") -> int:
    return validated_max_output_bytes(value, label=label, error_type=_as_xctx_error)


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


def _call_python_entrypoint_subprocess(
    store: dict[str, Any],
    command_path: Path,
    args: list[str],
    subdomain: dict[str, Any],
    timeout: float,
    max_output_bytes: int,
) -> tuple[int, str, str]:
    try:
        captured = capture_process(
            python_entrypoint_argv(command_path, args),
            cwd=store["root"],
            env=sanitized_env(_adapter_env(subdomain)),
            timeout=timeout,
            max_output_bytes=max_output_bytes,
        )
    except OSError as exc:
        return 127, "", redact_preview(str(exc))
    stderr = captured.stderr
    if captured.timed_out:
        message = f"live connector timed out after {timeout:g} seconds"
        stderr = f"{stderr.rstrip()}\n{message}" if stderr else message
        return 124, captured.stdout, stderr
    return captured.returncode or 0, captured.stdout, stderr


def call_external_command(
    store: dict[str, Any],
    subdomain: dict[str, Any],
    args: list[str],
) -> dict[str, Any]:
    ## Boundary guard: adapter args are selected by YAML routing before this
    ## point. This function executes the declared port and validates JSON shape.
    entrypoint = subdomain.get("entrypoint") or {}
    executable = entrypoint.get("file")
    if not executable:
        raise XctxError(f"agent_subdomain is missing entrypoint.file: {subdomain.get('id')}")
    _enforce_connector_supervisor(subdomain, executable)

    command_path = _resolve_entrypoint(store["root"], executable)

    compact_flag = entrypoint.get("compact_flag", "--compact")
    timeout = _validated_timeout(entrypoint.get("timeout_seconds", 30))
    max_output_bytes = _validated_max_output_bytes(entrypoint.get("max_output_bytes", DEFAULT_MAX_OUTPUT_BYTES))
    command_args = [*args]
    if compact_flag:
        command_args.append(str(compact_flag))

    returncode, stdout, stderr = _call_python_entrypoint_subprocess(
        store,
        command_path,
        command_args,
        subdomain,
        timeout,
        max_output_bytes,
    )

    if returncode != 0:
        message = _adapter_error_message_from_text(returncode, stdout, stderr, str(executable))
        run_cmd = _lawful_argument_run_cmd(subdomain, args)
        raise XctxError(
            f"live adapter failed for {executable}: {message}",
            next_moves=[run_cmd] if run_cmd else None,
        )

    try:
        payload = json.loads(stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise XctxError(f"invalid live adapter JSON output for {executable}: {exc}") from exc
    if not isinstance(payload, dict):
        raise XctxError(f"live adapter output must be a JSON object: {executable}")
    return payload
