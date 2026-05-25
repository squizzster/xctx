"""Pytest-collected discover/observe data-boundary checks."""

from __future__ import annotations

from framework_helpers import load_script_module


boundary = load_script_module("protocol_observe_discover_boundary")


def test_generic_xctx_core_is_decoupled() -> None:
    boundary.assert_generic_xctx_core_is_decoupled()


def test_market_discovery_payloads_do_not_return_observation_data() -> None:
    for args in (
        ["discover", "stock_intelligence_hub::market_data_gateway", "search_entity_instrument", "GOOG"],
        ["discover", "stock_intelligence_hub::market_data_gateway", "search_market_series", "AAPL"],
        ["discover", "stock_intelligence_hub::latest_price", "AAPL"],
        ["discover", "stock_intelligence_hub::market_data_gateway"],
    ):
        boundary.assert_market_discovery_payload(boundary.run_xctx(args))


def test_filing_discovery_payload_has_observe_next_move_but_no_observation_object() -> None:
    form_search = boundary.run_xctx(["discover", "stock_intelligence_hub::equity_filing", "search_forms", "10-K"])
    assert form_search["record_type"] == "discovery"
    boundary.assert_no_observation_object_type(boundary.live_data(form_search))
    boundary.assert_has_observe_next_move(boundary.live_data(form_search))


def test_observe_payloads_are_observations() -> None:
    observed = boundary.live_data(boundary.run_xctx(["observe", "stock_intelligence_hub::market_data_gateway", "AAPL"]))
    assert observed["object_type"] == "market_data_gateway_instrument_observation"
    assert observed["latest_available_price"]["is_live_quote"] is False

    observed_bars = boundary.live_data(
        boundary.run_xctx(["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--bars", "3"])
    )
    assert observed_bars["object_type"] == "market_data_gateway_market_series_range_observation"
    assert len(observed_bars["bars"]) == 3

    observed_form = boundary.live_data(boundary.run_xctx(["observe", "stock_intelligence_hub::equity_filing", "form:10-K"]))
    assert observed_form["object_type"] == "filing_form_observation"
    assert observed_form["description"]
    assert observed_form["when_to_use"]
