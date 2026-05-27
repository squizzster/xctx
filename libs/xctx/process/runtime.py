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
from xctx.process.redaction import redact_argv
from xctx.process.signals import configure_sigpipe
from xctx.protocol.accessors import canonical_command, configured_command_names
from xctx.protocol.detail import select_detail_level
from xctx.protocol.emitter import emit_final_stderr, emit_minimal_error, emit_record, emit_stderr_event
from xctx.protocol.guidance import root_protocol_next_moves


## Protocol boundary: this module owns process-level xctx mechanics only.
## It may recognize configured reference patterns, but not domain-pack meaning.


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
        raise XctxError(f"unsupported stdout format: {selected} (supported: {supported_display})")
    return selected


def _select_detail(store: dict, argv: list[str], explicit: str | None) -> str:
    return select_detail_level(store, argv, explicit)


def run(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """Run an xctx command in-process. Useful for tests and the CLI launcher."""

    raw_argv = list(argv or [])
    selection = extract_global_options(raw_argv)
    store = load_store(root=root)
    store["output_format"] = select_output_format(store, selection.output_format)
    normalized_argv = selection.argv
    store["detail_level"] = _select_detail(store, normalized_argv, selection.detail_level)
    if selection.output_error and not selection.detail_level:
        store["detail_level"] = "basic"
    if selection.output_error:
        raise XctxError(selection.output_error)

    handlers = command_handlers()
    selection = selection.__class__(
        argv=normalized_argv,
        output_format=selection.output_format,
        output_error=selection.output_error,
        detail_level=selection.detail_level,
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
    if selection.argv[0] in {"--version", "-V"}:
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
        raise XctxError("unknown xctx command", next_moves=root_protocol_next_moves(store))

    parser = build_parser(store)
    args, unknown_args = parser.parse_known_args(selection.argv)
    args.cmdline_arg = selection.cmdline_arg or shlex.join(selection.argv)
    canonical = canonical_command(store, args.command)
    if unknown_args:
        raise XctxError(f"unrecognized arguments: {' '.join(unknown_args)}")
    handler = handlers.get(canonical)
    if handler is None:
        raise XctxError(f"configured command has no handler: {canonical}")
    return handler(store, args)


def _emit_process_error(
    raw_argv: Sequence[str],
    message: str,
    *,
    root: Path | None = None,
    next_moves: list | None = None,
) -> None:
    command = redact_argv(list(raw_argv)) if raw_argv else "xctx"
    moves = list(next_moves or [])
    try:
        selection = extract_global_options(list(raw_argv))
        fallback_store = load_store(root=root)
        fallback_store["output_format"] = select_output_format(fallback_store, selection.output_format)
        normalized_argv = selection.argv
        fallback_store["detail_level"] = _select_detail(fallback_store, normalized_argv, selection.detail_level)
        if selection.output_error and not selection.detail_level:
            fallback_store["detail_level"] = "basic"
        emit_stderr_event(fallback_store, command, "error", message)
        emit_record(
            fallback_store,
            command,
            "error",
            {},
            ok=False,
            error=message,
            next_moves=moves,
            cmdline_arg=command,
        )
        emit_final_stderr(fallback_store, command, False, "error emitted", error=message, next_moves=moves)
    except Exception:
        emit_minimal_error(command, message, next_moves=moves, output_format=_minimal_output_format(raw_argv))


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    if argv is None:
        configure_sigpipe()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return run(raw_argv, root=root)
    except (XctxError, json.JSONDecodeError, yaml.YAMLError, OSError) as exc:
        next_moves = exc.next_moves if isinstance(exc, XctxError) else []
        _emit_process_error(raw_argv, str(exc), root=root, next_moves=next_moves)
        return 1
    except Exception as exc:
        _emit_process_error(raw_argv, f"unexpected_framework_error: {type(exc).__name__}: {exc}", root=root)
        return 1
