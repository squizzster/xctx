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
    assert payload["error"] == "invalid_execute_command"
    assert payload["results"]["next_move"] == "./xctx execute <PLAN_ID> --commit"


def test_plan_ref_parser_accepts_only_canonical_plan_id() -> None:
    ensure_libs_path()
    from xctx.store.plans import parse_plan_ref  # noqa: PLC0415

    digest = "a" * 64
    canonical = parse_plan_ref(f"plan:sha256:{digest}")
    raw = parse_plan_ref(digest)
    short = parse_plan_ref(digest[:5])
    malformed = parse_plan_ref("plan:sha256:not-a-sha")

    assert canonical.ok is True
    assert canonical.receipt_sha256 == digest
    assert raw.ok is False
    assert raw.error == "plan_id_required"
    assert short.ok is False
    assert short.error == "plan_id_required"
    assert malformed.ok is False
    assert malformed.error == "invalid_plan_receipt"


def test_resolve_plan_rejects_raw_and_short_receipts(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.planning import plan_payload  # noqa: PLC0415
    from xctx.store.plans import resolve_plan  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    plan = plan_payload(["bring_online", "macro_intelligence_hub"], store)

    assert resolve_plan(store, plan["plan_id"]).ok is True
    raw = resolve_plan(store, plan["receipt_sha256"])
    short = resolve_plan(store, plan["receipt_sha5"])

    assert raw.ok is False
    assert raw.error == "plan_id_required"
    assert short.ok is False
    assert short.error == "plan_id_required"


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

    result = execute_payload([plan["plan_id"]], True, store)

    assert result["ok"] is False
    assert result["error"] == "stale_plan_context"
    assert result["planner_binding"]["context_fingerprint_verified"] is False


def test_root_audit_exposes_loaded_config_fingerprint() -> None:
    rc, payload = run_runtime_json(["--max", "audit", "root"])

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


def test_config_validation_rejects_invalid_domain_and_action_ids() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.config.validation import validate_loaded_store  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain = store["agent_domains"].pop("stock_intelligence_hub")
    domain["id"] = "Bad-Domain"
    store["agent_domains"]["Bad-Domain"] = domain

    with pytest.raises(XctxError, match="invalid agent_domain id: Bad-Domain"):
        validate_loaded_store(store)

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["actions"]["bad-action"] = {"entrypoint_command": "bad-action"}

    with pytest.raises(XctxError, match="invalid agent_subdomain stock_intelligence_hub::market_data_gateway.actions action id"):
        validate_loaded_store(store)


def test_config_validation_rejects_invalid_connector_kind() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.config.validation import validate_loaded_store  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["connector"]["kind"] = "unsafe_adapter"

    with pytest.raises(XctxError, match="unsupported agent_subdomain stock_intelligence_hub::market_data_gateway.connector.kind"):
        validate_loaded_store(store)


def test_config_validation_requires_connector_supervisor_entrypoint() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.config.validation import validate_loaded_store  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["entrypoint"]["file"] = "examples/stock_intelligence_hub/adapters/market_data_gateway.py"

    with pytest.raises(XctxError, match="entrypoint.file must be connector_supervisor.py"):
        validate_loaded_store(store)


def test_config_validation_rejects_passthrough_target_escape() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.config.validation import validate_loaded_store  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["connector"]["target_entrypoint"] = "../outside.py"

    with pytest.raises(XctxError, match="connector.target_entrypoint resolves outside"):
        validate_loaded_store(store)


def test_config_validation_rejects_invalid_connector_limits() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.config.validation import validate_loaded_store  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["connector"]["timeout_seconds"] = 0

    with pytest.raises(XctxError, match="connector.timeout_seconds"):
        validate_loaded_store(store)

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["connector"]["max_output_bytes"] = 10

    with pytest.raises(XctxError, match="connector.max_output_bytes"):
        validate_loaded_store(store)


def test_config_validation_rejects_invalid_entrypoint_limits() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.config.validation import validate_loaded_store  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["entrypoint"]["timeout_seconds"] = 0

    with pytest.raises(XctxError, match="entrypoint.timeout_seconds"):
        validate_loaded_store(store)

    store = copy.deepcopy(load_store(root=ROOT))
    subdomain = store["agent_domains"]["stock_intelligence_hub"]["_subdomains"]["market_data_gateway"]
    subdomain["entrypoint"]["max_output_bytes"] = 10

    with pytest.raises(XctxError, match="entrypoint.max_output_bytes"):
        validate_loaded_store(store)


def test_duplicate_yaml_key_rejected_at_root(tmp_path) -> None:
    ensure_libs_path()
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.io.yaml_io import load_yaml  # noqa: PLC0415

    path = tmp_path / "duplicate-root.yaml"
    path.write_text("connector: first\nconnector: second\n", encoding="utf-8")

    with pytest.raises(XctxError, match="duplicate YAML key: connector"):
        load_yaml(path)


def test_duplicate_yaml_key_rejected_nested(tmp_path) -> None:
    ensure_libs_path()
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.io.yaml_io import load_yaml  # noqa: PLC0415

    path = tmp_path / "duplicate-nested.yaml"
    path.write_text("agent:\n  action: first\n  action: second\n", encoding="utf-8")

    with pytest.raises(XctxError, match="duplicate YAML key: action"):
        load_yaml(path)


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
