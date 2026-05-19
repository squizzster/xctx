"""observe command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.domain.agent_domains import has_agent_domains, observe_payload
from xctx.domain.discovery import find_discovery_action, observe_action_result
from xctx.domain.observations import apply_observe_expansions
from xctx.errors import XctxError
from xctx.protocol.accessors import guidance_cmd
from xctx.protocol.options import collect_cli_option_values
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event
from xctx.store.resolver import clean_subsystem, find_collection_record, find_collection_record_in_subsystem, subsystem_by_id


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "observe"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "loading observation target", target_id=args.id)

    target = getattr(args, "target", None)
    if has_agent_domains(store):
        level, payload = observe_payload(
            store,
            target,
            list(getattr(args, "target_args", [])),
            getattr(args, "id", None),
            collect_cli_option_values(store, command, args),
        )
        ok = payload.get("status") not in {"offline", "down_for_maintenance"}
        emit_record(
            store,
            command,
            "observation",
            payload,
            ok=ok,
            error=None if ok else payload.get("status"),
            cmdline_arg=called_as,
            domain_level=level,
        )
        emit_final_stderr(store, command, ok, "agent-domain observation complete", records=1)
        return 0 if ok else 1

    if target:
        action_match = find_discovery_action(store, target)
        if action_match:
            subsystem, action = action_match
            emit_record(
                store,
                command,
                "result",
                observe_action_result(store, subsystem, target, action, args.id),
                cmdline_arg=called_as,
            )
            emit_final_stderr(store, command, True, "observation complete", records=1)
            return 0

        subsystem = subsystem_by_id(store, target)
        if subsystem:
            found_in_subsystem = find_collection_record_in_subsystem(store, subsystem["id"], args.id)
            if found_in_subsystem:
                collection, record = found_in_subsystem
                emit_record(
                    store,
                    command,
                    "result",
                    apply_observe_expansions(store, collection, record),
                    cmdline_arg=called_as,
                )
                emit_final_stderr(store, command, True, "observation complete", records=1)
                return 0

    subsystem = subsystem_by_id(store, args.id)
    if subsystem:
        payload = clean_subsystem(subsystem)
        payload["counts"] = {
            collection["name"]: len(collection["records"])
            for collection in store["collections"].values()
            if collection["subsystem_id"] == subsystem["id"]
        }
        emit_record(store, command, "result", payload, cmdline_arg=called_as)
        emit_final_stderr(store, command, True, "observation complete", records=1)
        return 0

    found = find_collection_record(store, args.id)
    if not found:
        run_cmd = guidance_cmd(store, "discover_root_run_cmd")
        raise XctxError(f"next valid move: {run_cmd}" if run_cmd else "next valid move: discover")
    collection, record = found
    emit_record(store, command, "result", apply_observe_expansions(store, collection, record), cmdline_arg=called_as)
    emit_final_stderr(store, command, True, "observation complete", records=1)
    return 0
