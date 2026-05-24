"""discover command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import command_payload_error, cmdline_arg, live_payload_failed
from xctx.domain.agent_domains import discover_payload, has_agent_domains, universe_discovery_payload
from xctx.domain.discovery import (
    build_root_discovery_payload,
    build_subsystem_discovery_payload,
    discover_action_results,
    find_discovery_action,
)
from xctx.domain.identity import find_identity
from xctx.errors import XctxError
from xctx.domain.relationships import relationship_resources
from xctx.protocol.accessors import canonical_command, run_cmd_key
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = getattr(args, "command", "discover")
    called_as = cmdline_arg(args, command)
    canonical = canonical_command(store, command)
    emit_stderr_event(store, command, "start", "resolving discovery target")
    if has_agent_domains(store):
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
        if getattr(args, "id", None) and not getattr(args, "target", None):
            args.target = args.id
        if getattr(args, "name", None) and not getattr(args, "target", None):
            raise XctxError("next valid move: use a scoped discovery action, for example ./xctx discover <agent_domain>::<affordance> <name>")
        level, payload = discover_payload(store, getattr(args, "target", None), list(getattr(args, "target_args", [])))
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

    if getattr(args, "target", None) and not args.id and not args.name:
        action_match = find_discovery_action(store, args.target)
        if action_match:
            subsystem, action = action_match
            query_text = " ".join(getattr(args, "target_args", []))
            emit_record(
                store,
                command,
                "result",
                discover_action_results(store, subsystem, args.target, action, query_text),
                cmdline_arg=called_as,
            )
            emit_final_stderr(store, command, True, "discovery action complete", records=1)
            return 0
        args.id = args.target
    if not args.id and not args.name:
        emit_record(store, command, "result", build_root_discovery_payload(store), cmdline_arg=called_as)
        emit_final_stderr(store, command, True, "root discovery complete", records=1)
        return 0

    identity = find_identity(store, args.id, args.name)
    if identity["category"] == "system":
        emit_record(store, command, "result", build_root_discovery_payload(store), cmdline_arg=called_as)
        emit_final_stderr(store, command, True, "root discovery complete", records=1)
        return 0
    if identity["category"] == "available_system":
        emit_record(store, command, "result", identity, cmdline_arg=called_as)
        emit_record(
            store,
            command,
            "result",
            {
                "category": "available_system_next_move",
                "system_id": identity["id"],
                run_cmd_key(store): f"./xctx discover {identity['id']}::",
            },
            cmdline_arg=called_as,
        )
        emit_final_stderr(store, command, True, "available system discovery complete", records=2)
        return 0
    if identity["category"] == "subsystem":
        emit_record(store, command, "result", build_subsystem_discovery_payload(store, identity["id"]), cmdline_arg=called_as)
        emit_final_stderr(store, command, True, "subsystem discovery complete", records=1)
        return 0

    resources = relationship_resources(store, identity)
    emit_record(store, canonical, "identity", identity, cmdline_arg=called_as)
    for resource in resources:
        emit_record(store, canonical, "result", resource, cmdline_arg=called_as)
    emit_final_stderr(store, command, True, "discovery complete", records=len(resources) + 1)
    return 0
