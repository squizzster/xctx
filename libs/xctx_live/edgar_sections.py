from __future__ import annotations

import importlib.metadata as metadata
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_10K_ITEMS = ["1", "1A", "1B", "1C", "3", "7", "7A", "8", "9", "9A", "9B", "9C"]
DEFAULT_10Q_ITEMS = ["1", "2", "3", "4", "1A", "5", "6"]
DEFAULT_20F_ITEMS = ["3", "4", "4A", "5", "6", "7", "8", "10", "15", "16"]
DEFAULT_40F_ITEMS = ["1", "2", "3", "4", "5", "6", "7"]
FORM_ALIASES = {
    "10K": "10-K",
    "10-K": "10-K",
    "10KA": "10-K/A",
    "10-K/A": "10-K/A",
    "10Q": "10-Q",
    "10-Q": "10-Q",
    "10QA": "10-Q/A",
    "10-Q/A": "10-Q/A",
    "20F": "20-F",
    "20-F": "20-F",
    "20FA": "20-F/A",
    "20-F/A": "20-F/A",
    "40F": "40-F",
    "40-F": "40-F",
    "40FA": "40-F/A",
    "40-F/A": "40-F/A",
}

ITEM_HEADING_RE = re.compile(
    r"""
    ^[\f ]*
    (?P<strong>\*\*)?
    (?P<prefix>\#{1,6}\s*)?
    ITEM\s+
    (?P<item>\d+[A-Z]?)
    \s*
    (?P<sep>\.|:|\u2013|\u2014|-)
    \s*
    (?P<title>.+?)
    \s*$
    """,
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)
MARKDOWN_TABLE_ITEM_HEADING_RE = re.compile(
    r"""
    ^[\f ]*\|\s*
    ITEM\s+
    (?P<item>\d+[A-Z]?)
    \s*
    (?P<sep>\.|:|\u2013|\u2014|-)?
    \s*\|\s*
    (?:\|\s*)?
    (?P<title>[^|]+?)
    \s*\|\s*$
    """,
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)
TABLE_OF_CONTENTS_RE = re.compile(r"table\s+of\s+contents", re.IGNORECASE)
NON_TABLE_PART_HEADING_RE = re.compile(
    r"^[\f ]*(?:\#{1,6}\s*)?PART\s+[IVX]+(?:[\s.\-]|$)",
    re.IGNORECASE | re.MULTILINE,
)
TABLE_BODY_PART_HEADING_RE = re.compile(
    r"^[\f ]*\|\s*PART\s+[IVX]+\s*[-\u2013\u2014]\s*[A-Z][A-Z\s]+\s*\|\s*$",
    re.MULTILINE,
)
ITEM_TITLE_FALLBACKS = [
    ("2", "Management's Discussion and Analysis of Financial Condition and Results of Operations"),
    ("3", "Quantitative and Qualitative Disclosures About Market Risk"),
    ("4", "Controls and Procedures"),
    ("1", "Legal Proceedings"),
    ("1A", "Risk Factors"),
    ("2", "Unregistered Sales of Equity Securities and Use of Proceeds"),
    ("3", "Defaults Upon Senior Securities"),
    ("4", "Mine Safety Disclosures"),
    ("5", "Other Information"),
    ("6", "Exhibits"),
]
ITEM_TITLE_BOUNDARIES = [
    ("1", "Financial Statements"),
]


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in value]
    return str(value)


def provenance(command: str | None = None) -> dict[str, Any]:
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "python_version": sys.version.split()[0],
        "edgartools_version": _package_version("edgartools"),
        "pandas_version": _package_version("pandas"),
        "command": command or "xctx_live.edgar_sections",
    }


def normalize_form(form: str | None) -> str:
    text = str(form or "").strip().upper()
    compact = re.sub(r"[\s_-]+", "", text)
    return FORM_ALIASES.get(compact, FORM_ALIASES.get(text, text))


def default_items_for_form(form: str | None) -> list[str]:
    normalized = normalize_form(form)
    if normalized.startswith("10-Q"):
        return list(DEFAULT_10Q_ITEMS)
    if normalized.startswith("20-F"):
        return list(DEFAULT_20F_ITEMS)
    if normalized.startswith("40-F"):
        return list(DEFAULT_40F_ITEMS)
    return list(DEFAULT_10K_ITEMS)


def safe_filename(value: Any) -> str:
    text = str(value).strip().replace("/", "_")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("._") or "output"


def _fsync_parent(path: Path) -> None:
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_text(path: Path, content: str | None) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(content or "")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _fsync_parent(path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return {"path": str(path), "bytes": path.stat().st_size}


def write_json(path: Path, payload: Any) -> dict[str, Any]:
    return write_text(path, json.dumps(_safe_value(payload), sort_keys=True, indent=2) + "\n")


def locate_item_sections(path: Path, wanted_items: Iterable[str]) -> dict[str, Any]:
    data = path.read_text(encoding="utf-8", errors="replace")
    wanted = {item.upper().strip() for item in wanted_items}

    def in_table_of_contents_region(start: int) -> bool:
        last_toc = -1
        for toc_match in TABLE_OF_CONTENTS_RE.finditer(data, 0, start):
            last_toc = toc_match.start()
        if last_toc < 0:
            return False
        between = data[last_toc:start]
        return NON_TABLE_PART_HEADING_RE.search(between) is None and TABLE_BODY_PART_HEADING_RE.search(between) is None

    all_matches = []
    for match in ITEM_HEADING_RE.finditer(data):
        item = match.group("item").upper()
        title = re.sub(r"\s+", " ", match.group("title")).strip().strip("*").strip()
        if re.search(r"\bcontinued\b", title, re.IGNORECASE):
            continue
        if match.group("prefix"):
            selection_reason = "markdown_heading"
        elif match.group("strong"):
            selection_reason = "markdown_strong_heading"
        else:
            selection_reason = "plain_heading"
        all_matches.append(
            {
                "item": item,
                "title": title,
                "separator": match.group("sep"),
                "selection_reason": selection_reason,
                "start": match.start(),
                "heading_end": match.end(),
            }
        )

    for match in MARKDOWN_TABLE_ITEM_HEADING_RE.finditer(data):
        item = match.group("item").upper()
        if not match.group("sep"):
            continue
        if in_table_of_contents_region(match.start()):
            continue
        title = re.sub(r"\s+", " ", match.group("title")).strip()
        if re.search(r"\bcontinued\b", title, re.IGNORECASE):
            continue
        all_matches.append(
            {
                "item": item,
                "title": title,
                "separator": match.group("sep") or "",
                "selection_reason": "markdown_table_heading",
                "start": match.start(),
                "heading_end": match.end(),
            }
        )

    if not any(entry["item"] in wanted for entry in all_matches):
        title_patterns = []
        for item, title in ITEM_TITLE_FALLBACKS:
            if item not in wanted:
                continue
            escaped = re.escape(title).replace(r"\ ", r"\s+")
            title_patterns.append(
                (
                    item,
                    title,
                    True,
                    re.compile(
                        rf"^[\f ]*(?P<prefix>\#{{1,6}}\s*)?(?P<title>{escaped})\s*$",
                        re.IGNORECASE | re.MULTILINE,
                    ),
                )
            )
        for item, title in ITEM_TITLE_BOUNDARIES:
            escaped = re.escape(title).replace(r"\ ", r"\s+")
            title_patterns.append(
                (
                    item,
                    title,
                    False,
                    re.compile(
                        rf"^[\f ]*(?P<prefix>\#{{1,6}}\s*)?(?P<title>{escaped})\s*$",
                        re.IGNORECASE | re.MULTILINE,
                    ),
                )
            )

        seen_item_starts = {(entry["item"], entry["start"]) for entry in all_matches}
        for item, _title, selectable, pattern in title_patterns:
            for match in pattern.finditer(data):
                key = (item, match.start())
                if key in seen_item_starts:
                    continue
                title = re.sub(r"\s+", " ", match.group("title")).strip()
                all_matches.append(
                    {
                        "item": item,
                        "title": title,
                        "separator": "",
                        "selection_reason": "markdown_title_heading" if match.group("prefix") else "title_heading",
                        "start": match.start(),
                        "heading_end": match.end(),
                        "selectable": selectable,
                        "weak_match": True,
                    }
                )
                seen_item_starts.add(key)

    all_matches.sort(key=lambda entry: entry["start"])
    for index, entry in enumerate(all_matches):
        entry["end"] = all_matches[index + 1]["start"] if index + 1 < len(all_matches) else len(data)
        entry["chars"] = entry["end"] - entry["start"]
        entry["probable_toc"] = entry["chars"] < 500 and entry["selection_reason"] != "markdown_table_heading"

    matches = []
    for item in wanted:
        item_matches = [entry for entry in all_matches if entry["item"] == item and entry.get("selectable", True)]
        substantive = [entry for entry in item_matches if not entry["probable_toc"]]
        matches.extend(substantive or item_matches)
    matches.sort(key=lambda entry: entry["start"])

    return {
        "path": str(path),
        "file_chars": len(data),
        "candidate_count": len(all_matches),
        "all_candidates": all_matches,
        "items": matches,
    }


def write_located_sections(path: Path, wanted_items: Iterable[str]) -> dict[str, Any]:
    requested_items = []
    seen_requested = set()
    for item in wanted_items:
        normalized = str(item).upper().strip()
        if normalized and normalized not in seen_requested:
            requested_items.append(normalized)
            seen_requested.add(normalized)

    index = locate_item_sections(path, requested_items)
    data = path.read_text(encoding="utf-8", errors="replace")
    section_dir = path.parent / "sections"

    files: dict[str, Any] = {}
    item_counts: dict[str, int] = {}
    for item in index["items"]:
        section_text = data[item["start"] : item["end"]]
        item_key = item["item"]
        item_counts[item_key] = item_counts.get(item_key, 0) + 1
        suffix = "" if item_counts[item_key] == 1 else f"_{item_counts[item_key]}"
        file_key = f"{item_key}{suffix}"
        section_path = section_dir / f"item_{safe_filename(item_key).lower()}{suffix}.md"
        file_entry = write_text(section_path, section_text)
        files[file_key] = file_entry
        item["file_key"] = file_key
        item["file"] = file_entry

    index["files"] = files
    found_items = {item["item"] for item in index["items"]}
    missing_items = [item for item in requested_items if item not in found_items]
    index["requested_items"] = requested_items
    index["missing_items"] = missing_items
    index["success"] = bool(index["items"])
    index["partial_success"] = bool(index["items"] and missing_items)
    index["errors"] = [] if index["items"] else [{"path": "items", "message": "no requested item sections found"}]
    warnings: list[dict[str, str]] = []
    if index["items"] and missing_items:
        warnings.append(
            {
                "path": "missing_items",
                "message": f"some requested item sections were not found: {', '.join(missing_items)}",
            }
        )
    if any(item.get("weak_match") for item in index["items"]):
        warnings.append(
            {
                "path": "items",
                "message": "section extraction used title-only fallback headings; verify before relying on section boundaries",
            }
        )
    if any(item.get("probable_toc") for item in index["items"]):
        warnings.append(
            {
                "path": "items",
                "message": "one or more selected sections are very short and may be placeholders or table-of-contents entries",
            }
        )
    index["warnings"] = warnings
    index["provenance"] = provenance()
    index["index_file"] = write_json(section_dir / "index.json", index)
    return index


def make_company_pack_sections_optional(sections_manifest: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if sections_manifest.get("success") is not False:
        return sections_manifest, []

    warning = {
        "path": "sections",
        "message": "section splitting did not locate requested items; filing.md remains available",
    }
    normalized = dict(sections_manifest)
    normalized["success"] = True
    normalized["partial_success"] = False
    normalized["optional"] = True
    normalized["section_extraction_success"] = False
    normalized["original_errors"] = _safe_value(sections_manifest.get("errors", []))
    normalized["errors"] = []
    normalized["warnings"] = list(normalized.get("warnings") or []) + [warning]
    return normalized, [warning]
