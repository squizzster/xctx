#!/usr/bin/env python3
"""Runtime EDGAR filing library entrypoint used by xctx.

This adapter owns SEC filing inventory semantics. It emits one JSON object;
xctx only routes to this scoped entrypoint and wraps the protocol envelope.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _workspace_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "yaml_dynamic_config").is_dir() and (parent / "data").is_dir():
            return parent
    for parent in Path(__file__).resolve().parents:
        if (parent / "libs").is_dir():
            return parent
    raise RuntimeError("could not locate xctx workspace root")


ROOT = _workspace_root()
LIBS = ROOT / "libs"
if LIBS.is_dir() and str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from xctx_live.common import emit_json, joined_query, take_flag, usage_error  # noqa: E402
from xctx_live.edgar_filing_library import (  # noqa: E402
    commit_company_pack,
    commit_download_key_filings,
    commit_index_local_artifacts,
    discover_library,
    filing_audit,
    list_artifacts,
    list_available_filings,
    list_key_filings,
    observe_filing,
    registry_stats,
    validate_company_pack,
    validate_download_key_filings,
    validate_index_local_artifacts,
)


## Domain-pack boundary: this adapter owns filing-library semantics.
## The generic xctx runtime must not duplicate SEC inventory or download logic.


def _parse_discover_args(args: list[str]) -> str:
    projection = "compact"
    index = 0
    while index < len(args):
        token = args[index]
        if token != "--projection":
            raise ValueError("supported discover argument projection: [--projection compact|full]")
        if index + 1 >= len(args):
            raise ValueError("--projection requires a value")
        projection = args[index + 1]
        if projection not in {"compact", "full"}:
            raise ValueError("--projection must be compact or full")
        index += 2
    return projection


def _parse_observe_args(args: list[str]) -> tuple[str, list[str]]:
    identifier_parts: list[str] = []
    option_args: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--preview-chars":
            if index + 1 >= len(args):
                raise ValueError("--preview-chars requires a value")
            option_args.extend([token, args[index + 1]])
            index += 2
            continue
        if token.startswith("--"):
            raise ValueError(f"unsupported observe option: {token}")
        identifier_parts.append(token)
        index += 1
    return joined_query(identifier_parts), option_args


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    compact, args = take_flag(raw, "--compact")
    command = args[0] if args else "discover"
    rest = args[1:]

    try:
        if command == "discover":
            projection = _parse_discover_args(rest)
            payload = discover_library(ROOT, projection=projection)
        elif command == "list-key-filings":
            payload = list_key_filings(ROOT, rest)
        elif command == "list-available-filings":
            payload = list_available_filings(ROOT, rest)
        elif command == "list-artifacts":
            payload = list_artifacts(ROOT, rest)
        elif command == "observe":
            identifier, option_args = _parse_observe_args(rest)
            payload = observe_filing(ROOT, identifier, option_args)
        elif command == "validate-company-pack":
            payload = validate_company_pack(ROOT, rest)
        elif command == "company-pack":
            payload = commit_company_pack(ROOT, rest)
        elif command == "validate-download-key-filings":
            payload = validate_download_key_filings(ROOT, rest)
        elif command == "download-key-filings":
            payload = commit_download_key_filings(ROOT, rest)
        elif command == "validate-index-local-artifacts":
            payload = validate_index_local_artifacts(ROOT, rest)
        elif command == "index-local-artifacts":
            payload = commit_index_local_artifacts(ROOT, rest)
        elif command == "stats":
            payload = {"object_type": "edgar_filing_library_stats", "stats": registry_stats(ROOT)}
        elif command == "audit":
            payload = filing_audit(ROOT)
        else:
            return usage_error(f"unknown edgar_filing_library command: {command}")
    except ValueError as exc:
        return usage_error(str(exc))

    emit_json(payload, compact=compact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
