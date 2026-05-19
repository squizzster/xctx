"""status command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.domain.status_payloads import build_status_payload
from xctx.protocol.accessors import response_template
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "status"
    emit_stderr_event(store, command, "start", "loading high-level status")
    payload = build_status_payload(store)
    emit_record(store, command, "result", payload, cmdline_arg=cmdline_arg(args, command))
    status_key = response_template(store, "status").get("overall_status_key", "overall_status")
    ok = payload[status_key] != "fail"
    emit_final_stderr(store, command, ok, "status complete", records=1)
    return 0 if ok else 2
