"""External-command live adapter port.

xctx remains the agent-facing config/protocol layer. Domain tools own their own
SQLite/YAML/API logic and return one JSON object for xctx to envelope. Python
entrypoints are executed in-process by default for fast agent loops, while the
same files remain runnable as standalone external commands.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from xctx.errors import XctxError
from xctx.protocol.actions import action_matches


## Protocol boundary: this port calls scoped adapter entrypoints and envelopes
## their JSON. It must not interpret scoped-pack business semantics.


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


def _adapter_error_message(proc: subprocess.CompletedProcess[str], executable: str) -> str:
    return _adapter_error_message_from_text(proc.returncode, proc.stdout, proc.stderr, executable)


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


def _apply_env(env_values: dict[str, str | None]) -> dict[str, str | None]:
    old: dict[str, str | None] = {}
    for key, value in env_values.items():
        old[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return old


def _restore_env(old: dict[str, str | None]) -> None:
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _call_python_entrypoint_in_process(command_path: Path, args: list[str], subdomain: dict[str, Any]) -> tuple[int, str, str]:
    module_name = f"_xctx_adapter_{command_path.stem}_{abs(hash(str(command_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, command_path)
    if spec is None or spec.loader is None:
        raise XctxError(f"next valid move: inspect live adapter import path {command_path}")
    module = importlib.util.module_from_spec(spec)
    out = io.StringIO()
    err = io.StringIO()
    old_env = _apply_env(_adapter_env(subdomain))
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            spec.loader.exec_module(module)
            main = getattr(module, "main", None)
            if not callable(main):
                return 2, out.getvalue(), f"adapter has no callable main(argv): {command_path}"
            try:
                return_code = main(list(args))
            except SystemExit as exc:
                return_code = int(exc.code or 0) if isinstance(exc.code, int) else 1
    finally:
        _restore_env(old_env)
    return int(return_code or 0), out.getvalue(), err.getvalue()


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
    proc = subprocess.run(
        [sys.executable, str(command_path), *args],
        cwd=store["root"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def call_external_command(
    store: dict[str, Any],
    subdomain: dict[str, Any],
    args: list[str],
) -> dict[str, Any]:
    ## Boundary guard: adapter args are selected by YAML routing before this
    ## point. This function executes the declared port and validates JSON shape.
    entrypoint = subdomain.get("entrypoint") or {}
    executable = entrypoint.get("file") or entrypoint.get("command")
    if not executable:
        raise XctxError(f"next valid move: add entrypoint.file to agent_subdomain {subdomain.get('id')}")

    command_path = store["root"] / str(executable)
    if not command_path.exists():
        raise XctxError(f"next valid move: inspect missing live adapter {executable}")

    compact_flag = entrypoint.get("compact_flag", "--compact")
    timeout = float(entrypoint.get("timeout_seconds", 30))
    command_args = [*args]
    if compact_flag:
        command_args.append(str(compact_flag))

    force_subprocess = os.environ.get("XCTX_FORCE_SUBPROCESS_ADAPTER") == "1"
    if command_path.suffix == ".py" and not force_subprocess:
        returncode, stdout, stderr = _call_python_entrypoint_in_process(command_path, command_args, subdomain)
    else:
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
