"""help command."""

from __future__ import annotations

import argparse

from xctx.domain.status_payloads import build_help_payload
from xctx.protocol.emitter import emit_final_stderr, emit_raw_for_store, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "help"
    emit_stderr_event(store, command, "start", "emitting machine interface")
    emit_raw_for_store(store, build_help_payload(store))
    emit_final_stderr(store, command, True, "machine interface emitted", records=1)
    return 0
