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
