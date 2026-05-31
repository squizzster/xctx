from __future__ import annotations

import json
import multiprocessing
import sqlite3
from pathlib import Path

import pytest

from framework_helpers import ensure_libs_path, run_runtime_json


ensure_libs_path()

from xctx_live.edgar_filing_library import (
    EDGAR_MIN_REQUEST_INTERVAL_SECONDS,
    _atomic_write_text,
    _atomic_write_with_path,
    _edgar_call,
    _edgar_note_retry_delay,
    _edgar_throttle,
    _heartbeat_summary,
    _reserve_edgar_slot,
    _retry_after_seconds,
    _retry_delay_seconds,
    _select_super_pack_candidates,
    _write_section_manifest,
)


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(90)]


ACCESSION = "0000320193-25-000079"


def _write_fixture(
    root: Path,
    *,
    include_ticker: bool = True,
    requested_identifier: str | None = None,
    include_pack: bool = False,
) -> Path:
    filing_dir = root / "0000320193" / "AAPL" / ACCESSION
    filing_dir.mkdir(parents=True)
    metadata = {
        "company": "Apple Inc.",
        "cik": "0000320193",
        "form": "10-K",
        "filing_date": "2025-10-31",
        "period_of_report": "2025-09-27",
        "accession": ACCESSION,
    }
    if include_ticker:
        metadata["ticker"] = "AAPL"
    if requested_identifier:
        metadata["requested_identifier"] = requested_identifier
    (filing_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (filing_dir / "filing.md").write_text("# Apple 10-K\n\nManagement discussion fixture.\n", encoding="utf-8")
    (filing_dir / "filing.txt").write_text("Apple 10-K plain text fixture.\n", encoding="utf-8")
    (filing_dir / "sections.txt").write_text("Item 1. Business\nItem 7. MD&A\n", encoding="utf-8")
    if include_pack:
        statements = filing_dir / "statements"
        statements.mkdir()
        (statements / "income_statement.csv").write_text(
            "concept,label,value\nus-gaap:NetIncomeLoss,Net income,100\n",
            encoding="utf-8",
        )
        (statements / "income_statement.json").write_text(
            json.dumps([{"concept": "us-gaap:NetIncomeLoss", "value": 100}], indent=2) + "\n",
            encoding="utf-8",
        )
        (statements / "manifest.json").write_text(
            json.dumps({"success": True, "files": ["income_statement.csv"]}, indent=2) + "\n",
            encoding="utf-8",
        )
        facts = filing_dir / "facts"
        facts.mkdir()
        (facts / "us-gaap_Assets.csv").write_text("concept,value\nus-gaap:Assets,500\n", encoding="utf-8")
        (facts / "us-gaap_Assets.json").write_text(
            json.dumps([{"concept": "us-gaap:Assets", "value": 500}], indent=2) + "\n",
            encoding="utf-8",
        )
        (facts / "manifest.json").write_text(
            json.dumps({"success": True, "files": ["us-gaap_Assets.csv"]}, indent=2) + "\n",
            encoding="utf-8",
        )
        metrics = filing_dir / "metrics"
        metrics.mkdir()
        (metrics / "metrics.csv").write_text("metric,value\nrevenue,200\n", encoding="utf-8")
        (metrics / "metrics.json").write_text(
            json.dumps([{"metric": "revenue", "value": 200}], indent=2) + "\n",
            encoding="utf-8",
        )
        (metrics / "manifest.json").write_text(
            json.dumps({"success": True, "files": ["metrics.csv"]}, indent=2) + "\n",
            encoding="utf-8",
        )
        (filing_dir / "company_pack_manifest.json").write_text(
            json.dumps(
                {
                    "success": True,
                    "statements": {"income_statement": "statements/income_statement.csv"},
                    "facts": {"us-gaap:Assets": "facts/us-gaap_Assets.csv"},
                    "metrics": {"metrics": "metrics/metrics.csv"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return root


def _plan(args: list[str]) -> dict:
    rc, payload = run_runtime_json(["plan", *args])
    assert rc == 0, payload
    return payload["results"]


def _commit(plan_id: str) -> dict:
    rc, payload = run_runtime_json(["execute", plan_id, "--commit"])
    assert rc == 0, payload
    return payload["results"]


def _parallel_reserve_edgar_slot(args: tuple[str, str, float]) -> float:
    root, scope, interval = args
    return _reserve_edgar_slot(
        Path(root),
        scope=scope,
        min_interval_seconds=interval,
        now_func=lambda: 100.0,
    )


def test_edgar_filing_library_discovery_starts_empty_and_plannable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("EDGAR_IDENTITY", raising=False)
    monkeypatch.delenv("XCTX_EDGAR_IDENTITY", raising=False)

    rc, payload = run_runtime_json(["discover", "stock_intelligence_hub::edgar_filing_library"])

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["object_type"] == "edgar_filing_library_discovery"
    assert live["storage"]["engine"] == "sqlite"
    assert live["storage"]["registry_initialized"] is False
    assert live["local_availability"]["available_filings"] == 0
    assert live["edgar_identity"] == {"available": False, "source": None, "value_printed": False}
    assert [item["action"] for item in live["planned_effects"]] == [
        "super_pack",
        "download_key_filings",
        "company_pack",
        "index_local_artifacts",
    ]
    assert live["planned_effects"][0]["recommended"] is True
    assert live["next_moves"][0]["run_cmd"] == (
        "./xctx plan stock_intelligence_hub::edgar_filing_library::super_pack --issuer AAPL"
    )
    assert {item["id"] for item in live["discoverable_modes"]} >= {"get_latest_filing", "list_artifacts"}


def test_empty_inventory_guides_to_super_pack_and_keeps_specific_paths_visible(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))

    rc, available = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::edgar_filing_library::list_available_filings",
            "--identifier",
            "MSFT",
        ]
    )
    assert rc == 0
    available_moves = available["results"]["live_data"]["next_moves"]
    assert available_moves[0]["run_cmd"] == (
        "./xctx plan stock_intelligence_hub::edgar_filing_library::super_pack --issuer MSFT"
    )
    assert available_moves[1]["run_cmd"].endswith("::index_local_artifacts --artifact-root <existing-edgar-artifact-root>")

    rc, artifacts = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::edgar_filing_library::list_artifacts",
            "--identifier",
            "MSFT",
            "--kind",
            "csv",
        ]
    )
    assert rc == 0
    artifact_moves = artifacts["results"]["live_data"]["next_moves"]
    assert artifact_moves[0]["run_cmd"] == (
        "./xctx plan stock_intelligence_hub::edgar_filing_library::super_pack --issuer MSFT"
    )
    assert artifact_moves[1]["run_cmd"] == (
        "./xctx plan stock_intelligence_hub::edgar_filing_library::company_pack --pack-identifier MSFT --pack-form 10-K"
    )
    assert artifact_moves[2]["run_cmd"].endswith("::index_local_artifacts --artifact-root <existing-edgar-artifact-root>")

    rc, observed = run_runtime_json(["observe", "stock_intelligence_hub::edgar_filing_library", "status"])
    assert rc == 0
    status_moves = observed["results"]["live_data"]["next_moves"]
    assert status_moves[0]["run_cmd"] == (
        "./xctx plan stock_intelligence_hub::edgar_filing_library::super_pack --issuer AAPL"
    )
    assert "list_available_filings" in status_moves[1]["run_cmd"]


def test_live_download_plan_requires_identity_before_ledger(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("EDGAR_IDENTITY", raising=False)
    monkeypatch.delenv("XCTX_EDGAR_IDENTITY", raising=False)

    rc, payload = run_runtime_json(
        [
            "plan",
            "stock_intelligence_hub::edgar_filing_library::download_key_filings",
            "--identifier",
            "AAPL",
            "--forms",
            "10-K",
        ]
    )

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "live EDGAR download requires XCTX_EDGAR_IDENTITY or EDGAR_IDENTITY"
    assert "plan_id" not in json.dumps(payload)


def test_edgar_identity_prefers_xctx_and_accepts_edgar_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("EDGAR_IDENTITY", "legacy@example.com Legacy Person")
    monkeypatch.setenv("XCTX_EDGAR_IDENTITY", "scoped@example.com Scoped Person")

    rc, discovered = run_runtime_json(["discover", "stock_intelligence_hub::edgar_filing_library"])

    assert rc == 0
    assert discovered["results"]["live_data"]["edgar_identity"] == {
        "available": True,
        "source": "XCTX_EDGAR_IDENTITY",
        "value_printed": False,
    }
    assert "Scoped Person" not in json.dumps(discovered)
    assert "Legacy Person" not in json.dumps(discovered)

    monkeypatch.delenv("XCTX_EDGAR_IDENTITY", raising=False)

    rc, planned = run_runtime_json(
        [
            "plan",
            "stock_intelligence_hub::edgar_filing_library::download_key_filings",
            "--identifier",
            "AAPL",
            "--forms",
            "10-K",
        ]
    )

    assert rc == 0
    assert planned["ok"] is True
    assert planned["results"]["plan_id"].startswith("plan:sha256:")


def test_index_local_artifacts_plan_commit_lists_and_observes_filings(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture_root = _write_fixture(tmp_path / "fixture_edgar_out")

    plan = _plan(
        [
            "stock_intelligence_hub::edgar_filing_library::index_local_artifacts",
            "--artifact-root",
            str(fixture_root),
        ]
    )
    commit = _commit(plan["plan_id"])
    assert commit["status"] == "committed"
    assert commit["mutations_applied"] == 1

    rc, observed_result = run_runtime_json(["observe", commit["result_id"]])
    assert rc == 0
    result_payload = observed_result["results"]["payload"]
    assert result_payload["object_type"] == "edgar_local_artifact_index_result"
    assert result_payload["indexed_count"] == 1
    assert result_payload["registry"]["available_filings"] == 1

    rc, available = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::edgar_filing_library::list_available_filings",
            "--identifier",
            "AAPL",
            "--form",
            "10-K",
        ]
    )
    assert rc == 0
    filings = available["results"]["live_data"]["filings"]
    assert len(filings) == 1
    assert filings[0]["id"] == f"filing:{ACCESSION}"
    assert filings[0]["observe_cmd"].endswith(f"filing:{ACCESSION}")

    rc, observed = run_runtime_json(
        ["observe", "stock_intelligence_hub::edgar_filing_library", f"filing:{ACCESSION}"]
    )
    assert rc == 0
    live = observed["results"]["live_data"]
    assert live["object_type"] == "edgar_filing_observation"
    assert live["form"] == "10-K"
    assert live["issuer"]["ticker"] == "AAPL"
    assert live["artifact_count"] >= 4
    assert "bounded_preview" not in live

    rc, preview = run_runtime_json(
        [
            "observe",
            "stock_intelligence_hub::edgar_filing_library",
            f"filing:{ACCESSION}",
            "--preview-chars",
            "20",
        ]
    )
    assert rc == 0
    preview_live = preview["results"]["live_data"]
    assert preview_live["bounded_preview"]["chars_returned"] == 20
    assert preview_live["bounded_preview"]["text"].startswith("# Apple 10-K")


def test_fixture_download_uses_planned_effect_and_updates_key_catalog(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture_root = _write_fixture(tmp_path / "fixture_edgar_out")

    plan = _plan(
        [
            "stock_intelligence_hub::edgar_filing_library::download_key_filings",
            "--identifier",
            "AAPL",
            "--forms",
            "10-K",
            "--source",
            "fixture",
            "--source-root",
            str(fixture_root),
        ]
    )
    commit = _commit(plan["plan_id"])
    rc, observed_result = run_runtime_json(["observe", commit["result_id"]])
    assert rc == 0
    result_payload = observed_result["results"]["payload"]
    assert result_payload["object_type"] == "edgar_key_filings_download_result"
    assert result_payload["source"] == "fixture"
    assert result_payload["indexed_count"] == 1

    rc, catalog = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::edgar_filing_library::list_key_filings",
            "--identifier",
            "AAPL",
        ]
    )
    assert rc == 0
    annual = next(group for group in catalog["results"]["live_data"]["groups"] if group["id"] == "annual_reports")
    ten_k = next(item for item in annual["forms"] if item["form"] == "10-K")
    assert ten_k["available_count"] == 1
    assert ten_k["latest_available"]["id"] == f"filing:{ACCESSION}"
    assert ten_k["plan_cmd"] == "./xctx plan stock_intelligence_hub::edgar_filing_library::super_pack --issuer AAPL"
    assert ten_k["specific_form_plan_cmd"] == (
        "./xctx plan stock_intelligence_hub::edgar_filing_library::download_key_filings --identifier AAPL --forms 10-K"
    )
    next_moves = catalog["results"]["live_data"]["next_moves"]
    assert next_moves[0]["run_cmd"] == ten_k["plan_cmd"]
    assert next_moves[2]["run_cmd"].endswith("::download_key_filings --identifier AAPL --forms critical")



def test_requested_identifier_backfills_live_ticker_filter(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture_root = _write_fixture(
        tmp_path / "live_style_edgar_out",
        include_ticker=False,
        requested_identifier="AAPL",
    )

    plan = _plan(
        [
            "stock_intelligence_hub::edgar_filing_library::index_local_artifacts",
            "--artifact-root",
            str(fixture_root),
        ]
    )
    _commit(plan["plan_id"])

    rc, available = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::edgar_filing_library::list_available_filings",
            "--identifier",
            "AAPL",
        ]
    )

    assert rc == 0
    filings = available["results"]["live_data"]["filings"]
    assert [item["id"] for item in filings] == [f"filing:{ACCESSION}"]
    assert filings[0]["ticker"] == "AAPL"


def test_csv_company_pack_artifacts_are_listed_and_observable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture_root = _write_fixture(tmp_path / "fixture_edgar_out", include_pack=True)

    plan = _plan(
        [
            "stock_intelligence_hub::edgar_filing_library::index_local_artifacts",
            "--artifact-root",
            str(fixture_root),
        ]
    )
    _commit(plan["plan_id"])

    rc, listed = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::edgar_filing_library::list_artifacts",
            "--identifier",
            "AAPL",
            "--kind",
            "csv",
        ]
    )
    assert rc == 0
    live = listed["results"]["live_data"]
    assert live["object_type"] == "edgar_artifact_file_list"
    artifacts = live["artifacts"]
    assert live["pagination"]["total_count"] == 3
    assert {Path(item["path"]).name for item in artifacts} == {
        "income_statement.csv",
        "metrics.csv",
        "us-gaap_Assets.csv",
    }

    income_statement = next(item for item in artifacts if Path(item["path"]).name == "income_statement.csv")
    rc, observed = run_runtime_json(
        [
            "observe",
            "stock_intelligence_hub::edgar_filing_library",
            income_statement["id"],
            "--preview-chars",
            "80",
        ]
    )
    assert rc == 0
    observed_live = observed["results"]["live_data"]
    assert observed_live["object_type"] == "edgar_artifact_file_observation"
    assert observed_live["artifact"]["kind"] == "csv"
    assert observed_live["csv_preview"]["columns"] == ["concept", "label", "value"]
    assert observed_live["csv_preview"]["rows"] == [["us-gaap:NetIncomeLoss", "Net income", "100"]]
    assert observed_live["bounded_preview"]["text"].startswith("concept,label,value")


def test_filing_artifact_paths_follow_detail_levels(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture_root = _write_fixture(tmp_path / "fixture_edgar_out", include_pack=True)

    plan = _plan(
        [
            "stock_intelligence_hub::edgar_filing_library::index_local_artifacts",
            "--artifact-root",
            str(fixture_root),
        ]
    )
    _commit(plan["plan_id"])

    base_args = [
        "discover",
        "stock_intelligence_hub::edgar_filing_library::list_artifacts",
        "--identifier",
        "AAPL",
        "--kind",
        "csv",
        "--limit",
        "1",
    ]
    rc, basic = run_runtime_json(base_args)
    assert rc == 0
    basic_artifact = basic["results"]["live_data"]["artifacts"][0]
    assert not Path(basic_artifact["path"]).is_absolute()
    assert "resolved_path" not in basic_artifact

    rc, max_payload = run_runtime_json(["--max", *base_args])
    assert rc == 0
    max_artifact = max_payload["results"]["live_data"]["artifacts"][0]
    assert not Path(max_artifact["path"]).is_absolute()
    assert Path(max_artifact["resolved_path"]).is_absolute()

    rc, observed_basic = run_runtime_json(
        [
            "observe",
            "stock_intelligence_hub::edgar_filing_library",
            basic_artifact["id"],
            "--preview-chars",
            "40",
        ]
    )
    assert rc == 0
    observed_basic_live = observed_basic["results"]["live_data"]
    assert "resolved_path" not in observed_basic_live["artifact"]
    assert "resolved_path" not in observed_basic_live["bounded_preview"]

    rc, observed_max = run_runtime_json(
        [
            "--max",
            "observe",
            "stock_intelligence_hub::edgar_filing_library",
            basic_artifact["id"],
            "--preview-chars",
            "40",
        ]
    )
    assert rc == 0
    observed_max_live = observed_max["results"]["live_data"]
    assert Path(observed_max_live["artifact"]["resolved_path"]).is_absolute()
    assert Path(observed_max_live["bounded_preview"]["resolved_path"]).is_absolute()


def test_company_pack_fixture_plan_indexes_csv_artifacts(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture_root = _write_fixture(tmp_path / "fixture_company_pack", include_pack=True)

    plan = _plan(
        [
            "stock_intelligence_hub::edgar_filing_library::company_pack",
            "--pack-identifier",
            "AAPL",
            "--pack-form",
            "10-K",
            "--pack-source",
            "fixture",
            "--pack-source-root",
            str(fixture_root),
        ]
    )
    commit = _commit(plan["plan_id"])
    assert commit["status"] == "committed"

    rc, observed_result = run_runtime_json(["observe", commit["result_id"]])
    assert rc == 0
    result_payload = observed_result["results"]["payload"]
    assert result_payload["object_type"] == "edgar_company_pack_result"
    assert result_payload["source"] == "fixture"
    assert result_payload["indexed_count"] == 1

    rc, listed = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::edgar_filing_library::list_artifacts",
            "--identifier",
            "AAPL",
            "--kind",
            "csv",
        ]
    )
    assert rc == 0
    assert listed["results"]["live_data"]["pagination"]["total_count"] == 3


def test_live_company_pack_plan_requires_identity_before_ledger(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("EDGAR_IDENTITY", raising=False)
    monkeypatch.delenv("XCTX_EDGAR_IDENTITY", raising=False)

    rc, payload = run_runtime_json(
        [
            "plan",
            "stock_intelligence_hub::edgar_filing_library::company_pack",
            "--pack-identifier",
            "AAPL",
            "--pack-form",
            "10-K",
        ]
    )

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "live EDGAR company pack requires XCTX_EDGAR_IDENTITY or EDGAR_IDENTITY"
    assert "plan_id" not in json.dumps(payload)


def test_section_manifest_splits_company_pack_markdown(tmp_path) -> None:
    artifact_dir = tmp_path / "artifact"
    filing_md = artifact_dir / "filing.md"
    filing_md.parent.mkdir(parents=True)
    filing_md.write_text(
        "\n".join(
            [
                "ITEM 1. Business",
                "business text " * 80,
                "ITEM 1A. Risk Factors",
                "risk text " * 80,
                "ITEM 7. Management's Discussion and Analysis",
                "mda text " * 80,
            ]
        ),
        encoding="utf-8",
    )

    manifest, warnings = _write_section_manifest(artifact_dir, filing_md, ["1", "1A", "7", "8"])

    assert manifest["success"] is True
    assert manifest["partial_success"] is True
    assert manifest["missing_items"] == ["8"]
    assert warnings == []
    assert (artifact_dir / "sections" / "item_1.md").exists()
    assert (artifact_dir / "sections" / "item_1a.md").exists()
    assert (artifact_dir / "sections" / "item_7.md").exists()
    assert (artifact_dir / "sections" / "index.json").exists()
    assert (artifact_dir / "sections" / "manifest.json").exists()


class _FakeFiling:
    def __init__(self, accession: str, form: str) -> None:
        self.accession = accession
        self.form = form


class _FakeFilingList:
    def __init__(self, rows: list[_FakeFiling] | Exception | None) -> None:
        self.rows = rows

    def latest(self, limit: int):
        if isinstance(self.rows, Exception):
            raise self.rows
        return list(self.rows or [])[:limit]


class _FakeCompany:
    def __init__(self, by_form: dict[str, list[_FakeFiling] | Exception | None]) -> None:
        self.by_form = by_form

    def get_filings(self, *, form: str, amendments: bool = True) -> _FakeFilingList:
        assert amendments is True
        return _FakeFilingList(self.by_form.get(form, []))


def test_super_pack_selection_chooses_foreign_annual_quarterly_and_updates() -> None:
    events: list[dict] = []
    company = _FakeCompany(
        {
            "10-K": ValueError("No filings found for form"),
            "20-F": [_FakeFiling("annual-20f", "20-F")],
            "10-Q": [_FakeFiling("quarter-10q", "10-Q")],
            "8-K": [_FakeFiling("update-8k", "8-K")],
            "6-K": [_FakeFiling("update-6k", "6-K")],
        }
    )

    selection = _select_super_pack_candidates(
        company,
        annual_forms=["10-K", "20-F", "40-F"],
        quarterly_forms=["10-Q"],
        update_forms=["8-K", "6-K"],
        update_limit=1,
        progress_events=events,
    )

    selected = [(item["role"], item["form"], item["filings"][0].accession) for item in selection["selections"]]
    assert selected == [
        ("latest_annual", "20-F", "annual-20f"),
        ("latest_quarterly", "10-Q", "quarter-10q"),
        ("latest_update", "8-K", "update-8k"),
        ("latest_update", "6-K", "update-6k"),
    ]
    assert selection["unavailable"][0]["status"] == "not_available"
    assert [event["event"] for event in events].count("probe_start") == 5
    assert [event["event"] for event in events].count("probe_done") == 5


def test_super_pack_selection_matrix_exercises_many_issuer_shapes() -> None:
    reports = []
    for index in range(40):
        annual_form = ["10-K", "20-F", "40-F"][index % 3]
        by_form: dict[str, list[_FakeFiling] | Exception | None] = {
            "10-K": [] if annual_form != "10-K" else [_FakeFiling(f"acc-{index}-10k", "10-K")],
            "20-F": [] if annual_form != "20-F" else [_FakeFiling(f"acc-{index}-20f", "20-F")],
            "40-F": [] if annual_form != "40-F" else [_FakeFiling(f"acc-{index}-40f", "40-F")],
            "10-Q": [] if index % 5 == 0 else [_FakeFiling(f"acc-{index}-10q", "10-Q")],
            "8-K": [] if index % 4 == 0 else [_FakeFiling(f"acc-{index}-8k", "8-K")],
            "6-K": [] if index % 6 else [_FakeFiling(f"acc-{index}-6k", "6-K")],
        }
        events: list[dict] = []
        selection = _select_super_pack_candidates(
            _FakeCompany(by_form),
            annual_forms=["10-K", "20-F", "40-F"],
            quarterly_forms=["10-Q"],
            update_forms=["8-K", "6-K"],
            update_limit=1,
            progress_events=events,
        )
        reports.append(
            {
                "roles": [item["role"] for item in selection["selections"]],
                "forms": [item["form"] for item in selection["selections"]],
                "events": events,
            }
        )

    assert len(reports) == 40
    assert all("latest_annual" in report["roles"] for report in reports)
    assert sum("latest_quarterly" in report["roles"] for report in reports) == 32
    assert sum("latest_update" in report["roles"] for report in reports) >= 33
    assert all(any(event["event"] == "probe_start" for event in report["events"]) for report in reports)


def test_get_latest_filing_returns_latest_local_match(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture_root = _write_fixture(tmp_path / "fixture_latest", include_pack=True)

    plan = _plan(
        [
            "stock_intelligence_hub::edgar_filing_library::index_local_artifacts",
            "--artifact-root",
            str(fixture_root),
        ]
    )
    _commit(plan["plan_id"])

    rc, latest = run_runtime_json(
        [
            "discover",
            "stock_intelligence_hub::edgar_filing_library::get_latest_filing",
            "--identifier",
            "AAPL",
            "--form",
            "10-K",
        ]
    )

    assert rc == 0
    live = latest["results"]["live_data"]
    assert live["object_type"] == "edgar_latest_filing_lookup"
    assert live["found"] is True
    assert live["latest"]["id"] == f"filing:{ACCESSION}"
    assert live["latest"]["observe_cmd"].endswith(f"filing:{ACCESSION}")


def test_super_pack_fixture_plan_indexes_artifacts(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture_root = _write_fixture(tmp_path / "fixture_super_pack", include_pack=True)

    plan = _plan(
        [
            "stock_intelligence_hub::edgar_filing_library::super_pack",
            "--issuer",
            "AAPL",
            "--super-source",
            "fixture",
            "--super-source-root",
            str(fixture_root),
        ]
    )
    assert plan["status"] == "planned_effect"
    assert plan["plan_id"].startswith("plan:sha256:")
    commit = _commit(plan["plan_id"])

    rc, observed_result = run_runtime_json(["observe", commit["result_id"]])
    assert rc == 0
    result_payload = observed_result["results"]["payload"]
    assert result_payload["object_type"] == "edgar_super_pack_result"
    assert result_payload["source"] == "fixture"
    assert result_payload["indexed_count"] == 1
    assert result_payload["selection_strategy"]["annual_forms"] == ["10-K", "20-F", "40-F"]


def test_super_pack_accepts_positional_issuer_for_agent_helper(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture_root = _write_fixture(tmp_path / "fixture_super_pack_positional", include_pack=True)

    plan = _plan(
        [
            "stock_intelligence_hub::filing_super_pack",
            "AAPL",
            "--super-source",
            "fixture",
            "--super-source-root",
            str(fixture_root),
        ]
    )
    assert "for AAPL" in plan["description_of_what_will_happen"]

    commit = _commit(plan["plan_id"])
    rc, observed_result = run_runtime_json(["observe", commit["result_id"]])

    assert rc == 0
    result_payload = observed_result["results"]["payload"]
    assert result_payload["object_type"] == "edgar_super_pack_result"
    assert result_payload["identifier"] == "AAPL"
    assert result_payload["indexed_count"] == 1


def test_super_pack_rejects_ambiguous_positional_and_named_issuer(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))

    rc, payload = run_runtime_json(
        [
            "plan",
            "stock_intelligence_hub::filing_super_pack",
            "AAPL",
            "--issuer",
            "MSFT",
        ]
    )

    assert rc == 1
    assert payload["ok"] is False
    assert "provide either positional argument 1 or --issuer" in payload["error"]


def test_atomic_text_write_replaces_complete_file(tmp_path) -> None:
    artifact = tmp_path / "artifact.md"
    artifact.write_text("old complete artifact", encoding="utf-8")

    _atomic_write_text(artifact, "new complete artifact")

    assert artifact.read_text(encoding="utf-8") == "new complete artifact"
    assert not list(tmp_path.glob(".artifact.md.*.tmp"))


def test_atomic_path_writer_preserves_existing_file_on_failure(tmp_path) -> None:
    artifact = tmp_path / "facts.csv"
    artifact.write_text("old,complete\n", encoding="utf-8")

    def failing_writer(path: Path) -> None:
        path.write_text("partial\n", encoding="utf-8")
        raise RuntimeError("writer crashed")

    with pytest.raises(RuntimeError, match="writer crashed"):
        _atomic_write_with_path(artifact, failing_writer)

    assert artifact.read_text(encoding="utf-8") == "old,complete\n"
    assert not list(tmp_path.glob(".facts.csv.*.tmp"))


def test_edgar_throttle_uses_sqlite_file_locked_limiter(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("XCTX_RUNTIME_DIR", raising=False)
    current = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current[0] += seconds

    _edgar_throttle(
        tmp_path,
        scope="unit_sec",
        min_interval_seconds=1.0,
        sleep_func=sleep,
        now_func=lambda: current[0],
    )
    _edgar_throttle(
        tmp_path,
        scope="unit_sec",
        min_interval_seconds=1.0,
        sleep_func=sleep,
        now_func=lambda: current[0],
    )

    db_path = (
        tmp_path
        / ".xctx_runtime"
        / "stock_intelligence_hub"
        / "edgar_filing_library"
        / "sec_rate_limits.sqlite"
    )
    assert db_path.exists()
    assert sleeps == [1.0]
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT scope, last_request_at, next_available_at, cooldown_until, min_interval_seconds
            FROM rate_limit_state
            WHERE scope = ?
            """,
            ("unit_sec",),
        ).fetchone()
    assert row == ("unit_sec", 101.0, 102.0, 0.0, 1.0)


def test_edgar_default_rate_limit_is_conservative() -> None:
    assert EDGAR_MIN_REQUEST_INTERVAL_SECONDS >= 0.5


def test_edgar_queue_wait_emits_compact_heartbeat(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("XCTX_RUNTIME_DIR", raising=False)
    current = [100.0]
    sleeps: list[float] = []
    events: list[dict] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current[0] += seconds

    _edgar_throttle(
        tmp_path,
        scope="queue_sec",
        min_interval_seconds=1.0,
        sleep_func=sleep,
        now_func=lambda: current[0],
        progress_events=events,
        label="get_filings.latest:very-long-label-" + ("x" * 100),
    )
    _edgar_throttle(
        tmp_path,
        scope="queue_sec",
        min_interval_seconds=1.0,
        sleep_func=sleep,
        now_func=lambda: current[0],
        progress_events=events,
        label="get_filings.latest:very-long-label-" + ("x" * 100),
    )

    heartbeat = next(event for event in events if event.get("phase") == "sec_queue_wait")
    assert sleeps == [1.0]
    assert heartbeat["event"] == "heartbeat"
    assert heartbeat["scope"] == "queue_sec"
    assert heartbeat["delay_seconds"] == 1.0
    assert len(heartbeat["label"]) <= 80


def test_edgar_rate_limiter_queues_parallel_processes(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("XCTX_RUNTIME_DIR", raising=False)
    interval = 0.01
    agent_count = 30

    with multiprocessing.get_context("fork").Pool(processes=10) as pool:
        waits = pool.map(
            _parallel_reserve_edgar_slot,
            [(str(tmp_path), "parallel_sec", interval)] * agent_count,
        )

    sorted_waits = sorted(waits)
    assert sorted_waits == pytest.approx([index * interval for index in range(agent_count)])
    db_path = (
        tmp_path
        / ".xctx_runtime"
        / "stock_intelligence_hub"
        / "edgar_filing_library"
        / "sec_rate_limits.sqlite"
    )
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT last_request_at, next_available_at
            FROM rate_limit_state
            WHERE scope = 'parallel_sec'
            """
        ).fetchone()
    assert row == pytest.approx((100.0 + ((agent_count - 1) * interval), 100.0 + (agent_count * interval)))


def test_edgar_throttle_rechecks_cooldown_after_reserved_wait(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("XCTX_RUNTIME_DIR", raising=False)
    scope = "cooldown_recheck_sec"
    current = [100.0]
    sleeps: list[float] = []
    events: list[dict] = []

    _reserve_edgar_slot(tmp_path, scope=scope, min_interval_seconds=10.0, now_func=lambda: 100.0)

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:
            _edgar_note_retry_delay(tmp_path, 20.0, scope=scope, now_func=lambda: 100.0)
        current[0] += seconds

    _edgar_throttle(
        tmp_path,
        scope=scope,
        min_interval_seconds=10.0,
        sleep_func=sleep,
        now_func=lambda: current[0],
        progress_events=events,
        label="filing.markdown",
    )

    assert sleeps == [10.0, 10.0]
    assert [event["phase"] for event in events if event["event"] == "heartbeat"] == [
        "sec_queue_wait",
        "sec_cooldown_wait",
    ]


def test_edgar_shared_cooldown_delays_later_reservations(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("XCTX_RUNTIME_DIR", raising=False)

    _edgar_note_retry_delay(
        tmp_path,
        5.0,
        scope="cooldown_sec",
        now_func=lambda: 100.0,
    )
    wait = _reserve_edgar_slot(
        tmp_path,
        scope="cooldown_sec",
        min_interval_seconds=1.0,
        now_func=lambda: 101.0,
    )

    db_path = (
        tmp_path
        / ".xctx_runtime"
        / "stock_intelligence_hub"
        / "edgar_filing_library"
        / "sec_rate_limits.sqlite"
    )
    assert wait == 4.0
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT last_request_at, next_available_at, cooldown_until
            FROM rate_limit_state
            WHERE scope = 'cooldown_sec'
            """
        ).fetchone()
    assert row == (105.0, 106.0, 105.0)


def test_edgar_shared_cooldown_never_shortens_existing_cooldown(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("XCTX_RUNTIME_DIR", raising=False)

    _edgar_note_retry_delay(tmp_path, 10.0, scope="cooldown_sec", now_func=lambda: 100.0)
    _edgar_note_retry_delay(tmp_path, 2.0, scope="cooldown_sec", now_func=lambda: 101.0)

    db_path = (
        tmp_path
        / ".xctx_runtime"
        / "stock_intelligence_hub"
        / "edgar_filing_library"
        / "sec_rate_limits.sqlite"
    )
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT cooldown_until FROM rate_limit_state WHERE scope = 'cooldown_sec'"
        ).fetchone()
    assert row == (110.0,)


def test_edgar_retry_after_sets_shared_sqlite_cooldown(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("XCTX_RUNTIME_DIR", raising=False)
    current = [100.0]
    sleeps: list[float] = []
    calls = 0

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current[0] += seconds

    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _RetryableHttpError(429, {"Retry-After": "2"})
        return "ok"

    result = _edgar_call(
        tmp_path,
        "unit_retry_shared_cooldown",
        flaky,
        max_attempts=2,
        min_interval_seconds=1.0,
        sleep_func=sleep,
        random_func=lambda: 0,
        now_func=lambda: current[0],
    )

    db_path = (
        tmp_path
        / ".xctx_runtime"
        / "stock_intelligence_hub"
        / "edgar_filing_library"
        / "sec_rate_limits.sqlite"
    )
    assert result == "ok"
    assert calls == 2
    assert sleeps == [2.0]
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT last_request_at, next_available_at, cooldown_until
            FROM rate_limit_state
            WHERE scope = 'sec_edgar'
            """
        ).fetchone()
    assert row == (102.0, 103.0, 102.0)


def test_retry_after_http_date_is_parsed_relative_to_current_time() -> None:
    exc = _RetryableHttpError(429, {"Retry-After": "Thu, 01 Jan 1970 00:01:40 GMT"})

    assert _retry_after_seconds(exc, now=lambda: 90.0) == 10.0
    assert _retry_delay_seconds(0, exc, random_func=lambda: 0.5, now_func=lambda: 90.0) == 10.0


def test_retry_after_is_capped_to_conservative_maximum() -> None:
    exc = _RetryableHttpError(429, {"Retry-After": "120"})

    assert _retry_after_seconds(exc) == 30.0
    assert _retry_delay_seconds(0, exc, random_func=lambda: 0) == 30.0


def test_timeout_retries_after_30_seconds_with_compact_heartbeat(tmp_path) -> None:
    calls = 0
    sleeps: list[float] = []
    events: list[dict] = []

    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("read timed out")
        return "ok"

    result = _edgar_call(
        tmp_path,
        "filing.markdown",
        flaky,
        max_attempts=2,
        min_interval_seconds=0,
        sleep_func=sleeps.append,
        random_func=lambda: 0,
        progress_events=events,
    )

    assert result == "ok"
    assert calls == 2
    assert sleeps == [30.0]
    assert len(events) == 1
    heartbeat = events[0]
    assert heartbeat["event"] == "heartbeat"
    assert heartbeat["phase"] == "sec_retry_wait"
    assert heartbeat["label"] == "filing.markdown"
    assert heartbeat["scope"] == "sec_edgar"
    assert heartbeat["delay_seconds"] == 30.0
    assert heartbeat["attempt"] == 1
    assert heartbeat["reason"] == "timeout"


def test_heartbeat_summary_is_compact_and_counts_retry_queue_and_cooldown() -> None:
    events = [
        {"event": "probe_start", "form": "10-K"},
        {"event": "heartbeat", "phase": "sec_queue_wait", "label": "Company:AAPL", "scope": "sec_edgar", "delay_seconds": 0.5},
        {
            "event": "heartbeat",
            "phase": "sec_retry_wait",
            "label": "filing.markdown",
            "scope": "sec_edgar",
            "delay_seconds": 30.0,
            "attempt": 1,
            "reason": "timeout",
            "verbose": "not included",
        },
        {
            "event": "heartbeat",
            "phase": "sec_cooldown_wait",
            "label": "filing.text",
            "scope": "sec_edgar",
            "delay_seconds": 12.0,
        },
    ]

    summary = _heartbeat_summary(events)

    assert summary == {
        "heartbeat_count": 3,
        "retry_wait_count": 1,
        "queue_wait_count": 1,
        "cooldown_wait_count": 1,
        "last": {
            "phase": "sec_cooldown_wait",
            "label": "filing.text",
            "scope": "sec_edgar",
            "delay_seconds": 12.0,
        },
    }


class _RetryResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


class _RetryableHttpError(RuntimeError):
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        super().__init__(f"HTTP {status_code}")
        self.response = _RetryResponse(status_code, headers)


def test_edgar_call_retries_429_with_retry_after(tmp_path) -> None:
    calls = 0
    sleeps: list[float] = []

    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _RetryableHttpError(429, {"Retry-After": "2"})
        return "ok"

    result = _edgar_call(
        tmp_path,
        "unit_retry",
        flaky,
        max_attempts=2,
        min_interval_seconds=0,
        sleep_func=sleeps.append,
        random_func=lambda: 0,
    )

    assert result == "ok"
    assert calls == 2
    assert sleeps == [2.0]


def test_edgar_call_retries_5xx_with_exponential_jitter(tmp_path) -> None:
    calls = 0
    sleeps: list[float] = []

    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _RetryableHttpError(503)
        return "ok"

    result = _edgar_call(
        tmp_path,
        "unit_5xx_retry",
        flaky,
        max_attempts=3,
        min_interval_seconds=0,
        sleep_func=sleeps.append,
        random_func=lambda: 0.5,
    )

    assert result == "ok"
    assert calls == 3
    assert sleeps == [1.125, 2.0]


def test_edgar_call_does_not_retry_non_retryable_errors(tmp_path) -> None:
    calls = 0

    def fail() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("No filings found")

    with pytest.raises(ValueError, match="No filings found"):
        _edgar_call(tmp_path, "unit_no_retry", fail, max_attempts=4, min_interval_seconds=0)

    assert calls == 1


def test_edgar_call_exhausts_retryable_errors_at_attempt_limit(tmp_path) -> None:
    calls = 0
    sleeps: list[float] = []

    def fail() -> None:
        nonlocal calls
        calls += 1
        raise _RetryableHttpError(503)

    with pytest.raises(_RetryableHttpError, match="HTTP 503"):
        _edgar_call(
            tmp_path,
            "unit_retry_exhausted",
            fail,
            max_attempts=2,
            min_interval_seconds=0,
            sleep_func=sleeps.append,
            random_func=lambda: 0,
        )

    assert calls == 2
    assert sleeps == [0.75]


def test_live_super_pack_plan_requires_identity_before_ledger(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("EDGAR_IDENTITY", raising=False)
    monkeypatch.delenv("XCTX_EDGAR_IDENTITY", raising=False)

    rc, payload = run_runtime_json(
        [
            "plan",
            "stock_intelligence_hub::edgar_filing_library::super_pack",
            "--issuer",
            "AAPL",
        ]
    )

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "live EDGAR super pack requires XCTX_EDGAR_IDENTITY or EDGAR_IDENTITY"
    assert "plan_id" not in json.dumps(payload)
