"""doctor command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.domain.diagnostics import run_diagnostics
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "doctor"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "running lower-level diagnostics")
    from xctx.commands.registry import command_handlers

    diagnostics = run_diagnostics(store, set(command_handlers().keys()))
    for diagnostic in diagnostics:
        emit_record(store, command, "result", diagnostic, ok=diagnostic["status"] != "fail", cmdline_arg=called_as)
    failed = [item for item in diagnostics if item["status"] == "fail"]
    emit_final_stderr(store, command, not failed, "doctor complete", diagnostics=len(diagnostics), failures=len(failed))
    return 0 if not failed else 2
