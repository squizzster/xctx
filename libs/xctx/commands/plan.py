"""plan command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.domain.agent_domains import plan_payload
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "plan"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "building read-only plan", args=args.plan_args)
    payload = plan_payload(list(args.plan_args), store)
    emit_record(store, command, "plan", payload, cmdline_arg=called_as, domain_level="root")
    emit_final_stderr(store, command, True, "plan complete", records=1)
    return 0
