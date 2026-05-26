"""help command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.domain.interface_payloads import build_help_payload
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "help"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "emitting machine interface")
    emit_record(
        store,
        command,
        "help",
        build_help_payload(store),
        cmdline_arg=called_as,
        domain_level="universe",
    )
    emit_final_stderr(store, command, True, "machine interface emitted", records=1)
    return 0
