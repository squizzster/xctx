from __future__ import annotations

from pathlib import Path

import pytest

from framework_helpers import ensure_libs_path


ensure_libs_path()

from xctx_live.edgar_sections import default_items_for_form, locate_item_sections, write_located_sections


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


def test_locate_item_sections_accepts_common_heading_variants(tmp_path: Path) -> None:
    filing = tmp_path / "filing.md"
    filing.write_text(
        "\n".join(
            [
                "ITEM 1: BUSINESS",
                "business text",
                "Item 1A \u2013 Risk Factors",
                "risk text",
                "## Item 7. Management's Discussion and Analysis",
                "mda text",
                "Item 8\u2014Financial Statements",
                "financial text",
            ]
        ),
        encoding="utf-8",
    )

    index = locate_item_sections(filing, ["1", "1A", "7", "8"])

    assert {item["item"] for item in index["items"]} == {"1", "1A", "7", "8"}
    assert index["candidate_count"] == 4


def test_write_located_sections_preserves_duplicate_items(tmp_path: Path) -> None:
    filing = tmp_path / "filing.md"
    filing.write_text(
        "\n".join(
            [
                "ITEM 1: BUSINESS",
                "first business text",
                "ITEM 1: BUSINESS",
                "second business text",
                "ITEM 1A. RISK FACTORS",
                "risk text",
            ]
        ),
        encoding="utf-8",
    )

    index = write_located_sections(filing, ["1", "1A"])

    assert set(index["files"]) == {"1", "1_2", "1A"}
    assert [item["file_key"] for item in index["items"]] == ["1", "1_2", "1A"]
    assert all(Path(file_entry["path"]).exists() for file_entry in index["files"].values())


def test_locate_item_sections_skips_pdf_table_of_contents_candidates(tmp_path: Path) -> None:
    filing = tmp_path / "filing.md"
    filing.write_text(
        "\n".join(
            [
                "Item 1. Business",
                "Item 1A. Risk Factors",
                "Item 7. Management's Discussion and Analysis",
                "\fItem 1. Business.",
                "real business text " * 80,
                "\fItem 1A. Risk Factors.",
                "real risk text " * 80,
                "\fItem 7. Management's Discussion and Analysis.",
                "real mda text " * 80,
            ]
        ),
        encoding="utf-8",
    )

    index = locate_item_sections(filing, ["1", "1A", "7"])
    by_item = {item["item"]: item for item in index["items"]}

    assert by_item["1"]["start"] > 50
    assert by_item["1A"]["start"] > by_item["1"]["start"]
    assert by_item["7"]["start"] > by_item["1A"]["start"]
    assert all(item["chars"] >= 500 for item in index["items"])


def test_default_items_for_form_uses_periodic_form_defaults() -> None:
    assert default_items_for_form("10-Q") == ["1", "2", "3", "4", "1A", "5", "6"]
    assert "7" in default_items_for_form("10-K")
    assert "5" in default_items_for_form("20-F")
    assert "4" in default_items_for_form("40-F")


def test_locate_item_sections_accepts_10q_markdown_table_body_headings(tmp_path: Path) -> None:
    filing = tmp_path / "filing.md"
    filing.write_text(
        "\n".join(
            [
                "| Item 1. | Financial Statements (Unaudited) | 3 |",
                "| Item 1 | Financial Statements (Unaudited) |",
                "| Item 2. | Management's Discussion and Analysis | 28 |",
                "### PART I. FINANCIAL INFORMATION",
                "| ITEM 1. | | Financial Statements (Unaudited) |",
                "financial text " * 80,
                "| ITEM 2. | | Management's Discussion and Analysis |",
                "mda text " * 80,
                "| ITEM 3. | Quantitative and Qualitative Disclosures About Market Risk |",
                "market risk text " * 80,
                "| ITEM 4. | | Controls and Procedures |",
                "controls text",
                "### PART II. OTHER INFORMATION",
                "| ITEM 1A. | | Risk Factors |",
                "risk text",
                "| ITEM 6. | | Exhibits |",
                "exhibit text",
            ]
        ),
        encoding="utf-8",
    )

    index = locate_item_sections(filing, default_items_for_form("10-Q"))
    found = [(item["item"], item["title"], item["selection_reason"], item["probable_toc"]) for item in index["items"]]

    assert index["candidate_count"] == 6
    assert found == [
        ("1", "Financial Statements (Unaudited)", "markdown_table_heading", False),
        ("2", "Management's Discussion and Analysis", "markdown_table_heading", False),
        ("3", "Quantitative and Qualitative Disclosures About Market Risk", "markdown_table_heading", False),
        ("4", "Controls and Procedures", "markdown_table_heading", False),
        ("1A", "Risk Factors", "markdown_table_heading", False),
        ("6", "Exhibits", "markdown_table_heading", False),
    ]


def test_locate_item_sections_skips_table_of_contents_item_rows_without_body_marker(tmp_path: Path) -> None:
    filing = tmp_path / "filing.md"
    filing.write_text(
        "\n".join(
            [
                "### TABLE OF CONTENTS",
                "| ITEM 1. | Financial Statements (unaudited) |",
                "| ITEM 2. | Management's Discussion and Analysis |",
                "| ITEM 6. | Exhibits |",
                "Cautionary Note Regarding Forward-Looking Statements",
                "body text " * 80,
            ]
        ),
        encoding="utf-8",
    )

    index = write_located_sections(filing, default_items_for_form("10-Q"))

    assert index["items"] == []
    assert index["missing_items"] == ["1", "2", "3", "4", "1A", "5", "6"]
    assert index["errors"] == [{"path": "items", "message": "no requested item sections found"}]


def test_locate_item_sections_accepts_title_only_10q_headings(tmp_path: Path) -> None:
    filing = tmp_path / "filing.md"
    filing.write_text(
        "\n".join(
            [
                "#### Table of Contents",
                "| Management's Discussion and Analysis of Financial Condition and Results of Operations | 2 |",
                "| Controls and Procedures | 18 |",
                "#### MD&AOverview",
                "Management's Discussion and Analysis of Financial Condition and Results of Operations",
                "mda text " * 80,
                "### Controls and Procedures",
                "controls text " * 80,
                "#### Legal Proceedings",
                "legal text " * 80,
                "#### Risk Factors",
                "risk text " * 80,
                "#### Other Information",
                "other text",
                "#### Financial Statements",
                "financial text " * 80,
                "#### Exhibits",
                "exhibit text",
            ]
        ),
        encoding="utf-8",
    )

    index = write_located_sections(filing, default_items_for_form("10-Q"))
    found = [(item["item"], item["title"], item["selection_reason"]) for item in index["items"]]

    assert found == [
        ("2", "Management's Discussion and Analysis of Financial Condition and Results of Operations", "title_heading"),
        ("4", "Controls and Procedures", "markdown_title_heading"),
        ("1", "Legal Proceedings", "markdown_title_heading"),
        ("1A", "Risk Factors", "markdown_title_heading"),
        ("5", "Other Information", "markdown_title_heading"),
        ("6", "Exhibits", "markdown_title_heading"),
    ]
    assert any("title-only fallback" in warning["message"] for warning in index["warnings"])


def test_locate_item_sections_accepts_markdown_bold_headings(tmp_path: Path) -> None:
    filing = tmp_path / "filing.md"
    filing.write_text(
        "\n".join(
            [
                "**Item 3.Quantitative and Qualitative Disclosures About Market Risk**",
                "market risk text " * 80,
                "**Item 4.Controls and Procedures",
                "controls text " * 80,
                "Item 6. Exhibits",
                "exhibit text",
            ]
        ),
        encoding="utf-8",
    )

    index = write_located_sections(filing, default_items_for_form("10-Q"))
    found = [(item["item"], item["title"], item["selection_reason"]) for item in index["items"]]

    assert found == [
        ("3", "Quantitative and Qualitative Disclosures About Market Risk", "markdown_strong_heading"),
        ("4", "Controls and Procedures", "markdown_strong_heading"),
        ("6", "Exhibits", "plain_heading"),
    ]
    assert index["missing_items"] == ["1", "2", "1A", "5"]
