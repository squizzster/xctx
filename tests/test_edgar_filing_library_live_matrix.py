from __future__ import annotations

import os

import pytest

from framework_helpers import ensure_libs_path


ensure_libs_path()

from xctx_live.edgar_filing_library import (
    SUPER_PACK_ANNUAL_FORMS,
    SUPER_PACK_QUARTERLY_FORMS,
    SUPER_PACK_UPDATE_FORMS,
    _select_super_pack_candidates,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.live_edgar,
    pytest.mark.timeout(1800),
]


LIVE_MATRIX_IDENTIFIERS = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "JPM",
    "JNJ",
    "XOM",
    "WMT",
    "PG",
    "V",
    "MA",
    "UNH",
    "HD",
    "BAC",
    "PFE",
    "KO",
    "NKE",
    "DIS",
    "NFLX",
    "ORCL",
    "INTC",
    "AMD",
    "IBM",
    "GE",
    "BA",
    "T",
    "VZ",
    "SHOP",
    "SAP",
    "ASML",
    "BABA",
    "TSM",
    "NVO",
    "RIO",
    "BP",
    "TM",
    "SONY",
]


def test_live_super_pack_selection_matrix_covers_broad_issuer_set() -> None:
    if os.environ.get("XCTX_LIVE_EDGAR_MATRIX") != "1":
        pytest.skip("set XCTX_LIVE_EDGAR_MATRIX=1 to run the broad live EDGAR selection matrix")
    identity = os.environ.get("XCTX_EDGAR_IDENTITY") or os.environ.get("EDGAR_IDENTITY")
    if not identity:
        pytest.skip("live EDGAR matrix requires XCTX_EDGAR_IDENTITY or EDGAR_IDENTITY")

    from edgar import Company, set_identity

    set_identity(identity)
    reports = []
    hard_errors = []
    annual_or_quarterly_hits = 0
    update_hits = 0
    for identifier in LIVE_MATRIX_IDENTIFIERS:
        events: list[dict] = []
        try:
            selection = _select_super_pack_candidates(
                Company(identifier),
                annual_forms=list(SUPER_PACK_ANNUAL_FORMS),
                quarterly_forms=list(SUPER_PACK_QUARTERLY_FORMS),
                update_forms=list(SUPER_PACK_UPDATE_FORMS),
                update_limit=1,
                progress_events=events,
            )
        except Exception as exc:
            hard_errors.append({"identifier": identifier, "message": str(exc)})
            continue
        selected_roles = [item["role"] for item in selection["selections"]]
        if any(role in {"latest_annual", "latest_quarterly"} for role in selected_roles):
            annual_or_quarterly_hits += 1
        if "latest_update" in selected_roles:
            update_hits += 1
        reports.append(
            {
                "identifier": identifier,
                "roles": selected_roles,
                "unavailable": selection["unavailable"],
                "progress_event_count": len(events),
            }
        )

    assert len(reports) >= 35, {"hard_errors": hard_errors, "reports": reports}
    assert len(hard_errors) <= 5, {"hard_errors": hard_errors, "reports": reports}
    assert annual_or_quarterly_hits >= 30, reports
    assert update_hits >= 20, reports
    assert all(report["progress_event_count"] >= 6 for report in reports), reports
