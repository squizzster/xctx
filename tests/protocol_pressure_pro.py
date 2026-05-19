#!/usr/bin/env python3
"""PRO pressure checks for xctx v4.2 protocol operability.

This script tests the protocol matrix in-process for speed and stability, then
runs a small real-CLI probe to verify the packaged launcher and persisted plan
ledger behave across separate processes.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / "libs"
XCTX = ROOT / "xctx"
if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from xctx.process.runtime import main as xctx_main  # noqa: E402


def run_engine(args: Iterable[str], code: int = 0) -> dict:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = xctx_main(["--json", *list(args)], root=ROOT)
    assert rc == code, f"args={list(args)} rc={rc}\nSTDOUT={out.getvalue()}\nSTDERR={err.getvalue()}"
    assert err.getvalue() == "", err.getvalue()
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1, out.getvalue()
    return json.loads(lines[0])


def run_cli(args: Iterable[str], code: int = 0) -> dict:
    proc = subprocess.run(
        [str(XCTX), "--json", *list(args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == code, f"args={list(args)} rc={proc.returncode}\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    assert proc.stderr == "", proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, proc.stdout
    return json.loads(lines[0])


def assert_cmd(payload: dict, *, ok: bool = True, record_type: str | None = None, level: str | None = None) -> None:
    assert payload["ok"] is ok, payload
    if record_type:
        assert payload["record_type"] == record_type, payload
    if level:
        assert payload["domain_level"] == level, payload


def assert_root_surface_clean(payload: object) -> None:
    text = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "--bars",
        "--calendar-days",
        "configured_options",
        "root_affordances",
        "search_entity_instrument",
        "search_market_series",
        "latest_price",
        "latest-price",
    ):
        assert forbidden not in text, forbidden


def main() -> int:
    shutil.rmtree(ROOT / ".xctx_runtime", ignore_errors=True)

    print("[pressure] root/universe command surface", flush=True)
    universe = run_engine([])
    assert_cmd(universe, record_type="discovery", level="universe")
    surface = universe["results"]["command_surface"]
    assert set(surface["xctx"]) == {"discover", "observe", "plan", "execute", "audit", "repair"}
    assert set(surface["xctx_other"]) == {"other"}
    assert surface["aliases"] == {"discover": ["discovery"]}
    assert "identify" not in surface["xctx"] and "write" not in surface["xctx"] and "status" not in surface["xctx"]
    assert_root_surface_clean(universe)
    assert_root_surface_clean(run_engine(["help"]))
    assert_root_surface_clean(run_engine(["--version"]))

    root = run_engine(["discover"])
    alias_root = run_engine(["discovery"])
    assert_cmd(root, record_type="discovery", level="root")
    assert_cmd(alias_root, record_type="discovery", level="root")
    assert_root_surface_clean(root)
    assert_root_surface_clean(alias_root)
    assert "configured_options" not in root["results"]
    assert "root_affordances" not in root["results"]
    assert root["results"]["next_moves"] == ["./xctx discover stock_intelligence_hub::", "./xctx audit root"]
    for core_rel in (
        "libs/xctx/process/parser.py",
        "libs/xctx/commands/observe.py",
        "libs/xctx/domain/agent_domains.py",
        "libs/xctx/commands/discover.py",
        "libs/xctx/domain/identity.py",
        "libs/xctx/commands/identify.py",
    ):
        text = (ROOT / core_rel).read_text(encoding="utf-8")
        for forbidden_literal in ("--bars", "--calendar-days", "search_entity_instrument", "latest_price", "latest-price", "ticker", "symbol"):
            assert forbidden_literal not in text, (core_rel, forbidden_literal)

    print("[pressure] domain/subdomain discovery", flush=True)
    domain = run_engine(["discover", "stock_intelligence_hub::"])
    assert_cmd(domain, record_type="discovery", level="agent_domain")
    subdomains = {item["id"]: item for item in domain["results"]["agent_subdomains"]}
    assert subdomains["market_data_gateway"]["status"] == "online"
    assert subdomains["equity_filing"]["status"] == "online"
    assert subdomains["fundamentals_gateway"]["terminal_reason"] == "down_for_maintenance"
    assert "latest_price" in domain["results"]["domain_affordances"]
    assert "search_filing_form" in domain["results"]["domain_affordances"]

    macro = run_engine(["discover", "macro_intelligence_hub::"])
    assert macro["results"]["status"] == "offline"
    assert macro["results"]["repair_cmd"] == "./xctx repair offline:macro_intelligence_hub"
    crypto = run_engine(["discover", "crypto_intelligence_hub::"])
    assert crypto["results"]["status"] == "down_for_maintenance"
    assert crypto["results"]["repair_path"] is None

    filings = run_engine(["discover", "stock_intelligence_hub::equity_filing"])
    assert filings["results"]["live_data"]["stats"]["total_lookup_filings"] == 412
    market = run_engine(["discover", "stock_intelligence_hub::market_data_gateway"])
    assert market["results"]["live_data"]["stats"]["canonical_instruments"] >= 100
    configured_observe_options = market["results"]["configured_options"]["observe"]
    assert [item["flags"][0] for item in configured_observe_options] == ["--bars", "--calendar-days"]
    assert configured_observe_options[0]["source"]["kind"] == "agent_subdomain_action"
    sample_series_ids = [item["market_series_id"] for item in market["results"]["live_data"]["sample_market_series"]]
    assert len(sample_series_ids) == len(set(sample_series_ids)), sample_series_ids

    print("[pressure] scoped affordance routing", flush=True)
    invalid_unscoped = run_engine(["discover", "search_filing_family", "annual"], code=1)
    assert_cmd(invalid_unscoped, ok=False, record_type="error")
    assert "./xctx discover stock_intelligence_hub::search_filing_family" in invalid_unscoped["error"]

    family = run_engine(["discover", "stock_intelligence_hub::search_filing_family", "annual"])
    assert any(item["id"] == "family:ANNUAL_REPORT" for item in family["results"]["live_data"]["matches"])
    priority = run_engine(["stock_intelligence_hub::search_priority_bucket", "critical"])
    assert priority["results"]["agent_subdomain"] == "equity_filing"
    assert priority["results"]["live_data"]["matches"][0]["id"] == "priority:critical_always"

    print("[pressure] market identity search", flush=True)
    apple = run_engine(["discover", "stock_intelligence_hub::market_data_gateway", "search_entity_instrument", "Apple"])
    live = apple["results"]["live_data"]
    assert live["matches_returned"] == 1
    assert live["matches"][0]["instrument_id"] == "instrument:aapl"
    assert "related_market_series" not in live
    assert any(move["run_cmd"].endswith("search_market_series AAPL") for move in live["matches"][0]["next_moves"])
    name_shortcut = run_engine(["discover", "--name", "Apple"], code=1)
    assert_cmd(name_shortcut, ok=False, record_type="error")
    assert "use a scoped discovery action" in name_shortcut["error"]
    apple_punct = run_engine(["discover", "stock_intelligence_hub::market_data_gateway", "search_entity_instrument", "Apple, Inc."])
    assert apple_punct["results"]["live_data"]["matches"][0]["resolver_match"]["reason"] == "normalized_name_exact"
    apple_cik = run_engine(["discover", "stock_intelligence_hub::search_entity_instrument", "issuer:cik:0000320193"])
    assert apple_cik["results"]["live_data"]["matches"][0]["resolver_match"]["reason"] == "exact_cik"
    fb = run_engine(["discover", "stock_intelligence_hub::search_entity_instrument", "FB"])
    assert fb["results"]["live_data"]["matches_returned"] == 1
    assert fb["results"]["live_data"]["matches"][0]["ticker"] == "META"

    ticker_a = run_engine(["discover", "stock_intelligence_hub::market_data_gateway", "search_entity_instrument", "A"])
    live_a = ticker_a["results"]["live_data"]
    assert live_a["total_matches"] >= 50
    assert live_a["matches_returned"] == 10
    assert live_a["matches"][0]["ticker"] == "A"
    assert live_a["matches"][0]["instrument_id"] == "instrument:a"

    series = run_engine(["discover", "stock_intelligence_hub::search_market_series", "AAPL"])
    assert series["results"]["live_data"]["matches"][0]["market_series_id"] == "market_series:aapl:daily"
    series_by_cik = run_engine(["discover", "stock_intelligence_hub::search_market_series", "320193"])
    assert series_by_cik["results"]["live_data"]["matches"][0]["market_series_id"] == "market_series:aapl:daily"
    latest = run_engine(["discover", "stock_intelligence_hub::latest_price", "AAPL"])
    assert latest["results"]["live_data"]["latest_available_price"]["is_live_quote"] is False
    assert latest["results"]["live_data"]["latest_available_price"]["price"] == latest["results"]["live_data"]["latest_available_price"]["close"]
    broad_series = run_engine(["discover", "stock_intelligence_hub::market_data_gateway", "search_market_series", "A"])
    broad_ids = [item["market_series_id"] for item in broad_series["results"]["live_data"]["matches"]]
    assert len(broad_ids) == len(set(broad_ids)), broad_ids

    print("[pressure] observe/audit/repair", flush=True)
    observed = run_engine(["observe", "instrument:aapl"])
    assert_cmd(observed, record_type="observation", level="agent_subdomain")
    assert observed["results"]["live_data"]["instrument_id"] == "instrument:aapl"
    assert observed["results"]["live_data"]["latest_available_price"]["is_live_quote"] is False
    observed_former = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "FB"])
    assert observed_former["results"]["live_data"]["ticker"] == "META"
    assert observed_former["results"]["live_data"]["market_series_available"] is False
    observed_series = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "market_series:a:daily"])
    series_live = observed_series["results"]["live_data"]
    assert series_live["latest_bar"] == series_live["sample_bars_last_5"][-1]
    ranged_small = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "market_series:aapl:daily", "--bars", "5"])
    small_live = ranged_small["results"]["live_data"]
    assert small_live["returned_bars"] == 5
    assert small_live["bars_inline"] is True
    assert len(small_live["bars"]) == 5
    assert small_live["price_summary"]["last_close"] == small_live["bars"][-1]["close"]
    assert re.fullmatch(r"\.xctx_runtime/exports/instrument_aapl_5_bars_[0-9a-f]{8}\.csv", small_live["csv"]["path"])
    assert (ROOT / small_live["csv"]["path"]).exists()
    ranged_large = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "instrument:aapl", "--bars", "31"])
    assert ranged_large["results"]["live_data"]["bars_inline"] is False
    assert ranged_large["results"]["live_data"]["bars_omitted_from_json"] == 31
    all_calendar = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--calendar-days", "0"])
    assert all_calendar["results"]["live_data"]["request"]["all_available"] is True
    assert all_calendar["results"]["live_data"]["returned_bars"] >= 1000
    calendar_50 = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--calendar-days", "50"])
    assert calendar_50["results"]["live_data"]["request"] == {"unit": "calendar_days", "value": 50, "all_available": False}
    unsupported_range = run_engine(["observe", "form:10-K", "--bars", "5"], code=1)
    assert "remove unsupported option --bars for stock_intelligence_hub::equity_filing observe" in unsupported_range["error"]
    missing_range_target = run_engine(["observe", "stock_intelligence_hub::market_data_gateway", "--bars", "5"], code=1)
    assert "provide an observation target before configured observe options" in missing_range_target["error"]
    spaced_form = run_engine(["observe", "DEF", "14A"])
    assert spaced_form["results"]["agent_subdomain"] == "equity_filing"
    assert spaced_form["results"]["live_data"]["id"] == "form:DEF 14A"
    range_conflict = run_engine(
        ["observe", "stock_intelligence_hub::market_data_gateway", "AAPL", "--bars", "1", "--calendar-days", "1"],
        code=1,
    )
    assert "choose either --bars or --calendar-days" in range_conflict["error"]
    filing_context = run_engine(["observe", "stock_intelligence_hub::equity_filing", "instrument:aapl"])
    assert filing_context["results"]["live_data"]["context_state"] == "with_equity"
    assert filing_context["results"]["live_data"]["issuer_submission_feed_status"] == "offline_not_bundled"

    audit = run_engine(["audit", "root"])
    assert_cmd(audit, record_type="audit", level="root")
    findings = {item["id"]: item for item in audit["results"]["findings"]}
    assert findings["down_for_maintenance:stock_intelligence_hub::fundamentals_gateway"]["repairable"] is False
    repaired = run_engine(["repair", "offline:macro_intelligence_hub"])
    assert_cmd(repaired, record_type="repair_result", level="agent_domain")
    terminal = run_engine(["repair", "down_for_maintenance:stock_intelligence_hub::fundamentals_gateway"], code=1)
    assert terminal["error"] == "down_for_maintenance"
    assert terminal["results"]["repair_path"] is None

    print("[pressure] plan/execute binding", flush=True)
    random_short = run_engine(["execute", "abcde", "--commit"], code=1)
    assert random_short["error"] == "unknown_plan_receipt"
    random_full = run_engine(["execute", "plan:sha256:" + "a" * 64, "--commit"], code=1)
    assert random_full["error"] == "unknown_plan_receipt"

    plan = run_engine(["plan", "bring_online", "stock_intelligence_hub::market_data_gateway"])
    results = plan["results"]
    assert re.fullmatch(r"[0-9a-f]{64}", results["receipt_sha256"])
    assert re.fullmatch(r"[0-9a-f]{5}", results["receipt_sha5"])
    assert (ROOT / ".xctx_runtime" / "plans" / f"{results['receipt_sha256']}.json").exists()
    no_commit = run_engine(["execute", results["plan_id"]], code=1)
    assert no_commit["error"] == "commit_required"
    execute_full = run_engine(["execute", results["plan_id"], "--commit"])
    assert execute_full["results"]["planner_binding"]["verified"] is True
    execute_short = run_engine(["execute", results["receipt_sha5"], "--commit"])
    assert execute_short["results"]["planner_binding"]["receipt_sha256"] == results["receipt_sha256"]

    print("[pressure] extension lane discipline", flush=True)
    for legacy in ("d", "identify", "status", "write", "doctor"):
        payload = run_engine([legacy], code=1)
        assert_cmd(payload, ok=False, record_type="error")
        assert "choose a known xctx command" in payload["error"]
    other = run_engine(["other", "--topic", "something-new"])
    assert_cmd(other, record_type="extension")
    assert other["results"]["topic"] == "something-new"

    print("[pressure] real CLI launcher and ledger probe", flush=True)
    cli_root = run_cli(["discover"])
    assert_cmd(cli_root, record_type="discovery", level="root")
    cli_unknown = run_cli(["execute", "abcde", "--commit"], code=1)
    assert cli_unknown["error"] == "unknown_plan_receipt"
    cli_plan = run_cli(["plan", "bring_online", "stock_intelligence_hub::market_data_gateway"])
    cli_short = cli_plan["results"]["receipt_sha5"]
    cli_exec = run_cli(["execute", cli_short, "--commit"])
    assert cli_exec["results"]["planner_binding"]["verified"] is True

    conflict = subprocess.run([str(XCTX), "--json", "--yaml", "discover"], cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert conflict.returncode == 1, conflict.stdout + conflict.stderr
    assert conflict.stderr == ""
    assert "choose either --json or --yaml" in json.loads(conflict.stdout)["error"]

    print("PRO xctx protocol pressure checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
