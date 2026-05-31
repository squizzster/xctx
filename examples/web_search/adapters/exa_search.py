#!/usr/bin/env python3
"""Runtime Exa search entrypoint used by xctx.

This adapter owns Exa provider semantics. It emits one JSON object; xctx only
routes to this scoped entrypoint and wraps the protocol envelope.
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
from xctx_live.web_search_exa import (  # noqa: E402
    commit_fetch_page,
    commit_search_deep,
    commit_search_fast,
    discover_exa_search,
    exa_search_audit,
    list_results,
    list_search_runs,
    observe_exa_search,
    registry_stats,
    validate_fetch_page,
    validate_search_deep,
    validate_search_fast,
)


## Domain-pack boundary: this adapter owns Exa search semantics.
## The generic xctx runtime must not duplicate web-search provider logic.


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
            payload = discover_exa_search(ROOT, projection=_parse_discover_args(rest))
        elif command == "list-search-runs":
            payload = list_search_runs(ROOT, rest)
        elif command == "list-results":
            payload = list_results(ROOT, rest)
        elif command == "observe":
            identifier, option_args = _parse_observe_args(rest)
            payload = observe_exa_search(ROOT, identifier, option_args)
        elif command == "validate-search-fast":
            payload = validate_search_fast(ROOT, rest)
        elif command == "search-fast":
            payload = commit_search_fast(ROOT, rest)
        elif command == "validate-search-deep":
            payload = validate_search_deep(ROOT, rest)
        elif command == "search-deep":
            payload = commit_search_deep(ROOT, rest)
        elif command == "validate-fetch-page":
            payload = validate_fetch_page(ROOT, rest)
        elif command == "fetch-page":
            payload = commit_fetch_page(ROOT, rest)
        elif command == "stats":
            payload = {"object_type": "web_search_exa_stats", "stats": registry_stats(ROOT)}
        elif command == "audit":
            payload = exa_search_audit(ROOT)
        else:
            return usage_error(f"unknown exa_search command: {command}")
    except ValueError as exc:
        return usage_error(str(exc))

    emit_json(payload, compact=compact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
