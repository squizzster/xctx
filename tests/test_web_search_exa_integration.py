from __future__ import annotations

import json
import os
import time
from email.utils import formatdate
from pathlib import Path

import pytest

from framework_helpers import ensure_libs_path, run_runtime_json


ensure_libs_path()

from xctx_live.web_search_exa import (  # noqa: E402
    _atomic_write_json,
    _reserve_exa_slot,
    _retry_after_seconds,
    _retry_delay_seconds,
    _should_retry,
)


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(90)]


class _ResponseError(Exception):
    def __init__(self, message: str, status_code: int | None = None, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.response = type("Response", (), {})()
        self.response.status_code = status_code
        self.response.headers = {"Retry-After": retry_after} if retry_after is not None else {}


def _write_fixture(path: Path, *, title: str = "Example search result", url: str = "https://example.com/a") -> Path:
    path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "title": title,
                        "url": url,
                        "publishedDate": "2026-01-01",
                        "author": "Example Author",
                        "highlights": ["A compact highlight about Exa-backed xctx web search."],
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


def test_exa_discovery_starts_empty_and_redacts_identity(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("EXA_API_KEY", "fallback-secret")
    monkeypatch.setenv("XCTX_EXA_API_KEY", "scoped-secret")

    rc, payload = run_runtime_json(["discover", "web_search::exa_search"])

    assert rc == 0
    live = payload["results"]["live_data"]
    assert live["object_type"] == "web_search_exa_discovery"
    assert live["storage"]["engine"] == "sqlite"
    assert live["storage"]["registry_initialized"] is False
    assert live["local_availability"] == {"runs": 0, "results": 0, "artifacts": 0, "last_run_at": None}
    assert live["provider_readiness"]["identity"] == {
        "available": True,
        "source": "XCTX_EXA_API_KEY",
        "value_printed": False,
    }
    assert "scoped-secret" not in json.dumps(payload)
    assert [item["action"] for item in live["planned_effects"]] == ["search_fast", "search_deep", "fetch_page"]
    assert live["planned_effects"][0]["recommended"] is True
    assert live["planned_effects"][1]["run_cmd"].startswith(
        "./xctx plan web_search::exa_search::search_deep --deep-query"
    )
    assert {item["id"] for item in live["discoverable_modes"]} >= {"list_search_runs", "list_results"}


def test_live_search_plan_requires_identity_before_ledger(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("XCTX_EXA_API_KEY", raising=False)

    rc, payload = run_runtime_json(["plan", "web_search::exa_search::search_fast", "--query", "xctx web search"])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "live Exa search requires XCTX_EXA_API_KEY or EXA_API_KEY"
    assert "plan_id" not in json.dumps(payload)


def test_web_search_domain_surface_detail_levels_and_error_boundaries(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))

    rc, root = run_runtime_json(["discover"])
    assert rc == 0
    assert "web_search" in {item["id"] for item in root["results"]["agent_domains"]}

    rc, domain = run_runtime_json(["discover", "web_search"])
    assert rc == 0
    assert domain["domain_level"] == "agent_domain"
    assert domain["results"]["affordance_count"] == 5
    assert "domain_affordances" not in domain["results"]

    rc, domain_more = run_runtime_json(["--more", "discover", "web_search"])
    assert rc == 0
    affordances = domain_more["results"]["domain_affordances"]
    assert set(affordances) == {
        "fetch_web_page",
        "list_web_results",
        "list_web_search_runs",
        "search_web",
        "search_web_deep",
    }
    assert affordances["search_web"]["implemented_by"] == "web_search::exa_search::search_fast"

    rc, subdomain_max = run_runtime_json(["--max", "discover", "web_search::exa_search"])
    assert rc == 0
    assert set(subdomain_max["results"]["configured_actions"]) == {
        "discover",
        "fetch_page",
        "list_results",
        "list_search_runs",
        "observe",
        "search_deep",
        "search_fast",
    }

    rc, unscoped = run_runtime_json(["discover", "search_web"])
    assert rc == 1
    assert unscoped["error"] == "unscoped discovery target: search_web"
    assert unscoped["next_moves"] == [{"run_cmd": "./xctx discover web_search::search_web"}]

    rc, bad_action = run_runtime_json(["discover", "web_search::exa_search::nope"])
    assert rc == 1
    assert bad_action["error"] == "unknown action for web_search::exa_search: nope"

    rc, bad_observe = run_runtime_json(["observe", "web_search::exa_search", "nope"])
    assert rc == 1
    assert "observe target must be status" in bad_observe["error"]


def test_fixture_fast_search_plan_commit_lists_and_observes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture = _write_fixture(tmp_path / "exa_search_fixture.json")

    plan = _plan(
        [
            "web_search::exa_search::search_fast",
            "xctx search fixture",
            "--fast-source",
            "fixture",
            "--fixture-path",
            str(fixture),
        ]
    )
    assert plan["status"] == "planned_effect"
    assert plan["plan_id"].startswith("plan:sha256:")

    commit = _commit(plan["plan_id"])
    assert commit["status"] == "committed"
    assert commit["mutations_applied"] == 1

    rc, observed_result = run_runtime_json(["observe", commit["result_id"]])
    assert rc == 0
    result_payload = observed_result["results"]["payload"]
    assert result_payload["object_type"] == "web_search_exa_commit_result"
    assert result_payload["operation"] == "search_fast"
    assert result_payload["source"] == "fixture"
    assert result_payload["result_count"] == 1
    assert result_payload["search_run_ref"].startswith("search_run:")
    web_result_id = result_payload["results"][0]["id"]
    artifact_id = next(item["id"] for item in result_payload["artifacts"] if item["kind"] == "markdown")

    rc, listed = run_runtime_json(["discover", "web_search::exa_search::list_results", "--query", "Example"])
    assert rc == 0
    listed_live = listed["results"]["live_data"]
    assert listed_live["count"] == 1
    assert listed_live["results"][0]["id"] == web_result_id
    assert listed_live["results"][0]["observe_cmd"].endswith(web_result_id)

    rc, observed_run = run_runtime_json(
        ["observe", "web_search::exa_search", result_payload["search_run_ref"], "--web-preview-chars", "80"]
    )
    assert rc == 0
    run_live = observed_run["results"]["live_data"]
    assert run_live["object_type"] == "web_search_exa_observation"
    assert run_live["run"]["operation"] == "search_fast"
    assert run_live["bounded_preview"]["chars_returned"] == 80

    rc, observed_web_result = run_runtime_json(
        ["observe", "web_search::exa_search", web_result_id, "--web-preview-chars", "30"]
    )
    assert rc == 0
    web_live = observed_web_result["results"]["live_data"]
    assert web_live["result"]["title"] == "Example search result"
    assert web_live["bounded_preview"]["text"].startswith("A compact highlight")

    rc, observed_artifact = run_runtime_json(
        ["observe", "web_search::exa_search", artifact_id, "--web-preview-chars", "20"]
    )
    assert rc == 0
    artifact_live = observed_artifact["results"]["live_data"]
    assert artifact_live["artifact"]["kind"] == "markdown"
    assert artifact_live["bounded_preview"]["text"].startswith("# Exa search fast")


def test_deep_search_and_fetch_page_support_positional_fixture_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    search_fixture = _write_fixture(tmp_path / "deep_fixture.json", title="Deep result")
    page_fixture = _write_fixture(tmp_path / "page_fixture.json", title="Fetched page", url="https://example.com/page")

    deep = _plan(
        [
            "web_search::exa_search::search_deep",
            "deep fixture query",
            "--deep-source",
            "fixture",
            "--deep-fixture-path",
            str(search_fixture),
        ]
    )
    page = _plan(
        [
            "web_search::exa_search::fetch_page",
            "https://example.com/page",
            "--page-source",
            "fixture",
            "--page-fixture-path",
            str(page_fixture),
        ]
    )

    _commit(deep["plan_id"])
    _commit(page["plan_id"])

    rc, runs = run_runtime_json(["discover", "web_search::exa_search::list_search_runs", "--operation", "fetch_page"])
    assert rc == 0
    assert runs["results"]["live_data"]["count"] == 1
    assert runs["results"]["live_data"]["runs"][0]["url"] == "https://example.com/page"


def test_retry_after_backoff_timeout_and_atomic_write(tmp_path) -> None:
    numeric = _ResponseError("rate limited", 429, "2.5")
    assert _retry_after_seconds(numeric) == 2.5

    future = formatdate(time.time() + 5, usegmt=True)
    dated = _ResponseError("rate limited", 429, future)
    assert 0 < (_retry_after_seconds(dated) or 0) <= 6

    assert _should_retry(_ResponseError("server error", 503))
    assert _should_retry(TimeoutError("request timeout"))
    assert not _should_retry(_ResponseError("bad request", 400))
    assert _retry_delay_seconds(TimeoutError("request timeout"), attempt_index=0, jitter_func=lambda: 0.0) == 30.0

    target = tmp_path / "nested" / "artifact.json"
    _atomic_write_json(target, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_sqlite_rate_limiter_serializes_slots(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("EXA_SEARCH_QPS", "2")
    sleeps: list[float] = []

    first = _reserve_exa_slot(tmp_path, "search", now_func=lambda: 100.0, sleep_func=sleeps.append)
    second = _reserve_exa_slot(tmp_path, "search", now_func=lambda: 100.0, sleep_func=sleeps.append)

    assert first == 0
    assert second == 0.5
    assert sleeps == [0.5]


@pytest.mark.live_exa
def test_live_exa_fast_search_smoke(monkeypatch, tmp_path) -> None:
    if os.environ.get("XCTX_RUN_LIVE_EXA") != "1":
        pytest.skip("set XCTX_RUN_LIVE_EXA=1 to spend a live Exa request")
    if not (os.environ.get("XCTX_EXA_API_KEY") or os.environ.get("EXA_API_KEY")):
        pytest.skip("live Exa smoke requires XCTX_EXA_API_KEY or EXA_API_KEY")
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))

    plan = _plan(
        [
            "web_search::exa_search::search_fast",
            "--query",
            "xctx web search live smoke",
            "--num-results",
            "1",
        ]
    )
    commit = _commit(plan["plan_id"])
    rc, observed_result = run_runtime_json(["observe", commit["result_id"]])

    assert rc == 0
    result_payload = observed_result["results"]["payload"]
    assert result_payload["object_type"] == "web_search_exa_commit_result"
    assert result_payload["source"] == "live"
    assert result_payload["result_count"] >= 1
