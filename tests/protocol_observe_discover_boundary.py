#!/usr/bin/env python3
"""Regression checks for discover/observe data-boundary behavior."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / "libs"

if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from xctx.process.runtime import main as xctx_main  # noqa: E402


FORBIDDEN_MARKET_DISCOVERY_KEYS = {
    "latest_available_price",
    "latest_bar",
    "bars",
    "bars_inline",
    "bars_omitted_from_json",
    "price_summary",
    "csv",
    "open",
    "high",
    "low",
    "close",
    "vwap",
    "volume_raw",
    "transaction_count",
    "bar_start_ts",
    "first_close",
    "last_close",
    "close_change",
    "close_change_percent",
    "highest_high",
    "lowest_low",
}

GENERIC_XCTX_FILES = [
    "libs/xctx/process/parser.py",
    "libs/xctx/commands/discover.py",
    "libs/xctx/commands/observe.py",
    "libs/xctx/domain/agent_domains.py",
    "libs/xctx/protocol/command_policy.py",
]

FORBIDDEN_CORE_LITERALS = (
    "--bars",
    "--calendar-days",
    "search_entity_instrument",
    "search_market_series",
    "search_filing_form",
    "list_forms",
    "latest_price",
    "latest-price",
    "ticker",
    "symbol",
    "OHLCV",
    "EDGAR",
    "CIK",
)


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def run_xctx(args: Iterable[str], expected_code: int = 0) -> dict[str, Any]:
    out = io.StringIO()
    err = io.StringIO()
    old_cwd = Path.cwd()
    try:
        os.chdir(ROOT)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = xctx_main(list(args), root=ROOT)
    finally:
        os.chdir(old_cwd)
    assert code == expected_code, out.getvalue() + err.getvalue()
    assert err.getvalue() == "", err.getvalue()
    parsed = parse_jsonl(out.getvalue())
    assert len(parsed) == 1, parsed
    return parsed[0]


def walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def walk_keys(value: Any, prefix: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            yield path, str(key)
            yield from walk_keys(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_keys(child, f"{prefix}[{index}]")


def live_data(payload: dict[str, Any]) -> dict[str, Any]:
    live = payload["results"].get("live_data")
    assert isinstance(live, dict), payload
    return live


def assert_no_observation_object_type(value: Any) -> None:
    for item in walk(value):
        if isinstance(item, dict) and "object_type" in item:
            object_type = str(item["object_type"])
            assert "_observation" not in object_type, object_type


def assert_no_raw_market_data(value: Any) -> None:
    leaked = [(path, key) for path, key in walk_keys(value) if key in FORBIDDEN_MARKET_DISCOVERY_KEYS]
    assert leaked == [], leaked


def assert_has_observe_next_move(value: Any) -> None:
    commands = [item for item in walk(value) if isinstance(item, str) and item.startswith("./xctx observe ")]
    assert commands, value


def assert_market_discovery_payload(payload: dict[str, Any]) -> None:
    assert payload["record_type"] == "discovery"
    live = live_data(payload)
    assert_no_observation_object_type(live)
    assert_no_raw_market_data(live)
    assert_has_observe_next_move(live)


def assert_generic_xctx_core_is_decoupled() -> None:
    for rel in GENERIC_XCTX_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for literal in FORBIDDEN_CORE_LITERALS:
            assert literal not in text, (rel, literal)


def main() -> None:
    assert_generic_xctx_core_is_decoupled()

    assert_market_discovery_payload(
        run_xctx(["discover", "stock_intelligence_hub::market_data_gateway", "search_entity_instrument", "GOOG"])
    )
    assert_market_discovery_payload(
        run_xctx(["discover", "stock_intelligence_hub::market_data_gateway", "search_market_series", "AAPL"])
    )
    assert_market_discovery_payload(run_xctx(["discover", "stock_intelligence_hub::latest_price", "AAPL"]))
    assert_market_discovery_payload(run_xctx(["discover", "stock_intelligence_hub::market_data_gateway"]))

    form_search = run_xctx(["discover", "stock_intelligence_hub::equity_filing", "search_forms", "10-K"])
    assert form_search["record_type"] == "discovery"
    assert_no_observation_object_type(live_data(form_search))
    assert_has_observe_next_move(live_data(form_search))

    observed = live_data(run_xctx(["observe", "stock_intelligence_hub::market_data_gateway", "AAPL"]))
    assert observed["object_type"] == "market_data_gateway_instrument_observation"
    assert observed["latest_available_price"]["is_live_quote"] is False

    observed_bars = live_data(run_xctx(["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--bars", "3"]))
    assert observed_bars["object_type"] == "market_data_gateway_market_series_range_observation"
    assert len(observed_bars["bars"]) == 3

    observed_form = live_data(run_xctx(["observe", "stock_intelligence_hub::equity_filing", "form:10-K"]))
    assert observed_form["object_type"] == "filing_form_observation"
    assert observed_form["description"]
    assert observed_form["when_to_use"]


if __name__ == "__main__":
    main()
