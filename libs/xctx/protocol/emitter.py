"""Protocol stdout/stderr emitters."""

from __future__ import annotations

import sys
import time
from typing import Any

import yaml

from xctx.io.stdout import write_stdout_record
from xctx.protocol.accessors import key_for, protocol_version


def now_ms() -> int:
    return int(time.time() * 1000)


def emit_stderr_event(store: dict[str, Any], command: str, stage: str, message: str, **extra: Any) -> None:
    if not store.get("protocol", {}).get("stderr", {}).get("emit_for_instant_yaml", False):
        return
    event = {
        "xctx_event": {
            "command": command,
            "stage": stage,
            "message": message,
            "time_unix_ms": now_ms(),
        }
    }
    event["xctx_event"].update(extra)
    sys.stderr.write("---\n")
    yaml.safe_dump(event, sys.stderr, sort_keys=False, allow_unicode=False)
    sys.stderr.flush()


def emit_final_stderr(store: dict[str, Any], command: str, ok: bool, summary: str, **extra: Any) -> None:
    if not store.get("protocol", {}).get("stderr", {}).get("emit_for_instant_yaml", False):
        return
    final = {
        "command": command,
        "ok": ok,
        "summary": summary,
        "time_unix_ms": now_ms(),
    }
    final.update(extra)
    sys.stderr.write("---\n")
    yaml.safe_dump({"final": final}, sys.stderr, sort_keys=False, allow_unicode=False)
    sys.stderr.flush()


def emit_record(
    store: dict[str, Any],
    command: str,
    record_type: str,
    payload: Any,
    ok: bool = True,
    error: str | None = None,
    cmdline_arg: str | None = None,
    domain_level: str | None = None,
) -> None:
    envelope: dict[str, Any] = {}
    for logical_key, default, value in (
        ("version", "version_xctx", protocol_version(store)),
        ("command", "cmdline_arg", cmdline_arg or command),
        ("record_type", None, record_type),
        ("ok", "ok", ok),
        ("domain_level", None, domain_level),
        ("payload", "results", payload),
    ):
        output_key = key_for(store, logical_key, default)
        if output_key and value is not None:
            envelope[output_key] = value
    if error:
        envelope[key_for(store, "error", "error")] = error
    write_stdout_record(envelope, store.get("output_format", "jsonl"))


def emit_raw_for_store(store: dict[str, Any], payload: dict[str, Any]) -> None:
    write_stdout_record(payload, store.get("output_format", "jsonl"))


def emit_minimal_error(
    command: str,
    message: str,
    version: str = "v4.2",
    output_format: str = "jsonl",
) -> None:
    write_stdout_record(
        {
            "version_xctx": version,
            "cmdline_arg": command,
            "record_type": "error",
            "ok": False,
            "results": {},
            "error": str(message),
        },
        output_format,
    )
