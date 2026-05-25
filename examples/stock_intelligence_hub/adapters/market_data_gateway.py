#!/usr/bin/env python3
"""Read-only market data gateway entrypoint used by xctx.

This reference adapter exposes canonical instrument identity and bundled OHLCV
market-series lookup. It emits one JSON object; xctx wraps it in the protocol
envelope.
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
from xctx_live.instruments import (  # noqa: E402
    instrument_audit,
    instrument_observation,
    instrument_registry_discovery,
    instrument_search_payload,
    latest_price_discovery,
    list_instruments,
    market_series_search_payload,
)


## Domain-pack boundary: this adapter owns market-data semantics.
## xctx only routes to this entrypoint and envelopes its JSON result.


def parse_discover_args(args: list[str]) -> tuple[str, str]:
    shape = "compact"
    query_parts: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--shape":
            if index + 1 >= len(args):
                raise ValueError("--shape requires a value")
            shape = args[index + 1]
            if shape not in {"compact", "full"}:
                raise ValueError("--shape must be compact or full")
            index += 2
            continue
        if token.startswith("--"):
            raise ValueError("supported discover argument shape: [--shape compact|full]")
        query_parts.append(token)
        index += 1
    return joined_query(query_parts), shape


def parse_observe_args(args: list[str]) -> tuple[str, dict[str, object] | None]:
    identifier_parts: list[str] = []
    range_request: dict[str, object] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token in {"--bars", "--calendar-days"}:
            if index + 1 >= len(args):
                raise ValueError(f"{token} requires a value")
            try:
                value = int(args[index + 1])
            except ValueError as exc:
                raise ValueError(f"{token} requires an integer") from exc
            if value < 0:
                raise ValueError(f"{token} cannot be negative")
            key = "bars" if token == "--bars" else "calendar_days"
            range_request[key] = value
            index += 2
            continue
        if token == "--export":
            if index + 1 >= len(args):
                raise ValueError("--export requires a value")
            export_format = args[index + 1]
            if export_format != "csv":
                raise ValueError("--export must be csv")
            range_request["export"] = export_format
            index += 2
            continue
        identifier_parts.append(token)
        index += 1
    if "bars" in range_request and "calendar_days" in range_request:
        raise ValueError("choose either --bars or --calendar-days")
    return joined_query(identifier_parts), range_request or None


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    compact, args = take_flag(raw, "--compact")
    command = args[0] if args else "discover"
    rest = args[1:]

    if command == "discover":
        try:
            query, shape = parse_discover_args(rest)
        except ValueError as exc:
            return usage_error(str(exc))
        payload = instrument_search_payload(ROOT, query) if query else instrument_registry_discovery(ROOT, shape=shape)
    elif command in {"search", "search_entity_instrument", "search-instruments", "search-instrument", "search_entity"}:
        query = joined_query(rest)
        if not query:
            return usage_error("search requires a company, ticker, CIK, issuer id, instrument id, or alias")
        payload = instrument_search_payload(ROOT, query)
    elif command in {"search-market-series", "search_market_series", "search-series", "search_series"}:
        query = joined_query(rest)
        if not query:
            return usage_error("search-market-series requires a ticker, issuer, provider, or text query")
        payload = market_series_search_payload(ROOT, query)
    elif command in {"latest-price", "latest_price", "latest", "quote", "latest_quote"}:
        query = joined_query(rest)
        if not query:
            return usage_error("latest-price requires a ticker, instrument id, CIK, issuer id, or market_series id")
        payload = latest_price_discovery(ROOT, query)
    elif command in {"list", "list_instruments", "list-instruments"}:
        try:
            payload = list_instruments(ROOT, rest)
        except ValueError as exc:
            return usage_error(str(exc))
    elif command == "observe":
        try:
            identifier, range_request = parse_observe_args(rest)
        except ValueError as exc:
            return usage_error(str(exc))
        if not identifier:
            return usage_error("observe requires an instrument id, ticker, CIK, issuer id, or market_series id")
        try:
            payload = instrument_observation(ROOT, identifier, range_request)
        except ValueError as exc:
            return usage_error(str(exc))
    elif command == "audit":
        payload = instrument_audit(ROOT)
    else:
        return usage_error(f"unknown market_data_gateway command: {command}")

    emit_json(payload, compact=compact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
