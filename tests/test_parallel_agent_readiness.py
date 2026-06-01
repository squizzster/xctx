from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from framework_helpers import ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(90)]


def _write_exa_fixture(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "title": "Identical fixture result",
                        "url": "https://example.com/parallel",
                        "text": "identical artifact content",
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


def test_exa_artifact_registry_keeps_identical_artifacts_attached_to_each_run(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    fixture = _write_exa_fixture(tmp_path / "exa_fixture.json")
    run_refs: list[str] = []

    for index in range(2):
        plan = _plan(
            [
                "web_search::exa_search::search_fast",
                f"identical fixture {index}",
                "--fast-source",
                "fixture",
                "--fixture-path",
                str(fixture),
            ]
        )
        commit = _commit(plan["plan_id"])
        rc, observed = run_runtime_json(["observe", commit["result_id"]])
        assert rc == 0
        run_refs.append(observed["results"]["payload"]["search_run_ref"])

    for run_ref in run_refs:
        rc, observed_run = run_runtime_json(["observe", "web_search::exa_search", run_ref])
        assert rc == 0
        live = observed_run["results"]["live_data"]
        assert live["run"]["result_count"] == 1
        assert {artifact["kind"] for artifact in live["artifacts"]} == {
            "manifest",
            "markdown",
            "raw_json",
            "results_json",
        }

    rc, status = run_runtime_json(["observe", "web_search::exa_search", "status"])
    assert rc == 0
    stats = status["results"]["live_data"]["stats"]
    assert stats["run_count"] == 2
    assert stats["artifact_count"] == 8


def test_domain_sqlite_connections_use_parallel_agent_busy_timeout(monkeypatch, tmp_path) -> None:
    ensure_libs_path()
    from xctx_live.edgar_filing_library import _connect_rw as connect_edgar  # noqa: PLC0415
    from xctx_live.web_search_exa import _connect as connect_exa  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path / "runtime"))
    with connect_exa(tmp_path) as conn:
        exa_timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])
    with connect_edgar(tmp_path) as conn:
        edgar_timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])

    assert exa_timeout == 30000
    assert edgar_timeout == 30000
