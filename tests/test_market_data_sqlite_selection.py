from __future__ import annotations

import shutil

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


def test_market_data_sqlite_defaults_to_example_when_runtime_db_is_absent(monkeypatch, tmp_path) -> None:
    ensure_libs_path()
    from xctx_live.instruments import market_db_selection  # noqa: PLC0415

    monkeypatch.delenv("XCTX_MARKET_DATA_SQLITE", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy2(ROOT / "data" / "mini_stocks.example.sqlite", data_dir / "mini_stocks.example.sqlite")

    selected = market_db_selection(tmp_path)

    assert selected["source"] == "example_fixture"
    assert selected["display_path"] == "data/mini_stocks.example.sqlite"
    assert selected["exists"] is True


def test_market_data_sqlite_prefers_ignored_runtime_db_over_example(monkeypatch, tmp_path) -> None:
    ensure_libs_path()
    from xctx_live.instruments import market_db_selection  # noqa: PLC0415

    monkeypatch.delenv("XCTX_MARKET_DATA_SQLITE", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "mini_stocks.example.sqlite").write_bytes(b"example")
    (data_dir / "mini_stocks.sqlite").write_bytes(b"runtime")

    selected = market_db_selection(tmp_path)

    assert selected["source"] == "local_runtime"
    assert selected["display_path"] == "data/mini_stocks.sqlite"
    assert selected["exists"] is True


def test_market_data_sqlite_env_override_is_strict(monkeypatch, tmp_path) -> None:
    ensure_libs_path()
    from xctx_live.instruments import connect_market, market_db_selection  # noqa: PLC0415

    missing = tmp_path / "missing.sqlite"
    monkeypatch.setenv("XCTX_MARKET_DATA_SQLITE", str(missing))

    selected = market_db_selection(ROOT)

    assert selected["source"] == "env_override"
    assert selected["display_path"] == str(missing)
    assert selected["exists"] is False
    with pytest.raises(FileNotFoundError, match="market data sqlite not found from env_override"):
        connect_market(ROOT)


def test_market_data_sqlite_env_override_reads_example_stats(monkeypatch) -> None:
    ensure_libs_path()
    from xctx_live.instruments import market_stats  # noqa: PLC0415

    monkeypatch.setenv("XCTX_MARKET_DATA_SQLITE", str(ROOT / "data" / "mini_stocks.example.sqlite"))

    stats = market_stats(ROOT)

    assert stats["database_source"] == "env_override"
    assert stats["database_path"] == "data/mini_stocks.example.sqlite"
    assert stats["fixture_kind"] == "example"
    assert stats["ohlcv_series"] == 100


def test_market_data_sqlite_missing_env_override_fails_without_traceback(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "missing.sqlite"
    monkeypatch.setenv("XCTX_MARKET_DATA_SQLITE", str(missing))

    rc, payload = run_runtime_json(
        ["discover", "stock_intelligence_hub::market_data_gateway::search_market_series", "AAPL"]
    )

    assert rc == 1
    assert payload["ok"] is False
    assert "market data sqlite not found from env_override" in payload["error"]
    assert "Traceback" not in payload["error"]


def test_market_data_list_filters_accept_provider_codes_and_display_labels() -> None:
    rc, coded_payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::market_data_gateway::list_instruments",
            "--limit",
            "3",
            "--exchange",
            "XNAS",
            "--security-type",
            "CS",
        ]
    )

    assert rc == 0
    coded = coded_payload["results"]["live_data"]
    coded_tickers = [item["ticker"] for item in coded["instruments"]]
    assert coded["filters"] == {"exchange": "XNAS", "security_type": "CS"}
    assert coded["pagination"]["returned_count"] == 3
    assert coded["filtered_count"] >= 3
    assert all(item["exchange"] == "Nasdaq" for item in coded["instruments"])
    assert all(item["security_type"] == "common_stock" for item in coded["instruments"])

    rc, display_payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::market_data_gateway::list_instruments",
            "--limit",
            "3",
            "--exchange",
            "Nasdaq",
            "--security-type",
            "common_stock",
        ]
    )

    assert rc == 0
    display = display_payload["results"]["live_data"]
    assert [item["ticker"] for item in display["instruments"]] == coded_tickers

    rc, full_payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::market_data_gateway::list_instruments",
            "--limit",
            "1",
            "--exchange",
            "XNAS",
            "--security-type",
            "CS",
            "--projection",
            "full",
        ]
    )

    assert rc == 0
    full_record = full_payload["results"]["live_data"]["instruments"][0]
    assert full_record["mic"] == "XNAS"
    assert full_record["security_type_code"] == "CS"
