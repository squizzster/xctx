"""repair command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.domain.repair import repair_domain_level, repair_payload
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "repair"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "resolving repair guidance", target=args.target)
    target = args.target or ""
    domain_level = repair_domain_level(store, target)
    ok, payload, error = repair_payload(store, target)
    emit_record(
        store,
        command,
        "repair_result",
        payload,
        ok=ok,
        error=error,
        cmdline_arg=called_as,
        domain_level=domain_level,
    )
    emit_final_stderr(store, command, ok, "repair guidance complete", records=1)
    return 0 if ok else 1
