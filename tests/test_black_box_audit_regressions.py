from __future__ import annotations

import json

import pytest

from framework_helpers import run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


# Framework/ledger tests


def test_unknown_plan_operation_does_not_create_executable_receipt() -> None:
    rc, payload = run_runtime_json(["plan", "delete_everything", "file_manager"])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["record_type"] == "error"
    assert payload["error"] == "unknown or non-plannable operation: delete_everything"
    assert "accepted_execute_cmd" not in json.dumps(payload)


def test_unknown_plan_without_commit_reports_unknown_not_commit_required() -> None:
    fake = "plan:sha256:" + "a" * 64

    rc, payload = run_runtime_json(["execute", fake])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "unknown_plan_receipt"
    assert payload["results"]["next_move"] == "./xctx plan <operation> <target>"


def test_known_plan_without_commit_still_reports_commit_required(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    rc, plan = run_runtime_json(
        [
            "plan",
            "guess_the_number_game::choose_random_number::choose_between_bounds",
            "--minimum",
            "1",
            "--maximum",
            "10",
        ]
    )
    assert rc == 0

    rc, payload = run_runtime_json(["execute", plan["results"]["plan_id"]])

    assert rc == 1
    assert payload["error"] == "commit_required"


def test_domain_affordance_reports_requested_and_implemented_scope() -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::search_filing_form",
            "10-K",
        ]
    )

    assert rc == 0
    assert payload["domain_level"] == "agent_subdomain"

    results = payload["results"]
    assert results["domain_affordance"] is True
    assert results["requested_scope_level"] == "agent_domain_affordance"
    assert results["implemented_scope_level"] == "agent_subdomain"
    assert results["implemented_by"] == "stock_intelligence_hub::equity_filing::search_forms"


# Framework/runtime-ref guidance tests


def test_discover_id_rejects_domain_object_ids_with_scoped_guidance() -> None:
    rc, payload = run_runtime_json(["discover", "--id", "instrument:aapl"])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "discover --id only accepts protocol artifact ids"
    assert payload["next_moves"] == [
        {"run_cmd": "./xctx discover <agent_domain>::<agent_subdomain> <query-or-id>"},
        {"run_cmd": "./xctx observe <agent_domain>::<agent_subdomain> --id <id>"},
    ]


def test_discover_result_id_points_to_observe_result() -> None:
    result_ref = "result:" + "a" * 64

    rc, payload = run_runtime_json(["discover", "--id", result_ref])

    assert rc == 1
    assert payload["error"] == "result handles are observed, not discovered"
    assert payload["next_moves"] == [{"run_cmd": f"./xctx observe {result_ref}"}]


def test_observe_master_plan_guides_to_discover_master_plan() -> None:
    ref = "master_plan:" + "a" * 64

    rc, payload = run_runtime_json(["observe", ref])

    assert rc == 1
    assert payload["error"] == "master_plan artifacts are discovered, not observed"
    assert payload["next_moves"] == [{"run_cmd": f"./xctx discover {ref}"}]


# Framework/audit-scope tests


def test_audit_accepts_trailing_domain_scope_separator() -> None:
    rc1, p1 = run_runtime_json(["audit", "file_manager"])
    rc2, p2 = run_runtime_json(["audit", "file_manager::"])

    assert rc1 == rc2
    assert p1["ok"] == p2["ok"]
    assert p2["results"]["scope"] == "file_manager"
    assert p2["domain_level"] == "agent_domain"


def test_live_audit_declares_that_availability_findings_are_excluded() -> None:
    rc, payload = run_runtime_json(["audit", "--scope", "live", "root"])

    assert rc == 0
    contract = payload["results"]["scope_contract"]
    assert contract["requested"] == "live"
    assert contract["availability_findings_included"] is False
    assert contract["excluded_availability_findings"] >= 1
    assert payload["results"]["findings"] == []


# Adapter/game-planned-effect tests


def test_choose_bounds_rejected_at_plan_time_before_ledger(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    rc, payload = run_runtime_json(
        [
            "plan",
            "guess_the_number_game::choose_random_number::choose_between_bounds",
            "--minimum",
            "10",
            "--maximum",
            "1",
        ]
    )

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "--minimum must be less than or equal to --maximum"
    assert "plan_id" not in json.dumps(payload)


def test_malformed_game_result_rejected_by_configured_pattern_before_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    rc, payload = run_runtime_json(
        [
            "plan",
            "guess_the_number_game::guess_number::submit_guess",
            "--game-result",
            "result:bogus",
            "--guess",
            "5",
        ]
    )

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "--game-result must match pattern ^result:[0-9a-f]{64}$"
    assert "plan_id" not in json.dumps(payload)


def test_unknown_game_result_rejected_at_plan_time(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    bogus = "result:" + "a" * 64

    rc, payload = run_runtime_json(
        [
            "plan",
            "guess_the_number_game::guess_number::submit_guess",
            "--game-result",
            bogus,
            "--guess",
            "5",
        ]
    )

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == f"unknown game result handle: {bogus}"
    assert "plan_id" not in json.dumps(payload)


# Adapter/file-manager tests


def test_file_manager_list_files_always_includes_pagination() -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "file_manager::home_directory::list_files",
            "--limit",
            "3",
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert "pagination" in live
    assert live["pagination"]["total_count"] >= live["pagination"]["returned_count"]
    assert {"total_count", "returned_count", "limit", "cursor", "next_cursor", "has_more"} <= set(
        live["pagination"]
    )


def test_file_manager_not_found_guidance_uses_canonical_action_ref() -> None:
    rc, payload = run_runtime_json(
        [
            "observe",
            "file_manager::home_directory",
            "file:does-not-exist.txt",
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["found"] is False
    moves = json.dumps(live["next_moves"])
    assert "./xctx discover file_manager::home_directory::list_files" in moves
    assert "./xctx discover file_manager::home_directory list_files" not in moves


def test_file_manager_bad_cursor_returns_clean_connector_error() -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "file_manager::home_directory::list_files",
            "--cursor",
            "abc",
        ]
    )

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "--cursor requires an integer"
    assert "invalid literal" not in json.dumps(payload)


# Adapter/filing-taxonomy tests


def test_priority_bucket_limit_without_cursor_reports_partial_truthfully() -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::equity_filing::list_priority_buckets",
            "--limit",
            "1",
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["total_count"] == 12
    assert live["returned_count"] == 1

    page = live["pagination"]
    assert page["cursor_supported"] is False
    assert page["next_cursor"] is None
    assert page["has_more"] is False
    assert page["partial"] is True
    assert page["more_available"] is True
    assert page["remaining_count"] == 11


def test_search_forms_accepts_limit_and_returns_bounded_matches() -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::equity_filing::search_forms",
            "annual",
            "--limit",
            "5",
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["limit"] == 5
    assert live["matches_returned"] <= 5
    assert len(live["matches"]) <= 5


def test_search_families_accepts_limit_and_compact_projection() -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::equity_filing::search_families",
            "report",
            "--limit",
            "3",
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["projection"] == "compact"
    assert live["limit"] == 3
    assert live["matches_returned"] <= 3
    if live["matches"]:
        assert "description" not in live["matches"][0]


def test_search_priority_buckets_accepts_limit() -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::equity_filing::search_priority_buckets",
            "critical",
            "--limit",
            "2",
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["limit"] == 2
    assert live["matches_returned"] <= 2


# Adapter/market-data tests


def test_search_market_series_accepts_limit() -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::market_data_gateway::search_market_series",
            "a",
            "--limit",
            "3",
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["limit"] == 3
    assert live["matches_returned"] <= 3


def test_market_series_shell_like_literal_has_no_unrelated_guidance() -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::market_data_gateway::search_market_series",
            "$(id)",
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["matches_returned"] == 0
    assert "ACIW" not in json.dumps(live)
    assert "Known instrument" not in str(live.get("empty_result_guidance"))


def test_stock_list_instruments_rejects_out_of_range_cursor() -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::market_data_gateway::list_instruments",
            "--cursor",
            "999999",
        ]
    )

    assert rc == 1
    assert payload["ok"] is False
    assert "--cursor out of range" in payload["error"]


def test_bars_zero_declares_all_available_in_basic_payload() -> None:
    rc, payload = run_runtime_json(
        [
            "observe",
            "stock_intelligence_hub::market_data_gateway",
            "AAPL",
            "--bars",
            "0",
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["request"] == {"unit": "bars", "value": 0, "all_available": True}
    assert live["range_controls"]["bars_zero_semantics"] == "all_available_bars"


def test_market_bars_expose_volume_units_and_normalized_volume() -> None:
    rc, payload = run_runtime_json(
        [
            "observe",
            "stock_intelligence_hub::market_data_gateway",
            "AAPL",
            "--bars",
            "1",
        ]
    )

    assert rc == 0
    bar = payload["results"]["live_data"]["bars"][0]
    assert "volume" in bar
    assert "volume_raw" in bar
    assert bar["volume_unit"] == "shares"
    assert bar["volume_scale"] in {1, 1000}
