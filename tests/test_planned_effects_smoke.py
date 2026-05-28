"""Planned-effect smoke contracts for result handles and re-planning."""

from __future__ import annotations

import shlex
from datetime import timedelta

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(90)]


def _results(args: list[str]) -> dict:
    rc, payload = run_runtime_json(args)
    assert rc == 0, payload
    assert payload["ok"] is True
    return payload["results"]


def _plan_create_game() -> dict:
    return _results(
        [
            "plan",
            "guess_the_number_game::choose_random_number::choose_between_bounds",
            "--minimum",
            "1",
            "--maximum",
            "1000",
        ]
    )


def _commit(plan_id: str) -> dict:
    return _results(["execute", plan_id, "--commit"])


def _observe(result_id: str) -> dict:
    return _results(["observe", result_id])


def _plan_command_to_args(command: str) -> list[str]:
    parts = shlex.split(command)
    assert parts[:2] == ["./xctx", "plan"]
    return ["plan", *parts[2:]]


def test_planned_number_creation_records_commit_and_result_contract(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    plan = _plan_create_game()

    assert plan["status"] == "planned_effect"
    assert plan["decision"] == "commit_required"
    assert plan["writes_to_db"] is True
    assert plan["can_be_reversed"] is False
    assert plan["can_be_repaired"] is False
    assert plan["master_plan_id"].startswith("master_plan:")
    assert plan["sub_plan_id"].startswith("sub_plan:")
    assert plan["expected_commit_id"].startswith("commit:")
    assert plan["expected_result_id"].startswith("result:")
    assert plan["expected_result_id"].endswith(plan["receipt_sha256"])
    assert "hidden number" in plan["description_of_what_will_happen"]

    master_plan_path = tmp_path / "master_plan" / f"{plan['receipt_sha256']}.json"
    sub_plan_path = tmp_path / "sub_plan" / f"{plan['receipt_sha256']}.json"
    assert master_plan_path.exists()
    assert sub_plan_path.exists()

    discovered = _results(["discover", plan["master_plan_id"]])
    assert discovered["artifact_kind"] == "master_plan"
    assert discovered["master_plan_id"] == plan["master_plan_id"]
    assert discovered["status"] == "planned"
    assert discovered["execute_plan_cmd"] == plan["accepted_execute_cmd"]

    commit = _commit(plan["plan_id"])
    assert commit["status"] == "committed"
    assert commit["commit_id"] == plan["expected_commit_id"]
    assert commit["result_id"] == plan["expected_result_id"]
    assert commit["mutations_applied"] == 1

    committed_master_plan = _results(["discover", plan["master_plan_id"]])
    assert committed_master_plan["status"] == "committed"
    assert committed_master_plan["execution_status"] == "committed"
    assert committed_master_plan["result_id"] == commit["result_id"]

    observed = _observe(commit["result_id"])
    assert observed["status"] == "ready"
    assert observed["heartbeat"]["phase"] == "game_ready"
    assert observed["payload"]["object_type"] == "guess_the_number_game_created"
    assert observed["payload"]["range"] == {"min": 1, "max": 1000}
    assert "secret_number" not in observed["payload"]
    assert observed["payload"]["next_plan_command"].startswith(
        "./xctx plan guess_the_number_game::guess_number::submit_guess"
    )


def test_guess_plans_replan_until_yes_within_binary_search_bound(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    create = _commit(_plan_create_game()["plan_id"])
    game_result_id = create["result_id"]
    observed_game = _observe(game_result_id)
    next_plan_command = observed_game["payload"]["next_plan_command"]

    turns = 0
    feedback_seen: list[str] = []
    last_payload: dict | None = None
    while next_plan_command:
        turns += 1
        assert turns <= 10
        guess_plan = _results(_plan_command_to_args(next_plan_command))
        assert guess_plan["status"] == "planned_effect"
        assert game_result_id in guess_plan["description_of_what_will_happen"]
        guess_commit = _commit(guess_plan["plan_id"])
        guess_observed = _observe(guess_commit["result_id"])
        last_payload = guess_observed["payload"]
        feedback_seen.append(last_payload["feedback"])
        assert last_payload["feedback"] in {"higher", "lower", "yes"}
        assert "secret_number" not in last_payload
        if last_payload["correct"]:
            assert last_payload["feedback"] == "yes"
            assert last_payload["next_plan_command"] is None
            break
        next_plan_command = last_payload["next_plan_command"]

    assert last_payload is not None
    assert last_payload["correct"] is True
    assert turns <= 10
    assert feedback_seen[-1] == "yes"


def test_reexecuting_committed_plan_is_refused_with_existing_result_guidance(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    plan = _plan_create_game()
    first = _commit(plan["plan_id"])
    rc, second = run_runtime_json(["execute", plan["plan_id"], "--commit"])

    assert rc == 1
    assert first["status"] == "committed"
    assert second["ok"] is False
    assert second["error"] == "plan_already_committed"
    assert second["results"]["result_id"] == first["result_id"]
    assert second["results"]["mutations_applied"] == 0


def test_runtime_artifacts_are_exact_bearer_handles_not_indexes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    plan = _plan_create_game()
    discovered = _results(["discover", plan["master_plan_id"]])

    assert discovered["artifact_kind"] == "master_plan"
    assert discovered["master_plan_id"] == plan["master_plan_id"]

    for target in ("master_plan", "sub_plan", "commit"):
        rc, payload = run_runtime_json(["discover", target])
        assert rc == 1
        assert payload["record_type"] == "error"
        assert payload["ok"] is False
        assert payload["error"] == f"unknown discovery target: {target}"
        assert "results" in payload and payload["results"] == {}

    for malformed in ("master_plan:", "master_plan:not-a-sha"):
        rc, payload = run_runtime_json(["discover", malformed])
        assert rc == 1
        assert payload["record_type"] == "error"
        assert payload["ok"] is False
        assert payload["error"] == "invalid runtime artifact reference"

    unknown_master = "master_plan:" + ("b" * 64)
    rc, payload = run_runtime_json(["discover", unknown_master])
    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["ok"] is False
    assert payload["error"] == f"unknown runtime artifact: {unknown_master}"
    assert payload["next_moves"] == [{"run_cmd": "./xctx discover"}, {"run_cmd": "./xctx plan <operation> <target>"}]


def test_result_handle_can_expire_without_domain_scope(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.store.runtime_artifacts import isoformat_utc, utc_now, write_runtime_artifact  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    digest = "a" * 64
    write_runtime_artifact(
        store,
        "result",
        digest,
        {
            "result_id": f"result:{digest}",
            "commit_id": f"commit:{digest}",
            "plan_id": f"plan:sha256:{digest}",
            "status": "ready",
            "created_at": isoformat_utc(utc_now() - timedelta(minutes=10)),
            "expires_at": isoformat_utc(utc_now() - timedelta(minutes=1)),
            "heartbeat_at": isoformat_utc(utc_now() - timedelta(minutes=10)),
            "heartbeat": {"phase": "complete", "message": "Result was ready."},
            "payload": {"value": "gone"},
        },
    )

    observed = _observe(f"result:{digest}")

    assert observed["status"] == "expired"
    assert observed["payload"] is None
    assert observed["heartbeat"]["phase"] == "expired"


def test_core_hook_points_do_not_contain_game_domain_vocabulary() -> None:
    generic_files = [
        "libs/xctx/domain/planning.py",
        "libs/xctx/domain/observation.py",
        "libs/xctx/store/runtime_artifacts.py",
    ]
    forbidden = ("guess_the_number_game", "choose_random_number", "guess_number", "secret_number")
    for rel in generic_files:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), rel
