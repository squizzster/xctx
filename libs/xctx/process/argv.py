"""Argument-vector normalization before command parsing."""

from __future__ import annotations

from dataclasses import dataclass

from xctx.process.redaction import redact_argv
from xctx.protocol.detail import DETAIL_FLAGS, DETAIL_LEVELS


@dataclass(frozen=True)
class ArgvSelection:
    argv: list[str]
    output_format: str | None
    output_error: str | None
    detail_level: str | None
    cmdline_arg: str


def _detail_conflict(existing: str | None, requested: str) -> str | None:
    if existing and existing != requested:
        return f"conflicting detail flags: --{existing} and --{requested}"
    return None


def extract_global_options(argv: list[str]) -> ArgvSelection:
    """Extract process-global output flags before command parsing.

    Global flags belong to the process invocation prefix. Once the command token
    starts, remaining tokens are command/action data and must not be consumed as
    xctx process options.
    """

    normalized: list[str] = []
    output_format: str | None = None
    output_error: str | None = None
    detail_level: str | None = None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            normalized.extend(argv[index + 1 :])
            break
        if token == "--detail":
            output_error = output_error or "unsupported global option --detail; use --basic, --more, or --max"
            index += 1
            continue
        if token == "--shape":
            output_error = output_error or "unsupported global option --shape; use --projection on scoped discovery actions or --basic/--more/--max for protocol detail"
            index += 2 if index + 1 < len(argv) and not str(argv[index + 1]).startswith("--") else 1
            continue
        if token == "--detail-level":
            if index + 1 >= len(argv):
                output_error = output_error or "missing value for --detail-level (allowed: basic|more|max)"
                index += 1
                continue
            requested = str(argv[index + 1]).strip().lower()
            if requested not in DETAIL_LEVELS:
                output_error = output_error or f"unsupported --detail-level value: {requested} (allowed: basic|more|max)"
            else:
                output_error = output_error or _detail_conflict(detail_level, requested)
                detail_level = detail_level or requested
            index += 2
            continue
        if token in DETAIL_FLAGS:
            requested = DETAIL_FLAGS[token]
            output_error = output_error or _detail_conflict(detail_level, requested)
            detail_level = detail_level or requested
            index += 1
            continue
        if token in {"--json", "--yaml"}:
            requested_format = "jsonl" if token == "--json" else "yaml"
            if output_error:
                output_format = None
            elif output_format and output_format != requested_format:
                output_error = "conflicting stdout format flags: --json and --yaml"
                output_format = None
            else:
                output_format = requested_format
            index += 1
            continue
        normalized.extend(argv[index:])
        break
    return ArgvSelection(
        argv=normalized,
        output_format=output_format,
        output_error=output_error,
        detail_level=detail_level,
        cmdline_arg=redact_argv(argv),
    )
