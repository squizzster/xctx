"""Argument-vector normalization before command parsing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArgvSelection:
    argv: list[str]
    system_id: str | None
    agent_domain_id: str | None
    output_format: str | None
    output_error: str | None
    detail: bool
    cmdline_arg: str


def extract_global_options(argv: list[str]) -> ArgvSelection:
    """Extract process-global flags such as --system and output format."""
    normalized: list[str] = []
    system_id: str | None = None
    agent_domain_id: str | None = None
    output_format: str | None = None
    output_error: str | None = None
    detail = False
    index = 0
    while index < len(argv):
        token = argv[index]
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
        if token in {"--system", "--agent-domain", "--domain"}:
            if index + 1 >= len(argv):
                normalized.append(token)
                index += 1
                continue
            if token == "--system":
                system_id = argv[index + 1]
                agent_domain_id = argv[index + 1]
            else:
                agent_domain_id = argv[index + 1]
            index += 2
            continue
        if token.startswith("--system="):
            system_id = token.split("=", 1)[1]
            agent_domain_id = system_id
            index += 1
            continue
        if token.startswith("--agent-domain=") or token.startswith("--domain="):
            agent_domain_id = token.split("=", 1)[1]
            index += 1
            continue
        normalized.append(token)
        index += 1
    return ArgvSelection(
        argv=normalized,
        system_id=system_id,
        agent_domain_id=agent_domain_id,
        output_format=output_format,
        output_error=output_error,
        detail=detail,
        cmdline_arg=" ".join(argv),
    )
