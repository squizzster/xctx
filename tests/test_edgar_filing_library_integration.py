from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework_helpers import run_runtime_json


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
    assert {item["action"] for item in live["planned_effects"]} == {
        "company_pack",
        "download_key_filings",
        "index_local_artifacts",
    }
    assert {item["id"] for item in live["discoverable_modes"]} >= {"list_artifacts"}


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
