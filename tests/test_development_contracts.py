"""Development-hardening contracts for the xctx framework core."""

from __future__ import annotations

import copy
import json

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


def test_execute_accepts_exactly_one_plan_identifier() -> None:
    rc, payload = run_runtime_json(["execute", "abcde", "extra", "--commit"])

    assert rc == 1
    assert payload["record_type"] == "execution_result"
    assert payload["ok"] is False
    assert payload["error"] == "invalid_execute_shape"
    assert payload["results"]["next_move"] == "./xctx execute <PLAN_ID|SHA256|SHA5> --commit"


def test_repair_finding_prefix_must_match_current_state() -> None:
    rc, payload = run_runtime_json(["repair", "offline:stock_intelligence_hub::fundamentals_gateway"])

    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["ok"] is False
    assert "stale repair finding" in payload["error"]
    assert "down_for_maintenance" in payload["error"]
    assert payload["next_moves"] == [{"run_cmd": "./xctx audit root"}]


def test_command_surface_audit_reports_duplicate_group_entries() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.command_policy import command_surface_check  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    store["protocol"]["command_groups"]["main"].append("discover")
    store["protocol"]["command_groups"]["other"].append("other")

    check = command_surface_check(store)

    assert check["status"] == "fail"
    assert check["duplicate_main_entries"] == ["discover"]
    assert check["duplicate_other_entries"] == ["other"]


def test_execute_rejects_plan_recorded_against_stale_config_context(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import execute_payload, plan_payload  # noqa: PLC0415
    from xctx.store.plans import plan_store_dir  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = plan_payload(["bring_online", "macro_intelligence_hub"], store)
    path = plan_store_dir(store) / f"{plan['receipt_sha256']}.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["planner_context"]["config_sha256"] = "0" * 64
    path.write_text(json.dumps(stored, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    result = execute_payload([plan["receipt_sha256"]], True, store)

    assert result["ok"] is False
    assert result["error"] == "stale_plan_context"
    assert result["planner_binding"]["context_fingerprint_verified"] is False


def test_root_audit_exposes_loaded_config_fingerprint() -> None:
    rc, payload = run_runtime_json(["audit", "root"])

    assert rc == 0
    checks = payload["results"]["checks"]
    check_ids = {check["id"] for check in checks}
    fingerprint_check = next(check for check in checks if check["id"] == "audit:xctx:config_fingerprint")
    fingerprint = fingerprint_check["fingerprint"]
    assert fingerprint_check["status"] == "pass"
    assert fingerprint["algorithm"] == "sha256"
    assert len(fingerprint["sha256"]) == 64
    assert fingerprint["config_file_count"] == len(fingerprint["config_files"])
    assert all(entry["available"] for entry in fingerprint["config_files"])
    assert "audit:market_data_gateway:mini_stocks_sqlite_exists" in check_ids
    assert "audit:file_manager:home_directory:external_command:ls" in check_ids


def test_config_validation_rejects_subdomain_id_mismatch() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.config.validation import validate_loaded_store  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain_id, domain = next(iter(store["agent_domains"].items()))
    subdomain_id, subdomain = next(iter(domain["_subdomains"].items()))
    subdomain["id"] = "wrong_subdomain_id"

    with pytest.raises(XctxError, match=f"agent_subdomain id mismatch for {domain_id}::{subdomain_id}"):
        validate_loaded_store(store)


def test_option_config_audit_rejects_invalid_numeric_bounds() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.option_surface import option_config_checks  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain = next(iter(store["agent_domains"].values()))
    subdomain = next(iter(domain["_subdomains"].values()))
    subdomain.setdefault("cli_options", []).append(
        {
            "flags": ["--bad-bound"],
            "dest": "bad_bound",
            "commands": ["observe"],
            "type": "int",
            "min": "not-an-integer",
        }
    )

    checks = option_config_checks(store)
    failed = [check for check in checks if check["status"] == "fail"]

    assert failed
    assert any("bad_bound.min" in check.get("error", "") for check in failed)


def test_configured_integer_choices_are_parsed_as_integers() -> None:
    ensure_libs_path()
    from argparse import ArgumentParser  # noqa: PLC0415
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.option_specs import command_cli_option_specs  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain = next(iter(store["agent_domains"].values()))
    subdomain = next(iter(domain["_subdomains"].values()))
    subdomain.setdefault("cli_options", []).append(
        {
            "flags": ["--window"],
            "dest": "window",
            "commands": ["observe"],
            "type": "int",
            "choices": [1, "5"],
        }
    )

    spec = next(spec for spec in command_cli_option_specs(store, "observe") if spec["_dest"] == "window")
    parser = ArgumentParser(add_help=False)
    parser.add_argument("--window", type=int, choices=spec["choices"])

    assert spec["choices"] == [1, 5]
    assert parser.parse_args(["--window", "5"]).window == 5
