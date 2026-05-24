"""Top-level process runtime for xctx."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Sequence

import yaml

from xctx.commands.registry import command_handlers
from xctx.config.loader import load_store
from xctx.domain.interface_payloads import build_version_payload
from xctx.errors import XctxError
from xctx.process.argv import extract_global_options
from xctx.process.parser import build_parser
from xctx.process.signals import configure_sigpipe
from xctx.protocol.accessors import canonical_command, configured_command_names, help_aliases
from xctx.protocol.command_policy import visible_command_names_for_guidance
from xctx.protocol.emitter import emit_final_stderr, emit_minimal_error, emit_record, emit_stderr_event


## Protocol boundary: this module owns process-level xctx mechanics only.
## It may recognize configured reference shapes, but not domain-pack meaning.


def _stdout_is_tty() -> bool:
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _minimal_output_format(argv: Sequence[str]) -> str:
    has_json = "--json" in argv
    has_yaml = "--yaml" in argv
    if has_json and not has_yaml:
        return "jsonl"
    if has_yaml and not has_json:
        return "yaml"
    return "yaml" if _stdout_is_tty() else "jsonl"


def select_output_format(store: dict, explicit_format: str | None) -> str:
    stdout_config = store.get("protocol", {}).get("stdout", {})
    supported = set(stdout_config.get("supported_formats", ["jsonl", "yaml"]))
    default_format = stdout_config.get("default_format", stdout_config.get("format", "jsonl"))
    tty_default_format = stdout_config.get("tty_default_format", "yaml")
    selected = explicit_format or (tty_default_format if _stdout_is_tty() else default_format)
    if selected not in supported:
        supported_display = "|".join(sorted(supported))
        raise XctxError(f"next valid move: choose supported stdout format {supported_display}")
    return selected


def _with_discover_shortcut(store: dict, argv: list[str]) -> list[str]:
    """Allow the protocol-safe shorthand: ./xctx <agent_domain>::<affordance> ...

    This helper does not add a new command; it only inserts the discover command when
    the first token is already a scoped xctx reference. Unknown natural-language
    phrases are refused instead of guessed.
    """
    ## Boundary guard: this is structural shorthand only. Do not inspect or infer
    ## business vocabulary here; scoped packs own that through config/adapters.
    if not argv or argv[0] in configured_command_names(store) or argv[0] in help_aliases(store):
        return argv
    token = argv[0]
    if "::" not in token:
        return argv
    domain_id = token.split("::", 1)[0]
    if domain_id and domain_id in store.get("agent_domains", {}):
        return ["discover", *argv]
    return argv


def run(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """Run an xctx command in-process. Useful for tests and the CLI launcher."""
    configure_sigpipe()
    raw_argv = list(argv or [])
    selection = extract_global_options(raw_argv)
    store = load_store(
        root=root,
        override_system=selection.system_id,
        override_agent_domain=selection.agent_domain_id,
    )
    store["output_format"] = select_output_format(store, selection.output_format)
    store["detail"] = selection.detail
    if selection.output_error:
        raise XctxError(selection.output_error)

    handlers = command_handlers()
    selection = selection.__class__(
        argv=_with_discover_shortcut(store, selection.argv),
        system_id=selection.system_id,
        agent_domain_id=selection.agent_domain_id,
        output_format=selection.output_format,
        output_error=selection.output_error,
        detail=selection.detail,
        cmdline_arg=selection.cmdline_arg,
    )
    if not selection.argv:
        return handlers["discover"](
            store,
            type(
                "Args",
                (),
                {
                    "command": "xctx",
                    "target": None,
                    "target_args": [],
                    "id": None,
                    "name": None,
                    "discover_universe": True,
                    "cmdline_arg": selection.cmdline_arg or "xctx",
                },
            )(),
        )
    if selection.argv[0] in help_aliases(store):
        return command_handlers()["help"](store, type("Args", (), {"cmdline_arg": selection.cmdline_arg or "help"})())
    if selection.argv[0] in {"--version", "-V", "version"}:
        command = selection.argv[0]
        emit_record(
            store,
            command,
            "version",
            build_version_payload(store),
            cmdline_arg=selection.cmdline_arg or command,
            domain_level="universe",
        )
        return 0

    configured = configured_command_names(store)
    if selection.argv[0] not in configured:
        allowed = ", ".join(sorted(visible_command_names_for_guidance(store)))
        raise XctxError(f"next valid move: choose a known xctx command ({allowed})")

    parser = build_parser(store)
    args, unknown_args = parser.parse_known_args(selection.argv)
    args.cmdline_arg = selection.cmdline_arg or shlex.join(selection.argv)
    canonical = canonical_command(store, args.command)
    if unknown_args:
        if canonical == "discovery" and hasattr(args, "target_args"):
            args.target_args.extend(unknown_args)
        else:
            raise XctxError(f"next valid move: adjust arguments (unrecognized arguments: {' '.join(unknown_args)})")
    handler = handlers.get(canonical)
    if handler is None:
        raise XctxError(f"next valid move: command {canonical} is configured but has no production handler")
    return handler(store, args)


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return run(raw_argv, root=root)
    except (XctxError, json.JSONDecodeError, yaml.YAMLError) as exc:
        command = " ".join(raw_argv) if raw_argv else "help"
        try:
            selection = extract_global_options(raw_argv)
            fallback_store = load_store(
                root=root,
                override_system=selection.system_id,
                override_agent_domain=selection.agent_domain_id,
            )
            fallback_store["output_format"] = select_output_format(fallback_store, selection.output_format)
            fallback_store["detail"] = selection.detail
            emit_stderr_event(fallback_store, command, "error", str(exc))
            emit_record(fallback_store, command, "error", {}, ok=False, error=str(exc), cmdline_arg=command)
            emit_final_stderr(fallback_store, command, False, "guidance emitted", error=str(exc))
        except Exception:
            emit_minimal_error(command, str(exc), output_format=_minimal_output_format(raw_argv))
        return 1
