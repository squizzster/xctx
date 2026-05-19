#!/usr/bin/env python3
"""Read-only equity filing taxonomy entrypoint used by xctx.

This script reads the bundled EDGAR form-reference SQLite database and emits one
JSON object. xctx wraps that object in the protocol envelope.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIBS = ROOT / "libs"
if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from xctx_live.common import emit_json, joined_query, take_flag, usage_error  # noqa: E402
from xctx_live.filings import (  # noqa: E402
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


def parse_limit(args: list[str], *, default: int = 50, maximum: int = 200) -> int:
    if not args:
        return default
    if len(args) == 2 and args[0] == "--limit":
        try:
            limit = int(args[1])
        except ValueError as exc:
            raise ValueError("--limit requires an integer") from exc
        if limit < 1:
            raise ValueError("--limit must be at least 1")
        return min(limit, maximum)
    raise ValueError("supported list argument shape: [--limit N]")


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    compact, args = take_flag(raw, "--compact")
    command = args[0] if args else "discover"
    rest = args[1:]

    if command == "discover":
        query = joined_query(rest)
        payload = discover_with_query(ROOT, query) if query else filing_taxonomy_discovery(ROOT)
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
            payload = list_forms(ROOT, parse_limit(rest))
        except ValueError as exc:
            return usage_error(str(exc))
    elif command == "list-families":
        try:
            payload = list_families(ROOT, parse_limit(rest))
        except ValueError as exc:
            return usage_error(str(exc))
    elif command == "list-priority-buckets":
        try:
            payload = list_priority_buckets(ROOT, parse_limit(rest))
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
