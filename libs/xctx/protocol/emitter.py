"""Protocol stdout/stderr emitters."""

from __future__ import annotations

import sys
import time
from typing import Any

import yaml

from xctx.io.stdout import write_stdout_record
from xctx.process.redaction import redact_value
from xctx.protocol.accessors import key_for, protocol_version
from xctx.protocol.detail import detail_level
from xctx.protocol.guidance import normalize_guidance
from xctx.protocol.projection import project_output_envelope, project_record_payload


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
    yaml.safe_dump(redact_value(event), sys.stderr, sort_keys=False, allow_unicode=False)
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
    yaml.safe_dump(redact_value({"final": final}), sys.stderr, sort_keys=False, allow_unicode=False)
    sys.stderr.flush()


def emit_record(
    store: dict[str, Any],
    command: str,
    record_type: str,
    payload: Any,
    ok: bool = True,
    error: str | None = None,
    next_moves: list[Any] | None = None,
    cmdline_arg: str | None = None,
    domain_level: str | None = None,
    error_category: str | None = None,
) -> None:
    public_payload = project_record_payload(
        store,
        record_type,
        payload,
        command=command,
        cmdline_arg=cmdline_arg or command,
        domain_level=domain_level,
    )
    envelope: dict[str, Any] = {}
    for logical_key, default, value in (
        ("version", "version_xctx", protocol_version(store)),
        ("command", "cmdline_arg", cmdline_arg or command),
        ("record_type", None, record_type),
        ("ok", "ok", ok),
        ("detail_level", "detail_level", detail_level(store)),
        ("domain_level", None, domain_level),
        ("payload", "results", public_payload),
    ):
        output_key = key_for(store, logical_key, default)
        if output_key and value is not None:
            envelope[output_key] = value
    if error:
        envelope[key_for(store, "error", "error")] = error
    if error_category:
        envelope["error_category"] = str(error_category)
    if next_moves:
        envelope["next_moves"] = next_moves
    public_envelope = project_output_envelope(store, envelope)
    write_stdout_record(redact_value(normalize_guidance(public_envelope)), store.get("output_format", "jsonl"))


def emit_raw_for_store(store: dict[str, Any], payload: dict[str, Any]) -> None:
    raw = dict(payload)
    raw.setdefault("detail_level", detail_level(store))
    public_raw = project_output_envelope(store, raw)
    write_stdout_record(redact_value(normalize_guidance(public_raw)), store.get("output_format", "jsonl"))


def emit_minimal_error(
    command: str,
    message: str,
    next_moves: list[Any] | None = None,
    version: str = "v4.2",
    output_format: str = "jsonl",
    error_category: str = "framework_bug",
) -> None:
    payload: dict[str, Any] = {
        "version_xctx": version,
        "cmdline_arg": command,
        "record_type": "error",
        "ok": False,
        "detail_level": "basic",
        "results": {},
        "error": str(message),
        "error_category": str(error_category),
    }
    if next_moves:
        payload["next_moves"] = next_moves
    write_stdout_record(redact_value(normalize_guidance(payload)), output_format)
