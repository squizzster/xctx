"""Argument-vector normalization before command parsing."""

from __future__ import annotations

from dataclasses import dataclass
import shlex


@dataclass(frozen=True)
class ArgvSelection:
    argv: list[str]
    output_format: str | None
    output_error: str | None
    detail: bool
    cmdline_arg: str


def extract_global_options(argv: list[str]) -> ArgvSelection:
    """Extract process-global output flags before command parsing.

    Global flags belong to the process invocation prefix. Once the command token
    starts, remaining tokens are command/action data and must not be consumed as
    xctx process options.
    """
    normalized: list[str] = []
    output_format: str | None = None
    output_error: str | None = None
    detail = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            normalized.extend(argv[index + 1 :])
            break
        if token == "--detail":
            detail = True
            index += 1
            continue
        if token in {"--json", "--yaml"}:
            requested_format = "jsonl" if token == "--json" else "yaml"
            if output_error:
                output_format = None
            elif output_format and output_format != requested_format:
                output_error = "next valid move: choose either --json or --yaml"
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
        detail=detail,
        cmdline_arg=shlex.join(argv),
    )
