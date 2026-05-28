"""Unit contracts for the planning public wrapper and execute module split."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from framework_helpers import ROOT, ensure_libs_path


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(90)]


def _load_store(tmp_path, monkeypatch) -> dict:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    return load_store(root=ROOT)


def _direct_planned_effect(store: dict) -> dict:
    ensure_libs_path()
    from xctx.domain.planning import plan_payload  # noqa: PLC0415

    return plan_payload(
        [
            "guess_the_number_game::choose_random_number::choose_between_bounds",
            "--minimum",
            "1",
            "--maximum",
            "1000",
        ],
        store,
    )


def test_planning_execute_payload_delegates_to_execute_module(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning  # noqa: PLC0415

    calls: list[tuple[list[str], bool, dict]] = []
    sentinel = {"ok": True, "source": "execute_module"}

    def fake_execute(args, commit, store):
        calls.append((args, commit, store))
        return sentinel

    store = {"store": "sentinel"}
    monkeypatch.setattr(planning, "_execute_payload", fake_execute)

    result = planning.execute_payload(["plan:sha256:" + ("a" * 64)], True, store)

    assert result is sentinel
    assert calls == [(["plan:sha256:" + ("a" * 64)], True, store)]


def test_planning_plan_payload_routes_planned_effect_to_planned_effect_module(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning  # noqa: PLC0415

    planned = {"domain": "domain", "action": "action"}
    sentinel = {"ok": True, "source": "planned_effect"}

    monkeypatch.setattr(
        planning,
        "parse_plan_request",
        lambda args: SimpleNamespace(operation="mutate", raw_args=["mutate", "target"]),
    )
    monkeypatch.setattr(planning, "_resolve_planned_action", lambda store, operation, args: planned)
    monkeypatch.setattr(planning, "_planned_effect_plan_payload", lambda args, store, resolved: sentinel)

    assert planning.plan_payload(["mutate", "target"], {"store": "sentinel"}) is sentinel


def test_planning_plan_payload_routes_unplanned_command_to_read_only_module(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning  # noqa: PLC0415

    sentinel = {"ok": True, "source": "read_only"}

    monkeypatch.setattr(
        planning,
        "parse_plan_request",
        lambda args: SimpleNamespace(operation="discover", raw_args=["discover", "root"]),
    )
    monkeypatch.setattr(planning, "_resolve_planned_action", lambda store, operation, args: None)
    monkeypatch.setattr(planning, "_read_only_plan_payload", lambda args, store: sentinel)

    assert planning.plan_payload(["discover", "root"], {"store": "sentinel"}) is sentinel


def test_execute_module_requires_plan_identifier_without_store_lookup(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415

    monkeypatch.setattr(
        planning_execute,
        "resolve_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("store lookup should not run")),
    )

    result = planning_execute.execute_payload([], True, {})

    assert result["ok"] is False
    assert result["error"] == "plan_required"


def test_execute_module_rejects_multiple_plan_identifiers_without_store_lookup(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415

    monkeypatch.setattr(
        planning_execute,
        "resolve_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("store lookup should not run")),
    )

    result = planning_execute.execute_payload(["plan:sha256:" + ("a" * 64), "extra"], True, {})

    assert result["ok"] is False
    assert result["error"] == "invalid_execute_command"


def test_execute_module_rejects_raw_receipt_without_store_lookup(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415

    monkeypatch.setattr(
        planning_execute,
        "resolve_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("store lookup should not run")),
    )

    result = planning_execute.execute_payload(["a" * 64], True, {})

    assert result["ok"] is False
    assert result["error"] == "plan_id_required"


def test_execute_module_requires_commit_without_store_lookup(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning_execute  # noqa: PLC0415

    monkeypatch.setattr(
        planning_execute,
        "resolve_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("store lookup should not run")),
    )

    result = planning_execute.execute_payload(["plan:sha256:" + ("a" * 64)], False, {})

    assert result["ok"] is False
    assert result["error"] == "commit_required"


def test_execute_module_marks_read_only_plan_committed(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain.planning import plan_payload  # noqa: PLC0415
    from xctx.domain.planning_execute import execute_payload  # noqa: PLC0415
    from xctx.store.plans import read_plan  # noqa: PLC0415

    store = _load_store(tmp_path, monkeypatch)
    plan = plan_payload(["bring_online", "macro_intelligence_hub"], store)

    result = execute_payload([plan["plan_id"]], True, store)
    persisted = read_plan(store, plan["receipt_sha256"])

    assert result["ok"] is True
    assert persisted is not None
    assert persisted["execution_status"] == "committed"


def test_execute_module_uses_moved_adapter_call_boundary(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.domain import planning, planning_execute  # noqa: PLC0415

    store = _load_store(tmp_path, monkeypatch)
    plan = _direct_planned_effect(store)
    calls: list[list[str]] = []

    def fake_call(_store, _subdomain, args):
        calls.append(list(args))
        return {"object_type": "test_adapter_success"}

    monkeypatch.setattr(planning_execute, "call_external_command", fake_call)

    result = planning_execute.execute_payload([plan["plan_id"]], True, store)

    assert result["ok"] is True
    assert calls
    assert calls[0][0] == plan["planned_effect"]["commit_adapter_command"]
    assert calls[0][-6:] == [
        "--xctx-plan-id",
        plan["plan_id"],
        "--xctx-commit-id",
        plan["expected_commit_id"],
        "--xctx-result-id",
        plan["expected_result_id"],
    ]
    assert not hasattr(planning, "call_external_command")
