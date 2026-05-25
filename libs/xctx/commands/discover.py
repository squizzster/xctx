"""discover command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import command_payload_error, cmdline_arg, live_payload_failed
from xctx.domain.core import has_agent_domains
from xctx.domain.discovery import discover_payload, universe_discovery_payload
from xctx.errors import XctxError
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = getattr(args, "command", "discover")
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "resolving discovery target")
    if not has_agent_domains(store):
        raise XctxError("no agent_domains are configured")
    if getattr(args, "discover_universe", False):
        emit_record(
            store,
            command,
            "discovery",
            universe_discovery_payload(store),
            cmdline_arg=called_as,
            domain_level="universe",
        )
        emit_final_stderr(store, command, True, "universe discovery complete", records=1)
        return 0

    target_args = list(getattr(args, "target_args", []))
    if "--id" in target_args:
        raise XctxError(
            "invalid discover arguments: --id must appear before TARGET",
            next_moves=["./xctx discover TARGET", "./xctx discover --id ID"],
        )
    if getattr(args, "id", None) and getattr(args, "target", None):
        raise XctxError(
            "conflicting discovery targets: TARGET and --id",
            next_moves=["./xctx discover TARGET", "./xctx discover --id ID"],
        )
    if getattr(args, "id", None):
        args.target = args.id
    level, payload = discover_payload(store, getattr(args, "target", None), target_args)
    failed = live_payload_failed(payload.get("live_data") if isinstance(payload, dict) else None)
    emit_record(
        store,
        command,
        "discovery",
        payload,
        ok=not failed,
        error=command_payload_error(payload) if failed else None,
        cmdline_arg=called_as,
        domain_level=level,
    )
    emit_final_stderr(store, command, not failed, "agent-domain discovery complete", records=1)
    return 1 if failed else 0
