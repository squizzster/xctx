from __future__ import annotations

from types import SimpleNamespace

import pytest

from framework_helpers import ROOT, ensure_libs_path


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


def test_planned_effect_preflight_calls_configured_adapter_command(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx.domain.planning_intent import PlannedAction, PlannedActionArgs  # noqa: PLC0415
    from xctx.domain.planning_planned_effect_plan_preflight import planned_effect_plan_preflight  # noqa: PLC0415
    from xctx.domain import planning_planned_effect_plan_preflight as module  # noqa: PLC0415

    calls: list[tuple[dict, dict, list[str]]] = []
    subdomain = {"id": "demo_subdomain", "_domain_id": "demo_domain"}

    monkeypatch.setattr(module, "resolve_subdomain", lambda _store, _domain, _subdomain: subdomain)
    monkeypatch.setattr(
        module,
        "call_external_command",
        lambda store, scoped, args: calls.append((store, scoped, args)) or {"ok": True},
    )

    planned = PlannedAction(
        "demo_domain",
        "demo_subdomain",
        "demo_action",
        {"run_cmd": "./xctx plan demo_domain::demo_subdomain::demo_action --value 1"},
        {"preflight_adapter_command": "validate-demo"},
    )
    parsed = PlannedActionArgs(values={"value": 1}, adapter_args=["--value", "1"], positional_args=[])

    planned_effect_plan_preflight({"root": ROOT}, planned, parsed)

    assert calls == [({"root": ROOT}, subdomain, ["validate-demo", "--value", "1"])]


def test_planned_effect_preflight_raises_structured_adapter_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx.domain.planning_intent import PlannedAction, PlannedActionArgs  # noqa: PLC0415
    from xctx.domain.planning_planned_effect_plan_preflight import planned_effect_plan_preflight  # noqa: PLC0415
    from xctx.domain import planning_planned_effect_plan_preflight as module  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    monkeypatch.setattr(module, "resolve_subdomain", lambda *_args: {"id": "demo_subdomain"})
    monkeypatch.setattr(module, "call_external_command", lambda *_args: {"ok": False, "error": "bad preflight"})

    planned = PlannedAction(
        "demo_domain",
        "demo_subdomain",
        "demo_action",
        {"run_cmd": "./xctx plan demo_domain::demo_subdomain::demo_action"},
        {"preflight_adapter_command": "validate-demo"},
    )

    with pytest.raises(XctxError, match="bad preflight") as raised:
        planned_effect_plan_preflight(
            {"root": ROOT},
            planned,
            PlannedActionArgs(values={}, adapter_args=[], positional_args=[]),
        )

    assert raised.value.next_moves == ["./xctx plan demo_domain::demo_subdomain::demo_action"]


def test_planned_effect_preflight_preserves_adapter_next_moves(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx.domain.planning_intent import PlannedAction, PlannedActionArgs  # noqa: PLC0415
    from xctx.domain.planning_planned_effect_plan_preflight import planned_effect_plan_preflight  # noqa: PLC0415
    from xctx.domain import planning_planned_effect_plan_preflight as module  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    next_moves = ["./xctx discover demo_domain::demo_subdomain"]
    monkeypatch.setattr(module, "resolve_subdomain", lambda *_args: {"id": "demo_subdomain"})
    monkeypatch.setattr(
        module,
        "call_external_command",
        lambda *_args: {"ok": False, "error": "bad preflight", "next_moves": next_moves},
    )

    planned = PlannedAction(
        "demo_domain",
        "demo_subdomain",
        "demo_action",
        {"run_cmd": "./xctx plan demo_domain::demo_subdomain::demo_action"},
        {"preflight_adapter_command": "validate-demo"},
    )

    with pytest.raises(XctxError, match="bad preflight") as raised:
        planned_effect_plan_preflight(
            {"root": ROOT},
            planned,
            PlannedActionArgs(values={}, adapter_args=[], positional_args=[]),
        )

    assert raised.value.next_moves == next_moves


def test_planned_effect_preflight_treats_command_status_failure_as_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_libs_path()
    from xctx.domain.planning_intent import PlannedAction, PlannedActionArgs  # noqa: PLC0415
    from xctx.domain.planning_planned_effect_plan_preflight import planned_effect_plan_preflight  # noqa: PLC0415
    from xctx.domain import planning_planned_effect_plan_preflight as module  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    monkeypatch.setattr(module, "resolve_subdomain", lambda *_args: {"id": "demo_subdomain"})
    monkeypatch.setattr(
        module,
        "call_external_command",
        lambda *_args: {"command_status": {"ok": False, "error": "command rejected"}},
    )

    planned = PlannedAction(
        "demo_domain",
        "demo_subdomain",
        "demo_action",
        {"run_cmd": "./xctx plan demo_domain::demo_subdomain::demo_action"},
        {"preflight_adapter_command": "validate-demo"},
    )

    with pytest.raises(XctxError, match="command rejected"):
        planned_effect_plan_preflight(
            {"root": ROOT},
            planned,
            PlannedActionArgs(values={}, adapter_args=[], positional_args=[]),
        )


def test_connector_parse_controls_reports_clean_integer_errors() -> None:
    ensure_libs_path()
    from xctx_connectors.runtime import parse_controls  # noqa: PLC0415

    with pytest.raises(ValueError, match="^--limit requires an integer$"):
        parse_controls(["--limit", "abc"], default_limit=10, max_limit=50)

    with pytest.raises(ValueError, match="^--cursor requires an integer$"):
        parse_controls(["--cursor", "abc"], default_limit=10, max_limit=50)


def test_connector_parse_controls_returns_rest_and_controls() -> None:
    ensure_libs_path()
    from xctx_connectors.runtime import parse_controls  # noqa: PLC0415

    rest, controls = parse_controls(
        ["file:README.txt", "--limit", "3", "--cursor", "2", "--projection", "full"],
        default_limit=10,
        max_limit=50,
    )

    assert rest == ["file:README.txt"]
    assert controls == {"limit": 3, "cursor": 2, "projection": "full"}


def test_file_manager_not_found_helper_uses_canonical_action_refs() -> None:
    ensure_libs_path()
    from xctx_connectors.domains.file_manager.external_command_adapter import _filesystem_not_found  # noqa: PLC0415

    context = SimpleNamespace(adapter_ref="file_manager::home_directory")
    runtime = SimpleNamespace(detail_is_max=lambda _context: False)

    payload = _filesystem_not_found(context, "missing.txt", expected="file", runtime=runtime)

    assert payload["next_moves"] == [
        "./xctx discover file_manager::home_directory::list_files",
        "./xctx discover file_manager::home_directory::list_directories",
    ]


def test_game_preflight_helpers_return_structured_read_only_failures(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_libs_path()
    from xctx_connectors.domains.guess_the_number_game import external_command_adapter as adapter  # noqa: PLC0415

    context = SimpleNamespace(workspace_root=ROOT)
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    bogus = "result:" + "a" * 64

    choose = adapter._validate_choose_between_bounds(context, ["--minimum", "10", "--maximum", "1"])
    submit = adapter._validate_submit_guess(context, ["--game-result", bogus, "--guess", "5"])

    assert choose == {
        "ok": False,
        "error": "--minimum must be less than or equal to --maximum",
    }
    assert submit == {
        "ok": False,
        "error": f"unknown game result handle: {bogus}",
    }
    assert not (tmp_path / "guess_the_number_game").exists()


def test_equity_search_arg_parser_bounds_controls_and_keeps_query_order() -> None:
    from examples.stock_intelligence_hub.adapters.equity_filings import parse_search_args  # noqa: PLC0415

    assert parse_search_args(["annual", "report", "--limit", "7", "--projection", "full"]) == (
        "annual report",
        7,
        "full",
    )
    assert parse_search_args(["annual", "--limit", "999"])[1] == 50

    with pytest.raises(ValueError, match="^--limit requires an integer$"):
        parse_search_args(["annual", "--limit", "nope"])


def test_market_search_arg_parser_bounds_controls_and_keeps_query_order() -> None:
    from examples.stock_intelligence_hub.adapters.market_data_gateway import parse_search_args  # noqa: PLC0415

    assert parse_search_args(["alpha", "inc", "--limit", "4", "--projection", "full"]) == (
        "alpha inc",
        4,
        "full",
    )
    assert parse_search_args(["alpha", "--limit", "999"])[1] == 50

    with pytest.raises(ValueError, match="^--projection must be compact or full$"):
        parse_search_args(["alpha", "--projection", "wide"])


def test_priority_bucket_pagination_metadata_is_truthful_directly() -> None:
    ensure_libs_path()
    from xctx_live.filings import list_priority_buckets  # noqa: PLC0415

    payload = list_priority_buckets(ROOT, limit=1)
    page = payload["pagination"]

    assert payload["returned_count"] == 1
    assert page["cursor_supported"] is False
    assert page["partial"] is True
    assert page["remaining_count"] == payload["total_count"] - 1


def test_market_exact_instrument_lookup_does_not_fuzzy_match_shell_literal() -> None:
    ensure_libs_path()
    from xctx_live.instruments import find_instrument_exact, market_series_search_payload  # noqa: PLC0415

    assert find_instrument_exact(ROOT, "AAPL")["ticker"] == "AAPL"
    assert find_instrument_exact(ROOT, "$(id)") is None
    payload = market_series_search_payload(ROOT, "$(id)")
    assert payload["matches"] == []
    assert "Known instrument" not in str(payload["empty_result_guidance"])


def test_market_series_search_payload_respects_limit_and_compact_projection() -> None:
    ensure_libs_path()
    from xctx_live.instruments import market_series_search_payload  # noqa: PLC0415

    payload = market_series_search_payload(ROOT, "a", limit=2, projection="compact")

    assert payload["limit"] == 2
    assert payload["projection"] == "compact"
    assert payload["matches_returned"] <= 2
    assert all("latest_bar" not in match for match in payload["matches"])


def test_market_bar_payload_normalizes_scaled_volume() -> None:
    ensure_libs_path()
    from xctx_live.instruments import VOLUME_SCALE, _bar_payload, connect_market  # noqa: PLC0415

    with connect_market(ROOT) as conn:
        row = conn.execute(
            """
            SELECT b.*
            FROM ohlcv_bars b
            JOIN bar_datasets d ON d.dataset_id = b.dataset_id
            JOIN ohlcv_series s ON s.ohlcv_series_id = d.ohlcv_series_id
            WHERE s.latest_ticker = 'AAPL'
            ORDER BY b.bar_date_key DESC
            LIMIT 1
            """
        ).fetchone()

    assert row is not None
    bar = _bar_payload(row, include_ts=True)

    assert bar["volume"] == bar["volume_raw"] // VOLUME_SCALE
    assert bar["volume_scale"] == VOLUME_SCALE
    assert bar["volume_unit"] == "shares"
    assert bar["volume_raw_unit"] == "shares_x1000"
