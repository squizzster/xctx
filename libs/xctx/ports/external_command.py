"""External-command live connector port.

xctx remains the agent-facing config/protocol layer. Domain tools own their own
SQLite/YAML/API logic behind the connector supervisor, which returns one JSON
object for xctx to envelope.
"""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from xctx.errors import XctxError
from xctx.protocol.actions import action_matches


## Protocol boundary: this port calls scoped connector entrypoints and envelopes
## their JSON. It must not interpret scoped-pack business semantics.


CONNECTOR_SUPERVISOR_ENTRYPOINT = "connector_supervisor.py"
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


def _validated_timeout(value: Any, *, label: str = "timeout_seconds") -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise XctxError(f"next valid move: set {label} to a number") from exc
    if timeout != timeout or timeout < MIN_TIMEOUT_SECONDS or timeout > MAX_TIMEOUT_SECONDS:
        raise XctxError(f"next valid move: set {label} between {MIN_TIMEOUT_SECONDS:g} and {MAX_TIMEOUT_SECONDS:g}")
    return timeout


def _validated_max_output_bytes(value: Any, *, label: str = "max_output_bytes") -> int:
    try:
        max_bytes = int(value)
    except (TypeError, ValueError) as exc:
        raise XctxError(f"next valid move: set {label} to an integer") from exc
    if max_bytes < 1024 or max_bytes > MAX_CAPTURE_BYTES:
        raise XctxError(f"next valid move: set {label} between 1024 and {MAX_CAPTURE_BYTES}")
    return max_bytes


def _sanitized_env(extra: dict[str, str | None]) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
    for key, value in extra.items():
        if value is None:
            env.pop(key, None)
        elif key in SAFE_ENV_KEYS or key.startswith("XCTX_"):
            env[key] = str(value)
    return env


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
            return
        proc.kill()
    except ProcessLookupError:
        return


def _append_limited(buffer: bytearray, chunk: bytes, max_output_bytes: int) -> None:
    if len(buffer) >= max_output_bytes:
        return
    remaining = max_output_bytes - len(buffer)
    buffer.extend(chunk[:remaining])


def _decode_output(buffer: bytearray) -> str:
    return bytes(buffer).decode("utf-8", errors="replace")


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
    max_output_bytes: int,
) -> tuple[int, str, str]:
    env = _sanitized_env(_adapter_env(subdomain))
    proc = subprocess.Popen(
        [sys.executable, str(command_path), *args],
        cwd=store["root"],
        env=env,
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
            _append_limited(buffers[str(key.data)], chunk, max_output_bytes)

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
        guidance = _lawful_argument_guidance(subdomain, args)
        raise XctxError(f"next valid move: {guidance} ({message})")

    try:
        payload = json.loads(stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise XctxError(f"next valid move: fix live adapter JSON output for {executable}: {exc}") from exc
    if not isinstance(payload, dict):
        raise XctxError(f"next valid move: fix live adapter output object for {executable}")
    return payload
