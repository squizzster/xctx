"""observe command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import command_payload_error, command_payload_failed, cmdline_arg
from xctx.domain.core import has_agent_domains
from xctx.domain.observation import observe_payload
from xctx.domain.routing import parse_ref
from xctx.errors import XctxError
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event
from xctx.protocol.option_specs import collect_cli_option_values


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "observe"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "loading observation target", target_id=args.id)

    target = getattr(args, "target", None)
    positional_ids = list(getattr(args, "target_args", []))
    if getattr(args, "id", None) and positional_ids:
        raise XctxError("conflicting observation identifiers: positional ID and --id")
    if getattr(args, "id", None) and target and not all(parse_ref(store, target)):
        raise XctxError(
            "invalid observe arguments: --id requires a scoped target",
            next_moves=["./xctx observe <agent_domain>::<agent_subdomain> --id <id>"],
        )
    if not has_agent_domains(store):
        raise XctxError("no agent_domains are configured")
    level, payload = observe_payload(
        store,
        target,
        positional_ids,
        getattr(args, "id", None),
        collect_cli_option_values(store, command, args),
    )
    ok = not command_payload_failed(payload)
    emit_record(
        store,
        command,
        "observation",
        payload,
        ok=ok,
        error=None if ok else command_payload_error(payload),
        cmdline_arg=called_as,
        domain_level=level,
    )
    emit_final_stderr(store, command, ok, "agent-domain observation complete", records=1)
    return 0 if ok else 1
