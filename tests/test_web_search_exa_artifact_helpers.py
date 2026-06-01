from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework_helpers import run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(90)]


def _write_page_fixture(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "title": "Fetched page",
                        "url": "https://example.com/page",
                        "publishedDate": "2026-01-01",
                        "text": "Fetched page body for helper testing.",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _plan(args: list[str]) -> dict:
    rc, payload = run_runtime_json(["plan", *args])
    assert rc == 0, payload
    return payload["results"]


def _commit(plan_id: str) -> dict:
    rc, payload = run_runtime_json(["execute", plan_id, "--commit"])
    assert rc == 0, payload
    return payload["results"]


def test_web_artifact_observation_reports_json_shape_helpers(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture = _write_page_fixture(tmp_path / "page_fixture.json")

    plan = _plan(
        [
            "web_search::exa_search::fetch_page",
            "https://example.com/page",
            "--page-source",
            "fixture",
            "--page-fixture-path",
            str(fixture),
        ]
    )
    commit = _commit(plan["plan_id"])
    rc, observed_result = run_runtime_json(["observe", commit["result_id"]])
    assert rc == 0
    result_payload = observed_result["results"]["payload"]
    artifacts = {item["kind"]: item["id"] for item in result_payload["artifacts"]}

    rc, results_artifact = run_runtime_json(["observe", "web_search::exa_search", artifacts["results_json"]])
    assert rc == 0
    results_live = results_artifact["results"]["live_data"]
    assert results_live["artifact"]["kind"] == "results_json"
    assert results_live["content_helper"]["preview_cmd"].endswith("--web-preview-chars 1200")
    assert results_live["json_helper"]["root_type"] == "array"
    assert results_live["json_helper"]["root_length"] == 1
    assert results_live["json_helper"]["root_access_path"] == ".[0]"
    assert ".[0]" in results_live["json_helper"]["safe_jq_examples"]
    assert ".[0].text" in results_live["json_helper"]["safe_jq_examples"]
    assert results_live["json_helper"]["content_paths"][0] == {"path": ".[0].text", "chars": 37}

    rc, raw_artifact = run_runtime_json(["observe", "web_search::exa_search", artifacts["raw_json"]])
    assert rc == 0
    raw_live = raw_artifact["results"]["live_data"]
    assert raw_live["artifact"]["kind"] == "raw_json"
    assert raw_live["json_helper"]["root_type"] == "object"
    assert raw_live["json_helper"]["results_path"] == ".results"
    assert raw_live["json_helper"]["first_result_path"] == ".results[0]"
    assert ".results[0].text" in raw_live["json_helper"]["safe_jq_examples"]


def test_web_result_observation_reports_content_helper(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture = _write_page_fixture(tmp_path / "page_fixture.json")

    plan = _plan(
        [
            "web_search::exa_search::fetch_page",
            "https://example.com/page",
            "--page-source",
            "fixture",
            "--page-fixture-path",
            str(fixture),
        ]
    )
    commit = _commit(plan["plan_id"])
    rc, observed_result = run_runtime_json(["observe", commit["result_id"]])
    assert rc == 0
    web_result_id = observed_result["results"]["payload"]["results"][0]["id"]

    rc, observed_web_result = run_runtime_json(["observe", "web_search::exa_search", web_result_id])
    assert rc == 0
    web_live = observed_web_result["results"]["live_data"]
    assert web_live["content_helper"] == {
        "source": "result_raw_json",
        "content_chars": 37,
        "bounded_preview_flag": "--web-preview-chars N",
        "preview_cmd": f"./xctx observe web_search::exa_search {web_result_id} --web-preview-chars 1200",
    }

    rc, previewed_web_result = run_runtime_json(
        ["observe", "web_search::exa_search", web_result_id, "--web-preview-chars", "20"]
    )
    assert rc == 0
    preview = previewed_web_result["results"]["live_data"]["bounded_preview"]
    assert preview == {"chars_returned": 20, "truncated": True, "text": "Fetched page body fo"}


def test_exa_discovery_detail_levels_promote_full_projection(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))

    rc, basic = run_runtime_json(["discover", "web_search::exa_search"])
    assert rc == 0
    assert basic["results"]["live_data"]["projection"] == "compact"
    assert "artifact_kinds" not in basic["results"]["live_data"]

    rc, max_payload = run_runtime_json(["--max", "discover", "web_search::exa_search"])
    assert rc == 0
    assert max_payload["results"]["live_data"]["projection"] == "full"
    assert max_payload["results"]["live_data"]["artifact_kinds"] == [
        "raw_json",
        "results_json",
        "markdown",
        "manifest",
    ]
