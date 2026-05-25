"""execute command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.domain.planning import execute_payload
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "execute"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "checking execute boundary", args=args.execute_args)
    payload = execute_payload(list(args.execute_args), args.commit, store)
    ok = bool(payload.pop("ok", False))
    error = payload.pop("error", None)
    emit_record(
        store,
        command,
        "execution_result",
        payload,
        ok=ok,
        error=error,
        cmdline_arg=called_as,
        domain_level="root",
    )
    emit_final_stderr(store, command, ok, "execute boundary reported", records=1)
    return 0 if ok else 1
