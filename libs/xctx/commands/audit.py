"""audit command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.domain.audit import audit_check_failed, audit_domain_level, audit_payload
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "audit"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "auditing agent-domain surface", scope=args.scope)
    domain_level = audit_domain_level(store, args.scope)
    payload = audit_payload(store, args.scope)
    ok = not any(audit_check_failed(check) for check in payload.get("checks", []))
    emit_record(store, command, "audit", payload, ok=ok, cmdline_arg=called_as, domain_level=domain_level)
    emit_final_stderr(store, command, ok, "audit complete", records=1)
    return 0 if ok else 1
