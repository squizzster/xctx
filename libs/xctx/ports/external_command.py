"""External-command live connector port.

xctx remains the agent-facing config/protocol layer. Domain tools own their own
SQLite/YAML/API logic behind the connector supervisor, which returns one JSON
object for xctx to envelope.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from xctx.errors import XctxError
from xctx.protocol.actions import action_matches


## Protocol boundary: this port calls scoped connector entrypoints and envelopes
## their JSON. It must not interpret scoped-pack business semantics.


CONNECTOR_SUPERVISOR_ENTRYPOINT = "legacy_connector.py"


def _adapter_error_message_from_text(returncode: int, stdout: str, stderr: str, executable: str) -> str:
    for text in (stdout.strip(), stderr.strip()):
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(payload, dict) and payload.get("error"):
            return str(payload["error"])
        return text
    return f"live adapter returned code {returncode}: {executable}"


def _lawful_argument_guidance(subdomain: dict[str, Any], args: list[str]) -> str:
    command = args[0] if args else "discover"
    for action_name, action in (subdomain.get("actions") or {}).items():
        if action_matches(action_name, action, command) and action.get("run_cmd"):
            return f"adjust arguments for {action['run_cmd']}"
    if subdomain.get("_domain_id") and subdomain.get("id"):
        return f"adjust arguments for ./xctx discover {subdomain['_domain_id']}::{subdomain['id']}"
    return "adjust xctx command arguments"


def _adapter_env(subdomain: dict[str, Any]) -> dict[str, str | None]:
    return {
        "XCTX_AGENT_DOMAIN": str(subdomain["_domain_id"]) if subdomain.get("_domain_id") else None,
        "XCTX_AGENT_SUBDOMAIN": str(subdomain["id"]) if subdomain.get("id") else None,
    }


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
            return
        proc.kill()
    except ProcessLookupError:
        return


def _resolve_entrypoint(root: Path, raw: Any) -> Path:
    if raw is None or str(raw).strip() == "":
        raise XctxError("next valid move: add entrypoint.file to agent_subdomain")
    candidate = Path(str(raw))
    if candidate.is_absolute():
        raise XctxError("next valid move: use a workspace-relative connector entrypoint")
    workspace_root = root.resolve()
    resolved = (workspace_root / candidate).resolve()
    if resolved != workspace_root and workspace_root not in resolved.parents:
        raise XctxError("next valid move: keep connector entrypoint inside the workspace")
    if not resolved.exists():
        raise XctxError(f"next valid move: inspect missing live connector {raw}")
    if not resolved.is_file():
        raise XctxError(f"next valid move: inspect live connector file {raw}")
    return resolved


def _enforce_connector_supervisor(subdomain: dict[str, Any], executable: Any) -> None:
    if not isinstance(subdomain.get("connector"), dict):
        raise XctxError(f"next valid move: add connector block to agent_subdomain {subdomain.get('id')}")
    if Path(str(executable)).as_posix() != CONNECTOR_SUPERVISOR_ENTRYPOINT:
        raise XctxError(f"next valid move: route live subdomain through {CONNECTOR_SUPERVISOR_ENTRYPOINT}")


def _call_python_entrypoint_subprocess(
    store: dict[str, Any],
    command_path: Path,
    args: list[str],
    subdomain: dict[str, Any],
    timeout: float,
) -> tuple[int, str, str]:
    env = os.environ.copy()
    for key, value in _adapter_env(subdomain).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    proc = subprocess.Popen(
        [sys.executable, str(command_path), *args],
        cwd=store["root"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        stdout, stderr = proc.communicate()
        message = f"live connector timed out after {timeout:g} seconds"
        stderr = f"{stderr.rstrip()}\n{message}" if stderr else message
        return 124, stdout, stderr
    return proc.returncode or 0, stdout, stderr


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
        raise XctxError(f"next valid move: add entrypoint.file to agent_subdomain {subdomain.get('id')}")
    _enforce_connector_supervisor(subdomain, executable)

    command_path = _resolve_entrypoint(store["root"], executable)

    compact_flag = entrypoint.get("compact_flag", "--compact")
    timeout = float(entrypoint.get("timeout_seconds", 30))
    command_args = [*args]
    if compact_flag:
        command_args.append(str(compact_flag))

    returncode, stdout, stderr = _call_python_entrypoint_subprocess(store, command_path, command_args, subdomain, timeout)

    if returncode != 0:
        message = _adapter_error_message_from_text(returncode, stdout, stderr, str(executable))
        guidance = _lawful_argument_guidance(subdomain, args)
        raise XctxError(f"next valid move: {guidance} ({message})")

    try:
        payload = json.loads(stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise XctxError(f"next valid move: fix live adapter JSON output for {executable}: {exc}") from exc
    if not isinstance(payload, dict):
        raise XctxError(f"next valid move: fix live adapter output object for {executable}")
    return payload
