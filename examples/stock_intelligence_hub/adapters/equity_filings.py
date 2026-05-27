#!/usr/bin/env python3
"""Read-only equity filing taxonomy entrypoint used by xctx.

This script reads the bundled EDGAR form-reference SQLite database and emits one
JSON object. xctx wraps that object in the protocol envelope.
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
from xctx_live.filings import (  # noqa: E402
    LIST_DEFAULT_LIMIT,
    LIST_MAX_LIMIT,
    discover_with_query,
    filing_audit,
    filing_taxonomy_discovery,
    list_families,
    list_forms,
    list_priority_buckets,
    observe_any,
    search_families,
    search_forms,
    search_priority_buckets,
    stats,
)


## Domain-pack boundary: this adapter owns filing-taxonomy semantics.
## The generic xctx runtime may route here, but must not duplicate this logic.


def parse_discover_args(args: list[str]) -> tuple[str, str]:
    projection = "compact"
    query_parts: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--projection":
            if index + 1 >= len(args):
                raise ValueError("--projection requires a value")
            projection = args[index + 1]
            if projection not in {"compact", "full"}:
                raise ValueError("--projection must be compact or full")
            index += 2
            continue
        if token.startswith("--"):
            raise ValueError("supported discover argument projection: [--projection compact|full]")
        query_parts.append(token)
        index += 1
    return joined_query(query_parts), projection


def parse_list_args(args: list[str], *, cursor_supported: bool = False) -> dict[str, int | str]:
    options: dict[str, int | str] = {
        "limit": LIST_DEFAULT_LIMIT,
        "cursor": 0,
        "projection": "compact",
    }
    index = 0
    while index < len(args):
        token = args[index]
        if token not in {"--limit", "--cursor", "--projection"}:
            raise ValueError("supported list argument projection: [--limit N] [--cursor CURSOR] [--projection compact|full]")
        if index + 1 >= len(args):
            raise ValueError(f"{token} requires a value")
        value = args[index + 1]
        if token == "--limit":
            try:
                limit = int(value)
            except ValueError as exc:
                raise ValueError("--limit requires an integer") from exc
            if limit < 1:
                raise ValueError("--limit must be at least 1")
            options["limit"] = min(limit, LIST_MAX_LIMIT)
        elif token == "--cursor":
            if not cursor_supported:
                raise ValueError("--cursor is not supported for this list")
            try:
                cursor = int(value)
            except ValueError as exc:
                raise ValueError("--cursor requires an integer cursor in this adapter") from exc
            if cursor < 0:
                raise ValueError("--cursor cannot be negative")
            options["cursor"] = cursor
        elif token == "--projection":
            if value not in {"compact", "full"}:
                raise ValueError("--projection must be compact or full")
            options["projection"] = value
        index += 2
    return options


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    compact, args = take_flag(raw, "--compact")
    command = args[0] if args else "discover"
    rest = args[1:]

    if command == "discover":
        try:
            query, projection = parse_discover_args(rest)
        except ValueError as exc:
            return usage_error(str(exc))
        payload = discover_with_query(ROOT, query) if query else filing_taxonomy_discovery(ROOT, projection=projection)
    elif command == "search-forms":
        query = joined_query(rest)
        matches = search_forms(ROOT, query)
        payload = {"object_type": "equity_filing::search_filing_form::result", "query": query, "matches_returned": len(matches), "matches": matches}
    elif command == "search-families":
        query = joined_query(rest)
        matches = search_families(ROOT, query)
        payload = {"object_type": "equity_filing::search_filing_family::result", "query": query, "matches_returned": len(matches), "matches": matches}
    elif command == "search-priority-buckets":
        query = joined_query(rest)
        matches = search_priority_buckets(ROOT, query)
        payload = {"object_type": "equity_filing::search_priority_bucket::result", "query": query, "matches_returned": len(matches), "matches": matches}
    elif command == "list-forms":
        try:
            list_options = parse_list_args(rest, cursor_supported=True)
            payload = list_forms(
                ROOT,
                limit=int(list_options["limit"]),
                cursor=int(list_options["cursor"]),
                projection=str(list_options["projection"]),
            )
        except ValueError as exc:
            return usage_error(str(exc))
    elif command == "list-families":
        try:
            list_options = parse_list_args(rest, cursor_supported=True)
            payload = list_families(
                ROOT,
                limit=int(list_options["limit"]),
                cursor=int(list_options["cursor"]),
                projection=str(list_options["projection"]),
            )
        except ValueError as exc:
            return usage_error(str(exc))
    elif command == "list-priority-buckets":
        try:
            list_options = parse_list_args(rest)
            payload = list_priority_buckets(ROOT, limit=int(list_options["limit"]), projection=str(list_options["projection"]))
        except ValueError as exc:
            return usage_error(str(exc))
    elif command == "observe":
        identifier = joined_query(rest)
        if not identifier:
            return usage_error("observe requires form:<code>, family:<code>, priority:<code>, or instrument:<id>")
        payload = observe_any(ROOT, identifier)
    elif command == "stats":
        payload = {"object_type": "equity_filing_stats", "stats": stats(ROOT)}
    elif command == "audit":
        payload = filing_audit(ROOT)
    else:
        return usage_error(f"unknown equity_filings command: {command}")

    emit_json(payload, compact=compact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
