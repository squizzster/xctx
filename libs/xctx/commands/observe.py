"""observe command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import command_payload_error, command_payload_failed, cmdline_arg
from xctx.domain.actions import subdomain_action_config
from xctx.domain.core import has_agent_domains, resolve_subdomain
from xctx.domain.observation import observe_payload
from xctx.domain.routing import parse_ref
from xctx.errors import XctxError
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event
from xctx.protocol.option_specs import parse_target_cli_options
from xctx.store.runtime_artifacts import is_runtime_ref


def _split_observe_args(raw_args: list[str]) -> tuple[str | None, list[str], str | None]:
    item_id: str | None = None
    remaining: list[str] = []
    index = 0
    while index < len(raw_args):
        token = str(raw_args[index])
        if token == "--id":
            if index + 1 >= len(raw_args):
                raise XctxError("invalid observe arguments: --id requires a value")
            if item_id is not None:
                raise XctxError("conflicting observation identifiers: duplicate --id")
            item_id = str(raw_args[index + 1])
            index += 2
            continue
        if token.startswith("--id="):
            if item_id is not None:
                raise XctxError("conflicting observation identifiers: duplicate --id")
            item_id = token.split("=", 1)[1]
            if not item_id:
                raise XctxError("invalid observe arguments: --id requires a value")
            index += 1
            continue
        remaining.append(token)
        index += 1

    if remaining and remaining[0].startswith("-"):
        raise XctxError(
            "invalid observe arguments: configured observe options require a scoped target",
            next_moves=["./xctx observe <agent_domain>::<agent_subdomain> <id> [OPTIONS...]"],
        )
    target = remaining[0] if remaining else None
    target_args = remaining[1:] if len(remaining) > 1 else []
    return target, target_args, item_id


def _scoped_observe_parts(
    store: dict,
    target: str | None,
    target_args: list[str],
) -> tuple[list[str], dict[str, object]]:
    if target and is_runtime_ref("result", target):
        if target_args:
            raise XctxError("result observation does not accept extra arguments")
        return target_args, {}

    domain_id, subdomain_id = parse_ref(store, target)
    if domain_id and subdomain_id:
        subdomain = resolve_subdomain(store, domain_id, subdomain_id)
        action_name, action = subdomain_action_config(subdomain, "observe")
        positional, values = parse_target_cli_options(
            store,
            subdomain,
            "observe",
            target_args,
            action_name=action_name,
            action=action,
        )
        return positional, values

    if any(str(arg).startswith("-") for arg in target_args):
        if domain_id:
            raise XctxError(
                f"configured observe options require a scoped observe target: {domain_id}",
                next_moves=[f"./xctx observe {domain_id}::<agent_subdomain> --id <id>"],
            )
        unknown = next(str(arg) for arg in target_args if str(arg).startswith("-"))
        raise XctxError(f"unrecognized arguments: {unknown}")
    return target_args, {}


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "observe"
    called_as = cmdline_arg(args, command)
    raw_args = list(getattr(args, "observe_args", []))
    if not raw_args and hasattr(args, "target"):
        raw_args = [
            *([getattr(args, "target")] if getattr(args, "target", None) else []),
            *list(getattr(args, "target_args", [])),
        ]
        if getattr(args, "id", None):
            raw_args.extend(["--id", getattr(args, "id")])

    target, target_args, item_id = _split_observe_args(raw_args)
    emit_stderr_event(store, command, "start", "loading observation target", target_id=item_id)

    positional_ids, option_values = _scoped_observe_parts(store, target, target_args)
    if item_id and positional_ids:
        raise XctxError("conflicting observation identifiers: positional ID and --id")
    if item_id and not target:
        raise XctxError(
            "invalid observe arguments: --id requires a scoped target",
            next_moves=["./xctx observe <agent_domain>::<agent_subdomain> --id <id>"],
        )
    if item_id and target and not all(parse_ref(store, target)):
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
        item_id,
        option_values,
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
