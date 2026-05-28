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


def _plan_game(minimum: int = 1, maximum: int = 1) -> dict:
    rc, payload = run_runtime_json(
        [
            "plan",
            "guess_the_number_game::choose_random_number::choose_between_bounds",
            "--minimum",
            str(minimum),
            "--maximum",
            str(maximum),
        ]
    )
    assert rc == 0, payload
    return payload["results"]


def _commit_plan(plan_id: str) -> dict:
    rc, payload = run_runtime_json(["execute", plan_id, "--commit"])
    assert rc == 0, payload
    return payload["results"]


def _plan_guess(game_result: str, guess: int) -> tuple[int, dict]:
    return run_runtime_json(
        [
            "plan",
            "guess_the_number_game::guess_number::submit_guess",
            "--game-result",
            game_result,
            "--guess",
            str(guess),
        ]
    )


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


def test_solved_game_rejects_later_guess_plan_before_ledger(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    create = _commit_plan(_plan_game(1, 1)["plan_id"])
    game_result = create["result_id"]
    rc, first_guess = _plan_guess(game_result, 1)
    assert rc == 0
    solved = _commit_plan(first_guess["results"]["plan_id"])
    rc, solved_result = run_runtime_json(["observe", solved["result_id"]])
    assert rc == 0
    assert solved_result["results"]["payload"]["game_status"] == "solved"

    rc, rejected = _plan_guess(game_result, 1)

    assert rc == 1
    assert rejected["ok"] is False
    assert rejected["error"] == "game is already solved"
    assert "plan_id" not in json.dumps(rejected)


def test_stale_preplanned_guess_after_solve_fails_without_game_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    create = _commit_plan(_plan_game(1, 1)["plan_id"])
    game_result = create["result_id"]
    rc, first_guess = _plan_guess(game_result, 1)
    assert rc == 0
    rc, stale_guess = _plan_guess(game_result, 1)
    assert rc == 0

    _commit_plan(first_guess["results"]["plan_id"])
    rc, stale_commit = run_runtime_json(["execute", stale_guess["results"]["plan_id"], "--commit"])

    assert rc == 1
    assert stale_commit["ok"] is False
    assert stale_commit["error"] == "planned_effect_commit_failed"
    assert stale_commit["results"]["mutations_applied"] == 0
    rc, scoped_state = run_runtime_json(["observe", "guess_the_number_game::guess_number", game_result])
    assert rc == 0
    live = scoped_state["results"]["live_data"]
    assert live["status"] == "solved"
    assert live["attempt_count"] == 1
    assert "secret_number" not in json.dumps(live)


def test_guess_outside_original_game_range_rejected_before_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    create = _commit_plan(_plan_game(1, 1)["plan_id"])

    rc, payload = _plan_guess(create["result_id"], 2)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "--guess must be between 1 and 1 for this game"
    assert "plan_id" not in json.dumps(payload)


def test_guess_outside_current_unresolved_range_rejected_before_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    digest = "b" * 64
    game_result = f"result:{digest}"
    game_dir = tmp_path / "guess_the_number_game" / "games"
    game_dir.mkdir(parents=True)
    (game_dir / f"{digest}.json").write_text(
        json.dumps(
            {
                "game_result_id": game_result,
                "created_at": "2026-05-28T00:00:00Z",
                "range": {"min": 1, "max": 4},
                "current_range": {"min": 3, "max": 4},
                "secret_number": 4,
                "attempts": [{"guess": 2, "feedback": "higher", "correct": False}],
                "status": "active",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rc, rejected = _plan_guess(game_result, 1)

    assert rc == 1
    assert rejected["ok"] is False
    assert rejected["error"] == "--guess must be within current unresolved range 3..4"
    assert "plan_id" not in json.dumps(rejected)


def test_scoped_game_observe_reports_current_state_without_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    create = _commit_plan(_plan_game(1, 1)["plan_id"])
    game_result = create["result_id"]
    rc, guess = _plan_guess(game_result, 1)
    assert rc == 0
    _commit_plan(guess["results"]["plan_id"])

    rc, scoped_state = run_runtime_json(["observe", "guess_the_number_game::choose_random_number", game_result])

    assert rc == 0
    live = scoped_state["results"]["live_data"]
    assert live["object_type"] == "guess_the_number_game_state"
    assert live["status"] == "solved"
    assert live["attempt_count"] == 1
    assert live["next_plan_command"] is None
    assert "secret_number" not in json.dumps(live)


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


@pytest.mark.parametrize(
    "query",
    [
        "instrument:../../aapl",
        "instrument:aapl/../msft",
        "issuer:cik:../../0000320193",
        "market_series:../../aapl:daily",
        "market_series:aapl:daily/../../msft",
        "ohlcv_series:../../1",
        "ticker:../../aapl",
    ],
)
def test_malformed_stock_reserved_identifiers_do_not_resolve_in_instrument_search(query: str) -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::market_data_gateway::search_entity_instrument",
            query,
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["total_matches"] == 0
    assert live["matches_returned"] == 0
    matches = json.dumps(live["matches"]).lower()
    assert "instrument:aapl" not in matches
    assert "instrument:msft" not in matches


@pytest.mark.parametrize(
    "query",
    [
        "instrument:../../aapl",
        "issuer:cik:../../0000320193",
        "market_series:../../aapl:daily",
        "ohlcv_series:../../1",
    ],
)
def test_malformed_stock_reserved_identifiers_do_not_resolve_market_series(query: str) -> None:
    rc, payload = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::market_data_gateway::search_market_series",
            query,
        ]
    )

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["matches_returned"] == 0
    assert live["matches"] == []
    assert "market_series:aapl:daily" not in json.dumps(live).lower()


@pytest.mark.parametrize(
    "query",
    [
        "instrument:../../aapl",
        "issuer:cik:../../0000320193",
        "market_series:../../aapl:daily",
    ],
)
def test_malformed_stock_reserved_identifiers_do_not_resolve_latest_price(query: str) -> None:
    rc, payload = run_runtime_json(["discover", "stock_intelligence_hub::latest_price", query])

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["found"] is False
    assert live["candidate_instruments"] == []
    assert live["candidate_series"] == []
    assert "instrument:aapl" not in json.dumps(live).lower()


@pytest.mark.parametrize(
    "query",
    [
        "instrument:../../aapl",
        "issuer:cik:../../0000320193",
        "market_series:../../aapl:daily",
    ],
)
def test_malformed_stock_reserved_identifiers_do_not_resolve_observe(query: str) -> None:
    rc, payload = run_runtime_json(["observe", "stock_intelligence_hub::market_data_gateway", query])

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["found"] is False
    assert live.get("candidate_instruments", []) == []
    assert live.get("candidate_market_series", live.get("candidate_series", [])) == []
    candidates = json.dumps(
        {
            "candidate_instruments": live.get("candidate_instruments", []),
            "candidate_market_series": live.get("candidate_market_series", []),
            "candidate_series": live.get("candidate_series", []),
        }
    ).lower()
    assert "instrument:aapl" not in candidates


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("instrument:aapl", "instrument:aapl"),
        ("issuer:cik:0000320193", "instrument:aapl"),
        ("market_series:aapl:daily", "market_series:aapl:daily"),
    ],
)
def test_well_formed_stock_reserved_identifiers_still_resolve(query: str, expected: str) -> None:
    rc, payload = run_runtime_json(["observe", "stock_intelligence_hub::market_data_gateway", query])

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["found"] is True
    assert expected in json.dumps(live).lower()
