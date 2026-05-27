"""other extension-lane command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.protocol.detail import at_least_more, is_max
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event
from xctx.protocol.guidance import command_hints


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "other"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "using extension lane", topic=args.topic)
    payload = {
        "topic": args.topic,
        "status": "extension_lane_selected",
        "next_moves": command_hints(["./xctx discover", "./xctx audit root"]),
    }
    if at_least_more(store):
        payload["reason"] = args.reason
        payload["note"] = "Extension path selected for task dynamics outside the main agent-domain command set."
    if is_max(store):
        payload["extension_lane"] = "hidden_from_default_root_surface"
    emit_record(store, command, "extension", payload, cmdline_arg=called_as, domain_level="root")
    emit_final_stderr(store, command, True, "extension lane complete", records=1)
    return 0
