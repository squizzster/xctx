"""repair command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.domain.agent_domains import repair_payload
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "repair"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "resolving repair guidance", target=args.target)
    ok, payload, error = repair_payload(store, args.target or "")
    emit_record(
        store,
        command,
        "repair_result",
        payload,
        ok=ok,
        error=error,
        cmdline_arg=called_as,
        domain_level="agent_domain",
    )
    emit_final_stderr(store, command, ok, "repair guidance complete", records=1)
    return 0 if ok else 1
