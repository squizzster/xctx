from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1"
LIBRARY_RUNTIME_PATH = Path("stock_intelligence_hub") / "edgar_filing_library"
REGISTRY_FILENAME = "registry.sqlite"
ARTIFACTS_DIRNAME = "artifacts"
LIST_DEFAULT_LIMIT = 10
LIST_MAX_LIMIT = 100
COMPANY_PACK_DEFAULT_ITEMS = "1,1A,7,8,9A"
COMPANY_PACK_DEFAULT_CONCEPTS = (
    "us-gaap:Assets,"
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax,"
    "us-gaap:NetIncomeLoss"
)

KEY_FORM_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "id": "annual_reports",
        "label": "Annual reports",
        "forms": ["10-K", "20-F", "40-F"],
        "why": "Core audited annual business, risk, MD&A, and financial statement filings.",
    },
    {
        "id": "quarterly_reports",
        "label": "Quarterly reports",
        "forms": ["10-Q"],
        "why": "Core interim operating results and financial statement updates.",
    },
    {
        "id": "current_results",
        "label": "Current results and material event reports",
        "forms": ["8-K", "6-K"],
        "why": "Material events, earnings releases, and foreign issuer interim reports.",
    },
    {
        "id": "proxy_governance",
        "label": "Proxy and governance",
        "forms": ["DEF 14A"],
        "why": "Executive compensation, governance, voting, ownership, and annual meeting material.",
    },
    {
        "id": "registration_transactions",
        "label": "Registration and transaction filings",
        "forms": ["S-1", "F-1", "S-4", "F-4", "DEFM14A"],
        "why": "IPO, foreign registration, merger, and transaction disclosures.",
    },
)

KEY_FORMS: tuple[str, ...] = tuple(form for group in KEY_FORM_GROUPS for form in group["forms"])
AMENDMENT_FORMS: tuple[str, ...] = tuple(f"{form}/A" for form in KEY_FORMS if not form.endswith("/A"))
CRITICAL_FORM_SET: tuple[str, ...] = tuple(dict.fromkeys([*KEY_FORMS, *AMENDMENT_FORMS]))
ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"))


def _pretty_json(value: Any) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, indent=2) + "\n"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    for method_name in ("to_dict", "to_json"):
        method = getattr(value, method_name, None)
        if not callable(method):
            continue
        try:
            result = method()
        except Exception:
            continue
        if isinstance(result, str):
            try:
                return _json_safe(json.loads(result))
            except Exception:
                return result
        return _json_safe(result)
    return str(value)


def _runtime_root(root: Path) -> Path:
    configured = os.environ.get("XCTX_RUNTIME_DIR")
    runtime = Path(configured) if configured else root / ".xctx_runtime"
    if not runtime.is_absolute():
        runtime = root / runtime
    return runtime


def _detail_level() -> str:
    level = str(os.environ.get("XCTX_DETAIL_LEVEL") or "basic").strip().lower()
    return level if level in {"basic", "more", "max"} else "basic"


def _detail_is_max() -> bool:
    return _detail_level() == "max"


def library_paths(root: Path) -> dict[str, Path]:
    base = _runtime_root(root) / LIBRARY_RUNTIME_PATH
    return {
        "base": base,
        "registry": base / REGISTRY_FILENAME,
        "artifacts": base / ARTIFACTS_DIRNAME,
    }


def _display_path(root: Path, path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    for base in (root.resolve(), _runtime_root(root).resolve()):
        try:
            return str(resolved.relative_to(base))
        except ValueError:
            continue
    return str(resolved)


def _path_fields(root: Path, path: Path, *, key: str = "path") -> dict[str, Any]:
    fields: dict[str, Any] = {key: _display_path(root, path)}
    if _detail_is_max():
        try:
            fields["resolved_path"] = str(path.resolve())
        except OSError:
            fields["resolved_path"] = str(path.absolute())
    return fields


def _empty_stats(root: Path) -> dict[str, Any]:
    paths = library_paths(root)
    stats = {
        "registry_initialized": False,
        "registry_path": _display_path(root, paths["registry"]),
        "artifact_root": _display_path(root, paths["artifacts"]),
        "total_filings": 0,
        "available_filings": 0,
        "issuer_count": 0,
        "artifact_file_count": 0,
        "work_run_count": 0,
        "last_checked_at": None,
        "forms": {},
        "key_forms_available": {form: 0 for form in CRITICAL_FORM_SET},
    }
    if _detail_is_max():
        stats["resolved_paths"] = {
            "registry": str(paths["registry"].resolve()),
            "artifact_root": str(paths["artifacts"].resolve()),
        }
    return stats


def _connect_existing(root: Path) -> sqlite3.Connection | None:
    path = library_paths(root)["registry"]
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_rw(root: Path) -> sqlite3.Connection:
    path = library_paths(root)["registry"]
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS registry_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS issuers (
          issuer_key TEXT PRIMARY KEY,
          cik TEXT,
          ticker TEXT,
          name TEXT,
          created_at TEXT NOT NULL,
          last_checked_at TEXT,
          source TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS filings (
          accession TEXT PRIMARY KEY,
          issuer_key TEXT,
          cik TEXT,
          ticker TEXT,
          company TEXT,
          form TEXT NOT NULL,
          filing_date TEXT,
          period_of_report TEXT,
          local_state TEXT NOT NULL,
          artifact_dir TEXT,
          source TEXT NOT NULL,
          created_at TEXT NOT NULL,
          last_checked_at TEXT,
          last_downloaded_at TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY (issuer_key) REFERENCES issuers(issuer_key)
        );

        CREATE TABLE IF NOT EXISTS artifact_files (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          accession TEXT NOT NULL,
          kind TEXT NOT NULL,
          path TEXT NOT NULL,
          bytes INTEGER NOT NULL,
          sha256 TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY (accession) REFERENCES filings(accession) ON DELETE CASCADE,
          UNIQUE (accession, path)
        );

        CREATE TABLE IF NOT EXISTS work_runs (
          run_id TEXT PRIMARY KEY,
          operation TEXT NOT NULL,
          identifier TEXT,
          forms TEXT,
          source TEXT,
          status TEXT NOT NULL,
          plan_id TEXT,
          commit_id TEXT,
          result_id TEXT,
          created_at TEXT NOT NULL,
          finished_at TEXT,
          summary_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_filings_identifier
          ON filings (ticker, cik, company);
        CREATE INDEX IF NOT EXISTS idx_filings_form_date
          ON filings (form, filing_date DESC);
        CREATE INDEX IF NOT EXISTS idx_artifact_files_accession
          ON artifact_files (accession);
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO registry_meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def registry_stats(root: Path) -> dict[str, Any]:
    conn = _connect_existing(root)
    if conn is None:
        return _empty_stats(root)
    with conn:
        stats = _empty_stats(root)
        stats["registry_initialized"] = True
        stats["total_filings"] = conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
        stats["available_filings"] = conn.execute(
            "SELECT COUNT(*) FROM filings WHERE local_state IN ('available', 'downloaded', 'indexed')"
        ).fetchone()[0]
        stats["issuer_count"] = conn.execute("SELECT COUNT(*) FROM issuers").fetchone()[0]
        stats["artifact_file_count"] = conn.execute("SELECT COUNT(*) FROM artifact_files").fetchone()[0]
        stats["work_run_count"] = conn.execute("SELECT COUNT(*) FROM work_runs").fetchone()[0]
        stats["last_checked_at"] = conn.execute("SELECT MAX(last_checked_at) FROM filings").fetchone()[0]
        stats["forms"] = {
            str(row["form"]): int(row["count"])
            for row in conn.execute("SELECT form, COUNT(*) AS count FROM filings GROUP BY form ORDER BY form")
        }
        stats["key_forms_available"] = {
            form: int(stats["forms"].get(form, 0))
            for form in CRITICAL_FORM_SET
        }
        return stats


def _edgar_identity_status() -> dict[str, Any]:
    for key in ("EDGAR_IDENTITY", "XCTX_EDGAR_IDENTITY"):
        value = os.environ.get(key)
        if value and value.strip():
            return {"available": True, "source": key, "value_printed": False}
    return {"available": False, "source": None, "value_printed": False}


def discover_library(root: Path, projection: str = "compact") -> dict[str, Any]:
    stats = registry_stats(root)
    ref = "stock_intelligence_hub::edgar_filing_library"
    payload: dict[str, Any] = {
        "object_type": "edgar_filing_library_discovery",
        "projection": projection,
        "storage": {
            "engine": "sqlite",
            "registry_path": stats["registry_path"],
            "artifact_root": stats["artifact_root"],
            "registry_initialized": stats["registry_initialized"],
            "framework_boundary": "SEC filing inventory state is owned by this stock-domain adapter, not by generic xctx runtime code.",
        },
        "edgar_identity": _edgar_identity_status(),
        "local_availability": {
            "available_filings": stats["available_filings"],
            "issuer_count": stats["issuer_count"],
            "artifact_file_count": stats["artifact_file_count"],
            "last_checked_at": stats["last_checked_at"],
            "forms": stats["forms"],
        },
        "key_filing_groups": [
            {
                "id": group["id"],
                "label": group["label"],
                "forms": group["forms"],
                "available_count": sum(int(stats["forms"].get(form, 0)) for form in group["forms"]),
                "run_cmd": f"./xctx discover {ref}::list_key_filings",
            }
            for group in KEY_FORM_GROUPS
        ],
        "discoverable_modes": [
            {
                "id": "list_key_filings",
                "run_cmd": f"./xctx discover {ref}::list_key_filings [--identifier AAPL]",
            },
            {
                "id": "list_available_filings",
                "run_cmd": f"./xctx discover {ref}::list_available_filings [--identifier AAPL] [--form 10-K]",
            },
            {
                "id": "list_artifacts",
                "run_cmd": f"./xctx discover {ref}::list_artifacts [--identifier AAPL] [--kind csv]",
            },
        ],
        "observable_patterns": [
            {
                "id": "filing:<accession>",
                "run_cmd": f"./xctx observe {ref} filing:<accession>",
            },
            {
                "id": "artifact_file:<id>",
                "run_cmd": f"./xctx observe {ref} artifact_file:<id> [--preview-chars 800]",
            }
        ],
        "planned_effects": [
            {
                "action": "download_key_filings",
                "run_cmd": f"./xctx plan {ref}::download_key_filings --identifier AAPL --forms critical",
            },
            {
                "action": "company_pack",
                "run_cmd": f"./xctx plan {ref}::company_pack --pack-identifier AAPL --pack-form 10-K",
            },
            {
                "action": "index_local_artifacts",
                "run_cmd": f"./xctx plan {ref}::index_local_artifacts --artifact-root <existing-edgar-artifact-root>",
            },
        ],
        "next_moves": [
            {"run_cmd": f"./xctx discover {ref}::list_available_filings"},
            {"run_cmd": f"./xctx discover {ref}::list_artifacts --kind csv"},
            {"run_cmd": f"./xctx discover {ref}::list_key_filings --identifier AAPL"},
            {"run_cmd": f"./xctx plan {ref}::download_key_filings --identifier AAPL --forms critical"},
        ],
    }
    if projection == "full":
        payload["key_form_catalog"] = [
            {
                **group,
                "forms_with_amendments": [
                    form
                    for form in [*group["forms"], *[f"{item}/A" for item in group["forms"]]]
                    if form in CRITICAL_FORM_SET
                ],
            }
            for group in KEY_FORM_GROUPS
        ]
        payload["registry_stats"] = stats
    return payload


def _normalize_form(form: str) -> str:
    text = str(form).strip().upper()
    text = re.sub(r"\s+", " ", text)
    return text


def parse_forms(value: str | None) -> list[str]:
    text = str(value or "critical").strip()
    if not text or text.lower() in {"critical", "key", "all-key"}:
        return list(CRITICAL_FORM_SET)
    forms: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[,;]+", text):
        form = _normalize_form(raw)
        if not form:
            continue
        if not re.fullmatch(r"[A-Z0-9 -]+(?:/A)?", form):
            raise ValueError(f"unsupported SEC form token: {raw}")
        if form not in seen:
            seen.add(form)
            forms.append(form)
    if not forms:
        raise ValueError("--forms must contain at least one SEC form")
    return forms


def _option(args: list[str], flag: str, default: str | None = None, *, required: bool = False) -> str | None:
    if flag not in args:
        if required:
            raise ValueError(f"missing {flag}")
        return default
    index = args.index(flag)
    if index + 1 >= len(args):
        raise ValueError(f"missing value for {flag}")
    return args[index + 1]


def _int_option(
    args: list[str],
    flag: str,
    default: int,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    raw = _option(args, flag, str(default))
    try:
        value = int(str(raw))
    except ValueError as exc:
        raise ValueError(f"{flag} requires an integer") from exc
    if value < minimum:
        raise ValueError(f"{flag} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{flag} must be at most {maximum}")
    return value


def _positional_query(args: list[str], value_options: set[str]) -> str:
    query: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("--"):
            if token not in value_options:
                raise ValueError(f"unsupported option {token}")
            index += 2
            continue
        query.append(token)
        index += 1
    return " ".join(query).strip()


def _identifier_filter_sql(identifier: str | None, *, prefix: str = "") -> tuple[str, list[Any]]:
    if not identifier:
        return "", []
    query = f"%{identifier.strip().lower()}%"
    ticker = f"{prefix}ticker"
    company = f"{prefix}company"
    cik = f"{prefix}cik"
    return (
        f" AND (lower(COALESCE({ticker}, '')) LIKE ? OR lower(COALESCE({company}, '')) LIKE ? OR lower(COALESCE({cik}, '')) LIKE ?)",
        [query, query, query],
    )


def _filing_projection(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    accession = str(d.get("accession") or "")
    return {
        "id": f"filing:{accession}",
        "accession": accession,
        "form": d.get("form"),
        "filing_date": d.get("filing_date"),
        "period_of_report": d.get("period_of_report"),
        "cik": d.get("cik"),
        "ticker": d.get("ticker"),
        "company": d.get("company"),
        "local_state": d.get("local_state"),
        "artifact_count": int(d.get("artifact_count") or 0),
        "observe_cmd": f"./xctx observe stock_intelligence_hub::edgar_filing_library filing:{accession}",
    }


def list_available_filings(root: Path, args: list[str]) -> dict[str, Any]:
    limit = _int_option(args, "--limit", LIST_DEFAULT_LIMIT, minimum=1, maximum=LIST_MAX_LIMIT)
    cursor = _int_option(args, "--cursor", 0, minimum=0)
    form = _option(args, "--form")
    identifier = _option(args, "--identifier")
    query = _positional_query(args, {"--limit", "--cursor", "--form", "--identifier"})
    conn = _connect_existing(root)
    if conn is None:
        return {
            "object_type": "edgar_available_filing_list",
            "filings": [],
            "pagination": {
                "limit": limit,
                "cursor": str(cursor) if cursor else None,
                "returned_count": 0,
                "next_cursor": None,
                "has_more": False,
                "total_count": 0,
            },
            "registry_initialized": False,
            "next_moves": [
                {
                    "run_cmd": "./xctx plan stock_intelligence_hub::edgar_filing_library::download_key_filings --identifier AAPL --forms critical"
                },
                {
                    "run_cmd": "./xctx plan stock_intelligence_hub::edgar_filing_library::index_local_artifacts --artifact-root <existing-edgar-artifact-root>"
                },
            ],
        }

    where = "WHERE 1=1"
    params: list[Any] = []
    if form:
        where += " AND upper(form) = upper(?)"
        params.append(_normalize_form(form))
    extra, extra_params = _identifier_filter_sql(identifier)
    where += extra
    params.extend(extra_params)
    if query:
        like = f"%{query.lower()}%"
        where += (
            " AND (lower(accession) LIKE ? OR lower(COALESCE(company, '')) LIKE ? "
            "OR lower(COALESCE(ticker, '')) LIKE ? OR lower(COALESCE(cik, '')) LIKE ? OR lower(form) LIKE ?)"
        )
        params.extend([like, like, like, like, like])

    with conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM filings {where}", params).fetchone()[0])
        rows = conn.execute(
            f"""
            SELECT f.*, COUNT(a.id) AS artifact_count
            FROM filings f
            LEFT JOIN artifact_files a ON a.accession = f.accession
            {where}
            GROUP BY f.accession
            ORDER BY COALESCE(f.filing_date, '') DESC, f.accession DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, cursor],
        ).fetchall()
    next_cursor = cursor + len(rows) if cursor + len(rows) < total else None
    return {
        "object_type": "edgar_available_filing_list",
        "query": query or None,
        "filters": {"identifier": identifier, "form": form},
        "filings": [_filing_projection(row) for row in rows],
        "pagination": {
            "limit": limit,
            "cursor": str(cursor) if cursor else None,
            "returned_count": len(rows),
            "next_cursor": str(next_cursor) if next_cursor is not None else None,
            "has_more": next_cursor is not None,
            "total_count": total,
        },
        "registry_initialized": True,
    }


def _parse_artifact_kinds(value: str | None) -> list[str]:
    if not value:
        return []
    kinds: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[,;]+", value):
        kind = raw.strip().lower()
        if not kind:
            continue
        if not re.fullmatch(r"[a-z0-9_.-]+", kind):
            raise ValueError(f"unsupported artifact kind: {raw}")
        if kind not in seen:
            seen.add(kind)
            kinds.append(kind)
    return kinds


def _artifact_projection(root: Path, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    artifact_id = int(d.get("artifact_id") or d.get("id"))
    accession = str(d.get("accession") or "")
    path = Path(str(d.get("path") or ""))
    payload = {
        "id": f"artifact_file:{artifact_id}",
        "artifact_file_id": artifact_id,
        "filing_id": f"filing:{accession}",
        "accession": accession,
        "kind": d.get("kind"),
        **_path_fields(root, path),
        "bytes": int(d.get("bytes") or 0),
        "sha256": d.get("sha256"),
        "form": d.get("form"),
        "filing_date": d.get("filing_date"),
        "period_of_report": d.get("period_of_report"),
        "cik": d.get("cik"),
        "ticker": d.get("ticker"),
        "company": d.get("company"),
        "observe_cmd": f"./xctx observe stock_intelligence_hub::edgar_filing_library artifact_file:{artifact_id}",
        "filing_observe_cmd": f"./xctx observe stock_intelligence_hub::edgar_filing_library filing:{accession}",
    }
    return payload


def list_artifacts(root: Path, args: list[str]) -> dict[str, Any]:
    limit = _int_option(args, "--limit", LIST_DEFAULT_LIMIT, minimum=1, maximum=LIST_MAX_LIMIT)
    cursor = _int_option(args, "--cursor", 0, minimum=0)
    form = _option(args, "--form")
    identifier = _option(args, "--identifier")
    kinds = _parse_artifact_kinds(_option(args, "--kind"))
    query = _positional_query(args, {"--limit", "--cursor", "--form", "--identifier", "--kind"})
    conn = _connect_existing(root)
    if conn is None:
        return {
            "object_type": "edgar_artifact_file_list",
            "artifacts": [],
            "pagination": {
                "limit": limit,
                "cursor": str(cursor) if cursor else None,
                "returned_count": 0,
                "next_cursor": None,
                "has_more": False,
                "total_count": 0,
            },
            "registry_initialized": False,
            "next_moves": [
                {
                    "run_cmd": "./xctx plan stock_intelligence_hub::edgar_filing_library::company_pack --pack-identifier AAPL --pack-form 10-K"
                },
                {
                    "run_cmd": "./xctx plan stock_intelligence_hub::edgar_filing_library::index_local_artifacts --artifact-root <existing-edgar-artifact-root>"
                },
            ],
        }

    where = "WHERE 1=1"
    params: list[Any] = []
    if form:
        where += " AND upper(f.form) = upper(?)"
        params.append(_normalize_form(form))
    extra, extra_params = _identifier_filter_sql(identifier, prefix="f.")
    where += extra
    params.extend(extra_params)
    if kinds:
        where += " AND lower(a.kind) IN ({})".format(",".join("?" for _ in kinds))
        params.extend(kinds)
    if query:
        like = f"%{query.lower()}%"
        where += (
            " AND (lower(a.path) LIKE ? OR lower(a.kind) LIKE ? OR lower(a.accession) LIKE ? "
            "OR lower(COALESCE(f.company, '')) LIKE ? OR lower(COALESCE(f.ticker, '')) LIKE ? "
            "OR lower(COALESCE(f.cik, '')) LIKE ? OR lower(f.form) LIKE ?)"
        )
        params.extend([like, like, like, like, like, like, like])

    with conn:
        total = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM artifact_files a
                JOIN filings f ON f.accession = a.accession
                {where}
                """,
                params,
            ).fetchone()[0]
        )
        rows = conn.execute(
            f"""
            SELECT
              a.id AS artifact_id,
              a.accession,
              a.kind,
              a.path,
              a.bytes,
              a.sha256,
              f.form,
              f.filing_date,
              f.period_of_report,
              f.cik,
              f.ticker,
              f.company
            FROM artifact_files a
            JOIN filings f ON f.accession = a.accession
            {where}
            ORDER BY COALESCE(f.filing_date, '') DESC, a.kind, a.path
            LIMIT ? OFFSET ?
            """,
            [*params, limit, cursor],
        ).fetchall()
    next_cursor = cursor + len(rows) if cursor + len(rows) < total else None
    return {
        "object_type": "edgar_artifact_file_list",
        "query": query or None,
        "filters": {"identifier": identifier, "form": form, "kind": kinds[0] if len(kinds) == 1 else kinds or None},
        "artifacts": [_artifact_projection(root, row) for row in rows],
        "pagination": {
            "limit": limit,
            "cursor": str(cursor) if cursor else None,
            "returned_count": len(rows),
            "next_cursor": str(next_cursor) if next_cursor is not None else None,
            "has_more": next_cursor is not None,
            "total_count": total,
        },
        "registry_initialized": True,
    }


def list_key_filings(root: Path, args: list[str]) -> dict[str, Any]:
    identifier = _option(args, "--identifier")
    conn = _connect_existing(root)
    counts: dict[str, int] = {form: 0 for form in CRITICAL_FORM_SET}
    latest: dict[str, dict[str, Any]] = {}
    if conn is not None:
        where = "WHERE form IN ({})".format(",".join("?" for _ in CRITICAL_FORM_SET))
        params: list[Any] = list(CRITICAL_FORM_SET)
        extra, extra_params = _identifier_filter_sql(identifier)
        where += extra
        params.extend(extra_params)
        with conn:
            for row in conn.execute(f"SELECT form, COUNT(*) AS count FROM filings {where} GROUP BY form", params):
                counts[str(row["form"])] = int(row["count"])
            for form in CRITICAL_FORM_SET:
                row = conn.execute(
                    f"""
                    SELECT f.*, COUNT(a.id) AS artifact_count
                    FROM filings f
                    LEFT JOIN artifact_files a ON a.accession = f.accession
                    {where} AND form = ?
                    GROUP BY f.accession
                    ORDER BY COALESCE(filing_date, '') DESC, accession DESC
                    LIMIT 1
                    """,
                    [*params, form],
                ).fetchone()
                if row:
                    latest[form] = _filing_projection(row)

    groups = []
    for group in KEY_FORM_GROUPS:
        forms = []
        for form in group["forms"]:
            amendments = f"{form}/A"
            forms.append(
                {
                    "form": form,
                    "available_count": counts.get(form, 0),
                    "amendment_available_count": counts.get(amendments, 0),
                    "latest_available": latest.get(form),
                    "plan_cmd": (
                        "./xctx plan stock_intelligence_hub::edgar_filing_library::download_key_filings "
                        f"--identifier {identifier or '<identifier>'} --forms {form}"
                    ),
                }
            )
        groups.append(
            {
                "id": group["id"],
                "label": group["label"],
                "why": group["why"],
                "forms": forms,
            }
        )
    return {
        "object_type": "edgar_key_filing_catalog",
        "identifier": identifier,
        "registry_initialized": conn is not None,
        "groups": groups,
        "next_moves": [
            {
                "run_cmd": (
                    "./xctx plan stock_intelligence_hub::edgar_filing_library::download_key_filings "
                    f"--identifier {identifier or 'AAPL'} --forms critical"
                )
            },
            {
                "run_cmd": (
                    "./xctx discover stock_intelligence_hub::edgar_filing_library::list_available_filings"
                    + (f" --identifier {identifier}" if identifier else "")
                )
            },
        ],
    }


def _normalize_accession(value: Any) -> str:
    accession = str(value or "").strip().replace("/", "_")
    return accession


def _safe_filename(value: Any) -> str:
    text = str(value or "").strip().replace("/", "_")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("._") or "unknown"


def _looks_like_ticker(value: Any) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,14}", str(value or "").strip()))


def _normalized_cik(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return None
    return digits.zfill(10)


def _issuer_key(metadata: dict[str, Any]) -> str:
    cik = _normalized_cik(metadata.get("cik"))
    if cik:
        return f"issuer:cik:{cik}"
    ticker = str(metadata.get("ticker") or "").strip().upper()
    if ticker:
        return f"issuer:ticker:{ticker}"
    company = str(metadata.get("company") or "unknown").strip().lower()
    return "issuer:name:" + _safe_filename(company)


def _file_kind(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name == "metadata.json" or name.endswith(".metadata.json"):
        return "metadata"
    if name.endswith("manifest.json"):
        return "manifest"
    if "section" in name:
        return "sections"
    if "structured" in name:
        return "structured"
    if suffix == ".md":
        return "markdown"
    if suffix == ".txt":
        return "text"
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"
    return "artifact"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_files_for_metadata(metadata_path: Path, accession: str) -> list[Path]:
    if metadata_path.name == "metadata.json":
        base = metadata_path.parent
        return sorted(path for path in base.rglob("*") if path.is_file())
    candidates = {metadata_path}
    prefix = accession
    for path in metadata_path.parent.glob(f"{prefix}*"):
        if path.is_file():
            candidates.add(path)
        elif path.is_dir():
            candidates.update(item for item in path.rglob("*") if item.is_file())
    return sorted(candidates)


def _metadata_candidates(source_root: Path) -> list[Path]:
    candidates: set[Path] = set()
    for path in source_root.rglob("metadata.json"):
        if path.is_file():
            candidates.add(path)
    for path in source_root.rglob("*.metadata.json"):
        if path.is_file():
            candidates.add(path)
    return sorted(candidates)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON: {path}")
    return payload


def _metadata_accession(metadata: dict[str, Any], metadata_path: Path) -> str:
    for key in ("accession", "accession_number", "accession_no"):
        value = metadata.get(key)
        if value:
            return _normalize_accession(value)
    if metadata_path.name.endswith(".metadata.json"):
        return metadata_path.name[: -len(".metadata.json")]
    return metadata_path.parent.name


def _upsert_filing(
    conn: sqlite3.Connection,
    *,
    metadata: dict[str, Any],
    artifact_dir: Path,
    artifact_files: list[Path],
    source: str,
    local_state: str,
) -> dict[str, Any]:
    now = _now()
    accession = _metadata_accession(metadata, artifact_dir / "metadata.json")
    metadata = dict(metadata)
    metadata.setdefault("accession", accession)
    form = _normalize_form(str(metadata.get("form") or "UNKNOWN"))
    cik = _normalized_cik(metadata.get("cik"))
    requested_identifier = str(metadata.get("requested_identifier") or "").strip()
    ticker = str(metadata.get("ticker") or metadata.get("symbol") or "").strip().upper() or None
    if not ticker and _looks_like_ticker(requested_identifier):
        ticker = requested_identifier.upper()
    company = str(metadata.get("company") or metadata.get("company_name") or "").strip() or None
    issuer_key = _issuer_key({**metadata, "cik": cik, "ticker": ticker, "company": company})
    conn.execute(
        """
        INSERT INTO issuers(issuer_key, cik, ticker, name, created_at, last_checked_at, source, metadata_json)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(issuer_key) DO UPDATE SET
          cik=excluded.cik,
          ticker=COALESCE(excluded.ticker, issuers.ticker),
          name=COALESCE(excluded.name, issuers.name),
          last_checked_at=excluded.last_checked_at,
          source=excluded.source,
          metadata_json=excluded.metadata_json
        """,
        (issuer_key, cik, ticker, company, now, now, source, _json(metadata)),
    )
    conn.execute(
        """
        INSERT INTO filings(
          accession, issuer_key, cik, ticker, company, form, filing_date, period_of_report,
          local_state, artifact_dir, source, created_at, last_checked_at, last_downloaded_at, metadata_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(accession) DO UPDATE SET
          issuer_key=excluded.issuer_key,
          cik=excluded.cik,
          ticker=COALESCE(excluded.ticker, filings.ticker),
          company=COALESCE(excluded.company, filings.company),
          form=excluded.form,
          filing_date=excluded.filing_date,
          period_of_report=excluded.period_of_report,
          local_state=excluded.local_state,
          artifact_dir=excluded.artifact_dir,
          source=excluded.source,
          last_checked_at=excluded.last_checked_at,
          last_downloaded_at=excluded.last_downloaded_at,
          metadata_json=excluded.metadata_json
        """,
        (
            accession,
            issuer_key,
            cik,
            ticker,
            company,
            form,
            metadata.get("filing_date"),
            metadata.get("period_of_report"),
            local_state,
            str(artifact_dir),
            source,
            now,
            now,
            now,
            _json(metadata),
        ),
    )
    conn.execute("DELETE FROM artifact_files WHERE accession = ?", (accession,))
    for path in artifact_files:
        if not path.is_file():
            continue
        conn.execute(
            """
            INSERT INTO artifact_files(accession, kind, path, bytes, sha256, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                accession,
                _file_kind(path),
                str(path),
                path.stat().st_size,
                _sha256_file(path),
                now,
            ),
        )
    return {
        "id": f"filing:{accession}",
        "accession": accession,
        "form": form,
        "filing_date": metadata.get("filing_date"),
        "period_of_report": metadata.get("period_of_report"),
        "cik": cik,
        "ticker": ticker,
        "company": company,
        "artifact_count": len([path for path in artifact_files if path.is_file()]),
        "observe_cmd": f"./xctx observe stock_intelligence_hub::edgar_filing_library filing:{accession}",
    }


def index_artifact_root(
    root: Path,
    source_root: Path,
    *,
    source: str,
    run_context: dict[str, str] | None = None,
    operation: str = "index_local_artifacts",
) -> dict[str, Any]:
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise ValueError(f"source root is not a directory: {source_root}")
    indexed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with _connect_rw(root) as conn:
        for metadata_path in _metadata_candidates(source_root):
            try:
                metadata = _load_json(metadata_path)
                accession = _metadata_accession(metadata, metadata_path)
                files = _artifact_files_for_metadata(metadata_path, accession)
                artifact_dir = metadata_path.parent if metadata_path.name == "metadata.json" else metadata_path.parent
                indexed.append(
                    _upsert_filing(
                        conn,
                        metadata=metadata,
                        artifact_dir=artifact_dir,
                        artifact_files=files,
                        source=source,
                        local_state="indexed",
                    )
                )
            except Exception as exc:
                errors.append({"path": str(metadata_path), "message": str(exc)})
        status = "ok" if not errors else "partial"
        xctx = run_context or {}
        conn.execute(
            """
            INSERT OR REPLACE INTO work_runs(
              run_id, operation, identifier, forms, source, status, plan_id, commit_id, result_id,
              created_at, finished_at, summary_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                xctx.get("result_id") or f"manual:{_now()}",
                operation,
                None,
                None,
                source,
                status,
                xctx.get("plan_id"),
                xctx.get("commit_id"),
                xctx.get("result_id"),
                _now(),
                _now(),
                _json({"indexed_count": len(indexed), "error_count": len(errors)}),
            ),
        )
        conn.commit()
    return {
        "object_type": "edgar_local_artifact_index_result",
        "source_root": _display_path(root, source_root),
        "indexed_count": len(indexed),
        "error_count": len(errors),
        "indexed_filings": indexed[:25],
        "errors": errors[:10],
        "registry": registry_stats(root),
        **({"source_root_resolved_path": str(source_root)} if _detail_is_max() else {}),
    }


def _xctx_context(args: list[str]) -> dict[str, str]:
    return {
        "plan_id": str(_option(args, "--xctx-plan-id", required=True)),
        "commit_id": str(_option(args, "--xctx-commit-id", required=True)),
        "result_id": str(_option(args, "--xctx-result-id", required=True)),
    }


def _result_digest(result_id: str) -> str:
    prefix = "result:"
    value = result_id.strip().lower()
    if not value.startswith(prefix):
        raise ValueError("xctx result id must use result:<sha256>")
    digest = value[len(prefix) :]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("xctx result id must use result:<sha256>")
    return digest


def _copy_into_artifact_root(root: Path, source_root: Path, result_id: str) -> Path:
    paths = library_paths(root)
    artifact_root = paths["artifacts"].resolve()
    source = source_root.resolve()
    if source == artifact_root or artifact_root in source.parents:
        return source
    target = artifact_root / "imported" / _result_digest(result_id)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return target


def validate_index_local_artifacts(root: Path, args: list[str]) -> dict[str, Any]:
    try:
        source_root = Path(str(_option(args, "--source-root", required=True)))
        if not source_root.is_absolute():
            source_root = root / source_root
        if not source_root.is_dir():
            raise ValueError(f"source root is not a directory: {source_root}")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "object_type": "edgar_index_local_artifacts_preflight",
        "source_root": str(source_root),
    }


def commit_index_local_artifacts(root: Path, args: list[str]) -> dict[str, Any]:
    xctx = _xctx_context(args)
    source_root = Path(str(_option(args, "--source-root", required=True)))
    if not source_root.is_absolute():
        source_root = root / source_root
    indexed_root = _copy_into_artifact_root(root, source_root, xctx["result_id"])
    result = index_artifact_root(
        root,
        indexed_root,
        source="local_import",
        run_context=xctx,
        operation="index_local_artifacts",
    )
    result["result_id"] = xctx["result_id"]
    result["current_inventory_cmd"] = "./xctx discover stock_intelligence_hub::edgar_filing_library::list_available_filings"
    return result


def validate_download_key_filings(root: Path, args: list[str]) -> dict[str, Any]:
    try:
        identifier = str(_option(args, "--identifier", required=True)).strip()
        if not identifier:
            raise ValueError("--identifier cannot be empty")
        forms = parse_forms(_option(args, "--forms", "critical"))
        source = str(_option(args, "--source", "live"))
        if source not in {"live", "fixture"}:
            raise ValueError("--source must be live or fixture")
        _int_option(args, "--limit", 1, minimum=1, maximum=5)
        if source == "fixture":
            fixture_root = Path(str(_option(args, "--source-root", required=True)))
            if not fixture_root.is_absolute():
                fixture_root = root / fixture_root
            if not fixture_root.is_dir():
                raise ValueError(f"fixture source root is not a directory: {fixture_root}")
        else:
            try:
                import edgar  # noqa: F401
            except Exception as exc:
                raise ValueError(f"edgartools import failed: {exc}") from exc
            if not _edgar_identity_status()["available"]:
                raise ValueError("live EDGAR download requires EDGAR_IDENTITY or XCTX_EDGAR_IDENTITY")
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "next_moves": [
                "./xctx plan stock_intelligence_hub::edgar_filing_library::download_key_filings --identifier AAPL --forms critical",
                "./xctx plan stock_intelligence_hub::edgar_filing_library::index_local_artifacts --artifact-root <existing-edgar-artifact-root>",
            ],
        }
    return {
        "ok": True,
        "object_type": "edgar_download_key_filings_preflight",
        "identifier": identifier,
        "forms": forms,
        "source": source,
        "edgar_identity": _edgar_identity_status(),
    }


def _csv_tokens(value: str | None, default: str) -> list[str]:
    raw = str(value if value is not None else default)
    tokens: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[,;]+", raw):
        token = item.strip()
        if not token:
            continue
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def validate_company_pack(root: Path, args: list[str]) -> dict[str, Any]:
    try:
        identifier = str(_option(args, "--identifier", required=True)).strip()
        if not identifier:
            raise ValueError("--identifier cannot be empty")
        form = _normalize_form(str(_option(args, "--form", "10-K")))
        if not form:
            raise ValueError("--form cannot be empty")
        source = str(_option(args, "--source", "live"))
        if source not in {"live", "fixture"}:
            raise ValueError("--source must be live or fixture")
        items = _csv_tokens(_option(args, "--items", COMPANY_PACK_DEFAULT_ITEMS), COMPANY_PACK_DEFAULT_ITEMS)
        concepts = _csv_tokens(
            _option(args, "--concepts", COMPANY_PACK_DEFAULT_CONCEPTS),
            COMPANY_PACK_DEFAULT_CONCEPTS,
        )
        if source == "fixture":
            fixture_root = Path(str(_option(args, "--source-root", required=True)))
            if not fixture_root.is_absolute():
                fixture_root = root / fixture_root
            if not fixture_root.is_dir():
                raise ValueError(f"fixture source root is not a directory: {fixture_root}")
        else:
            try:
                import edgar  # noqa: F401
            except Exception as exc:
                raise ValueError(f"edgartools import failed: {exc}") from exc
            if not _edgar_identity_status()["available"]:
                raise ValueError("live EDGAR company pack requires EDGAR_IDENTITY or XCTX_EDGAR_IDENTITY")
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "next_moves": [
                "./xctx plan stock_intelligence_hub::edgar_filing_library::company_pack --pack-identifier AAPL --pack-form 10-K",
                "./xctx plan stock_intelligence_hub::edgar_filing_library::index_local_artifacts --artifact-root <existing-edgar-artifact-root>",
            ],
        }
    return {
        "ok": True,
        "object_type": "edgar_company_pack_preflight",
        "identifier": identifier,
        "form": form,
        "source": source,
        "items": items,
        "concepts": concepts,
        "edgar_identity": _edgar_identity_status(),
    }


def _live_identity_value() -> str:
    for key in ("EDGAR_IDENTITY", "XCTX_EDGAR_IDENTITY"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    raise ValueError("live EDGAR download requires EDGAR_IDENTITY or XCTX_EDGAR_IDENTITY")


def _filing_accession(filing: Any) -> str:
    value = (
        getattr(filing, "accession_no", None)
        or getattr(filing, "accession_number", None)
        or getattr(filing, "accession", None)
        or "filing"
    )
    return _normalize_accession(value)


def _filing_period(filing: Any) -> Any:
    for key in ("period_of_report", "report_period", "period"):
        value = getattr(filing, key, None)
        if value:
            return _json_safe(value)
    try:
        filing_dict = filing.to_dict()
    except Exception:
        filing_dict = {}
    if isinstance(filing_dict, dict):
        for key in ("period_of_report", "reportPeriod", "periodOfReport"):
            if filing_dict.get(key):
                return _json_safe(filing_dict[key])
    return None


def _filing_metadata(filing: Any, identifier: str) -> dict[str, Any]:
    metadata = {
        "company": _json_safe(getattr(filing, "company", None)),
        "cik": _json_safe(getattr(filing, "cik", None)),
        "form": _json_safe(getattr(filing, "form", None)),
        "filing_date": _json_safe(getattr(filing, "filing_date", None)),
        "period_of_report": _filing_period(filing),
        "accession": _filing_accession(filing),
        "requested_identifier": identifier,
    }
    try:
        filing_dict = filing.to_dict()
    except Exception:
        filing_dict = None
    if isinstance(filing_dict, dict):
        metadata["filing_dict"] = _json_safe(filing_dict)
    return metadata


def _ticker_for_path(identifier: str, metadata: dict[str, Any]) -> str:
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,14}", identifier or ""):
        return _safe_filename(identifier.upper())
    ticker = metadata.get("ticker") or metadata.get("symbol")
    if ticker:
        return _safe_filename(str(ticker).upper())
    return "NO_TICKER"


def _company_artifact_dir(root: Path, identifier: str, metadata: dict[str, Any]) -> Path:
    paths = library_paths(root)
    cik = _normalized_cik(metadata.get("cik")) or "unknown_cik"
    ticker = _ticker_for_path(identifier, metadata)
    accession = _normalize_accession(metadata.get("accession"))
    return paths["artifacts"] / cik / ticker / accession


def _write_text(path: Path, text: str | None) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")
    return {"path": str(path), "bytes": path.stat().st_size}


def _write_json_file(path: Path, value: Any) -> dict[str, Any]:
    return _write_text(path, _pretty_json(value))


def _dataframe_shape(dataframe: Any) -> tuple[int | None, list[str]]:
    shape = getattr(dataframe, "shape", None)
    row_count = int(shape[0]) if isinstance(shape, tuple) and shape else None
    columns = [str(column) for column in getattr(dataframe, "columns", [])]
    return row_count, columns


def _write_dataframe_files(base: Path, dataframe: Any) -> dict[str, Any]:
    base.parent.mkdir(parents=True, exist_ok=True)
    row_count, columns = _dataframe_shape(dataframe)
    csv_path = base.with_suffix(".csv")
    json_path = base.with_suffix(".json")
    result: dict[str, Any] = {"rows": row_count, "columns": columns}
    try:
        dataframe.to_csv(csv_path, index=False)
        result["csv"] = {"path": str(csv_path), "bytes": csv_path.stat().st_size}
    except Exception as exc:
        result["csv_error"] = str(exc)
    try:
        dataframe.to_json(json_path, orient="records", date_format="iso")
        result["json"] = {"path": str(json_path), "bytes": json_path.stat().st_size}
    except Exception as exc:
        result["json_error"] = str(exc)
    return result


def _statement_dataframe(statement_or_method: Any, view: str = "standard") -> tuple[Any, Any | None]:
    statement = statement_or_method() if callable(statement_or_method) else statement_or_method
    if statement is None:
        return None, None
    to_dataframe = getattr(statement, "to_dataframe", None)
    if not callable(to_dataframe):
        return statement, None
    try:
        return statement, to_dataframe(view=view)
    except TypeError:
        return statement, to_dataframe()


def _dump_company_pack(root: Path, filing: Any, identifier: str, items: list[str], concepts: list[str]) -> dict[str, Any]:
    metadata = _filing_metadata(filing, identifier)
    artifact_dir = _company_artifact_dir(root, identifier, metadata)
    base_row = _dump_live_filing(root, filing, identifier)
    files = sorted(path for path in artifact_dir.rglob("*") if path.is_file())
    errors: list[dict[str, str]] = list(base_row.get("errors") or [])

    sections_manifest = {
        "success": True,
        "requested_items": items,
        "source": "filing.md",
        "note": "Section body extraction is intentionally deferred; filing.md and sections.txt are indexed for observation.",
    }
    _write_json_file(artifact_dir / "sections" / "manifest.json", sections_manifest)

    statement_files: dict[str, Any] = {}
    try:
        obj = filing.obj()
        financials = getattr(obj, "financials", None) if obj else None
        if financials:
            statements_base = artifact_dir / "statements"
            for name in ("income_statement", "balance_sheet", "cash_flow_statement"):
                statement, dataframe = _statement_dataframe(getattr(financials, name, None))
                entry: dict[str, Any] = {}
                if dataframe is not None:
                    entry.update(_write_dataframe_files(statements_base / name, dataframe))
                to_markdown = getattr(statement, "to_markdown", None)
                if callable(to_markdown):
                    try:
                        entry["markdown"] = _write_text((statements_base / name).with_suffix(".md"), to_markdown())
                    except Exception as exc:
                        entry["markdown_error"] = str(exc)
                if entry:
                    statement_files[name] = entry
        else:
            statement_files["skipped"] = "filing object did not expose financial statements"
    except Exception as exc:
        statement_files["error"] = str(exc)
        errors.append({"path": "statements", "message": str(exc)})
    _write_json_file(artifact_dir / "statements" / "manifest.json", {"success": "error" not in statement_files, "files": statement_files})

    fact_files: dict[str, Any] = {}
    try:
        xbrl = filing.xbrl()
        if xbrl is None:
            fact_files["skipped"] = "filing.xbrl() returned None"
        else:
            facts_base = artifact_dir / "facts"
            for concept in concepts:
                query_concept = concept if ":" in concept else f"us-gaap:{concept}"
                try:
                    dataframe = xbrl.query().by_concept(query_concept, exact=True).to_dataframe()
                    fact_files[concept] = {
                        "query_concept": query_concept,
                        **_write_dataframe_files(facts_base / _safe_filename(query_concept), dataframe),
                    }
                except Exception as exc:
                    fact_files[concept] = {"query_concept": query_concept, "error": str(exc)}
    except Exception as exc:
        fact_files["error"] = str(exc)
        errors.append({"path": "facts", "message": str(exc)})
    _write_json_file(artifact_dir / "facts" / "manifest.json", {"success": "error" not in fact_files, "files": fact_files})

    manifest = {
        "success": not errors,
        "metadata": metadata,
        "dump": {
            "filing_id": base_row["id"],
            "artifact_dir": str(artifact_dir),
        },
        "sections": sections_manifest,
        "statements": statement_files,
        "facts": fact_files,
        "requested_items": items,
        "requested_concepts": concepts,
        "errors": errors,
        "generated_at_utc": _now(),
    }
    manifest_file = artifact_dir / "company_pack_manifest.json"
    _write_json_file(manifest_file, manifest)
    files = sorted(path for path in artifact_dir.rglob("*") if path.is_file())
    with _connect_rw(root) as conn:
        row = _upsert_filing(
            conn,
            metadata=metadata,
            artifact_dir=artifact_dir,
            artifact_files=files,
            source="live_edgar_company_pack",
            local_state="downloaded",
        )
        conn.commit()
    row["company_pack_manifest"] = _display_path(root, manifest_file)
    if _detail_is_max():
        row["company_pack_manifest_resolved_path"] = str(manifest_file.resolve())
    row["errors"] = errors
    return row


def _dump_live_filing(root: Path, filing: Any, identifier: str) -> dict[str, Any]:
    metadata = _filing_metadata(filing, identifier)
    artifact_dir = _company_artifact_dir(root, identifier, metadata)
    files: list[Path] = []
    metadata_file = artifact_dir / "metadata.json"
    _write_text(metadata_file, _pretty_json(metadata))
    files.append(metadata_file)
    errors: list[dict[str, str]] = []

    for kind, filename, producer in (
        ("markdown", "filing.md", lambda: filing.markdown(include_page_breaks=True)),
        ("text", "filing.txt", lambda: filing.text()),
    ):
        try:
            value = producer()
            path = artifact_dir / filename
            _write_text(path, str(value or ""))
            files.append(path)
        except Exception as exc:
            errors.append({"path": kind, "message": str(exc)})

    sections = getattr(filing, "sections", None)
    if callable(sections):
        try:
            value = "\n".join(str(item) for item in sections())
            path = artifact_dir / "sections.txt"
            _write_text(path, value)
            files.append(path)
        except Exception as exc:
            errors.append({"path": "sections", "message": str(exc)})

    manifest = {
        "success": not errors,
        "metadata": metadata,
        "artifact_dir": str(artifact_dir),
        "files": [str(path) for path in files],
        "errors": errors,
        "generated_at_utc": _now(),
    }
    manifest_file = artifact_dir / "manifest.json"
    _write_text(manifest_file, _pretty_json(manifest))
    files.append(manifest_file)
    with _connect_rw(root) as conn:
        row = _upsert_filing(
            conn,
            metadata=metadata,
            artifact_dir=artifact_dir,
            artifact_files=files,
            source="live_edgar",
            local_state="downloaded",
        )
        conn.commit()
    row["errors"] = errors
    return row


def _as_filing_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except TypeError:
        return [value]


def _download_live_filings(root: Path, identifier: str, forms: list[str], limit: int, xctx: dict[str, str]) -> dict[str, Any]:
    from edgar import Company, set_identity

    set_identity(_live_identity_value())
    company = Company(identifier)
    downloaded: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    for form in forms:
        try:
            rows = _as_filing_list(company.get_filings(form=form, amendments=True).latest(limit))
        except Exception as exc:
            unavailable.append({"form": form, "message": str(exc)})
            continue
        if not rows:
            unavailable.append({"form": form, "message": "no filings found"})
            continue
        for filing in rows[:limit]:
            try:
                downloaded.append(_dump_live_filing(root, filing, identifier))
            except Exception as exc:
                unavailable.append({"form": form, "message": str(exc)})

    status = "ok" if downloaded and not unavailable else ("partial" if downloaded else "error")
    with _connect_rw(root) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO work_runs(
              run_id, operation, identifier, forms, source, status, plan_id, commit_id, result_id,
              created_at, finished_at, summary_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                xctx["result_id"],
                "download_key_filings",
                identifier,
                ",".join(forms),
                "live",
                status,
                xctx["plan_id"],
                xctx["commit_id"],
                xctx["result_id"],
                _now(),
                _now(),
                _json({"downloaded_count": len(downloaded), "unavailable_count": len(unavailable)}),
            ),
        )
        conn.commit()
    return {
        "object_type": "edgar_key_filings_download_result",
        "source": "live",
        "identifier": identifier,
        "forms_requested": forms,
        "downloaded_count": len(downloaded),
        "unavailable_count": len(unavailable),
        "downloaded_filings": downloaded[:50],
        "unavailable": unavailable[:50],
        "registry": registry_stats(root),
    }


def _download_live_company_pack(
    root: Path,
    identifier: str,
    form: str,
    items: list[str],
    concepts: list[str],
    xctx: dict[str, str],
) -> dict[str, Any]:
    from edgar import Company, set_identity

    set_identity(_live_identity_value())
    company = Company(identifier)
    unavailable: list[dict[str, str]] = []
    downloaded: list[dict[str, Any]] = []
    try:
        rows = _as_filing_list(company.get_filings(form=form, amendments=True).latest(1))
    except Exception as exc:
        rows = []
        unavailable.append({"form": form, "message": str(exc)})
    if not rows:
        unavailable.append({"form": form, "message": "no filings found"})
    for filing in rows[:1]:
        try:
            downloaded.append(_dump_company_pack(root, filing, identifier, items, concepts))
        except Exception as exc:
            unavailable.append({"form": form, "message": str(exc)})

    status = "ok" if downloaded and not unavailable else ("partial" if downloaded else "error")
    with _connect_rw(root) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO work_runs(
              run_id, operation, identifier, forms, source, status, plan_id, commit_id, result_id,
              created_at, finished_at, summary_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                xctx["result_id"],
                "company_pack",
                identifier,
                form,
                "live",
                status,
                xctx["plan_id"],
                xctx["commit_id"],
                xctx["result_id"],
                _now(),
                _now(),
                _json({"downloaded_count": len(downloaded), "unavailable_count": len(unavailable)}),
            ),
        )
        conn.commit()
    return {
        "object_type": "edgar_company_pack_result",
        "source": "live",
        "identifier": identifier,
        "form_requested": form,
        "items_requested": items,
        "concepts_requested": concepts,
        "downloaded_count": len(downloaded),
        "unavailable_count": len(unavailable),
        "downloaded_filings": downloaded[:5],
        "unavailable": unavailable[:10],
        "registry": registry_stats(root),
    }


def commit_company_pack(root: Path, args: list[str]) -> dict[str, Any]:
    xctx = _xctx_context(args)
    identifier = str(_option(args, "--identifier", required=True)).strip()
    form = _normalize_form(str(_option(args, "--form", "10-K")))
    source = str(_option(args, "--source", "live"))
    items = _csv_tokens(_option(args, "--items", COMPANY_PACK_DEFAULT_ITEMS), COMPANY_PACK_DEFAULT_ITEMS)
    concepts = _csv_tokens(_option(args, "--concepts", COMPANY_PACK_DEFAULT_CONCEPTS), COMPANY_PACK_DEFAULT_CONCEPTS)
    if source == "fixture":
        source_root = Path(str(_option(args, "--source-root", required=True)))
        if not source_root.is_absolute():
            source_root = root / source_root
        indexed_root = _copy_into_artifact_root(root, source_root, xctx["result_id"])
        result = index_artifact_root(
            root,
            indexed_root,
            source="fixture_company_pack",
            run_context=xctx,
            operation="company_pack",
        )
        result.update(
            {
                "object_type": "edgar_company_pack_result",
                "source": "fixture",
                "identifier": identifier,
                "form_requested": form,
                "items_requested": items,
                "concepts_requested": concepts,
                "result_id": xctx["result_id"],
                "artifact_inventory_cmd": (
                    "./xctx discover stock_intelligence_hub::edgar_filing_library::list_artifacts "
                    f"--identifier {identifier} --kind csv"
                ),
            }
        )
        return result
    if source != "live":
        raise ValueError("--source must be live or fixture")
    result = _download_live_company_pack(root, identifier, form, items, concepts, xctx)
    result["result_id"] = xctx["result_id"]
    result["artifact_inventory_cmd"] = (
        "./xctx discover stock_intelligence_hub::edgar_filing_library::list_artifacts "
        f"--identifier {identifier} --kind csv"
    )
    return result


def commit_download_key_filings(root: Path, args: list[str]) -> dict[str, Any]:
    xctx = _xctx_context(args)
    identifier = str(_option(args, "--identifier", required=True)).strip()
    forms = parse_forms(_option(args, "--forms", "critical"))
    source = str(_option(args, "--source", "live"))
    limit = _int_option(args, "--limit", 1, minimum=1, maximum=5)
    if source == "fixture":
        source_root = Path(str(_option(args, "--source-root", required=True)))
        if not source_root.is_absolute():
            source_root = root / source_root
        indexed_root = _copy_into_artifact_root(root, source_root, xctx["result_id"])
        result = index_artifact_root(
            root,
            indexed_root,
            source="fixture_download",
            run_context=xctx,
            operation="download_key_filings",
        )
        result.update(
            {
                "object_type": "edgar_key_filings_download_result",
                "source": "fixture",
                "identifier": identifier,
                "forms_requested": forms,
                "result_id": xctx["result_id"],
            }
        )
        return result
    if source != "live":
        raise ValueError("--source must be live or fixture")
    result = _download_live_filings(root, identifier, forms, limit, xctx)
    result["result_id"] = xctx["result_id"]
    result["current_inventory_cmd"] = (
        "./xctx discover stock_intelligence_hub::edgar_filing_library::list_available_filings "
        f"--identifier {identifier}"
    )
    return result


def _artifact_rows(root: Path, conn: sqlite3.Connection, accession: str) -> list[dict[str, Any]]:
    return [
        _artifact_row_payload(root, row)
        for row in conn.execute(
            "SELECT id, kind, path, bytes, sha256 FROM artifact_files WHERE accession = ? ORDER BY kind, path",
            (accession,),
        )
    ]


def _artifact_row_payload(root: Path, row: sqlite3.Row) -> dict[str, Any]:
    path = Path(str(row["path"]))
    payload = {
        "id": f"artifact_file:{row['id']}",
        "kind": row["kind"],
        **_path_fields(root, path),
        "bytes": row["bytes"],
        "sha256": row["sha256"],
        "_local_path": str(path),
    }
    return payload


def _public_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in artifact.items() if not str(key).startswith("_")} for artifact in artifacts]


def _preview_artifact(root: Path, artifacts: list[dict[str, Any]], preview_chars: int) -> dict[str, Any] | None:
    if preview_chars <= 0:
        return None
    for artifact in artifacts:
        if artifact["kind"] not in {"markdown", "text"}:
            continue
        path = Path(str(artifact.get("_local_path") or artifact["path"]))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        return {
            "artifact_id": artifact["id"],
            "kind": artifact["kind"],
            **_path_fields(root, path),
            "chars_returned": min(preview_chars, len(text)),
            "truncated": len(text) > preview_chars,
            "text": text[:preview_chars],
        }
    return None


def _bounded_text_preview(root: Path, path: Path, preview_chars: int) -> dict[str, Any] | None:
    if preview_chars <= 0:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return {
        **_path_fields(root, path),
        "chars_returned": min(preview_chars, len(text)),
        "truncated": len(text) > preview_chars,
        "text": text[:preview_chars],
    }


def _csv_preview(root: Path, path: Path, max_rows: int = 6) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            rows: list[list[str]] = []
            truncated = False
            for index, row in enumerate(reader):
                if index >= max_rows:
                    truncated = True
                    break
                rows.append([str(item) for item in row])
    except OSError:
        return None
    return {
        **_path_fields(root, path),
        "rows_returned": len(rows),
        "truncated": truncated,
        "columns": rows[0] if rows else [],
        "rows": rows[1:] if rows else [],
    }


def _json_preview(root: Path, path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(value, dict):
        return {
            **_path_fields(root, path),
            "json_type": "object",
            "top_level_keys": sorted(str(key) for key in value.keys())[:25],
            "key_count": len(value),
        }
    if isinstance(value, list):
        return {
            **_path_fields(root, path),
            "json_type": "array",
            "item_count": len(value),
            "first_item_type": type(value[0]).__name__ if value else None,
        }
    return {**_path_fields(root, path), "json_type": type(value).__name__}


def _artifact_numeric_id(target: str) -> int | None:
    for prefix in ("artifact_file:", "artifact:"):
        if target.startswith(prefix):
            value = target[len(prefix) :]
            return int(value) if value.isdigit() else None
    return None


def _observe_artifact_file(root: Path, artifact_id: int, preview_chars: int) -> dict[str, Any]:
    conn = _connect_existing(root)
    if conn is None:
        return {
            "ok": False,
            "object_type": "edgar_filing_library_error",
            "error": "filing registry is not initialized",
            "next_moves": [
                "./xctx plan stock_intelligence_hub::edgar_filing_library::index_local_artifacts --artifact-root <existing-edgar-artifact-root>"
            ],
        }
    with conn:
        row = conn.execute(
            """
            SELECT
              a.id AS artifact_id,
              a.accession,
              a.kind,
              a.path,
              a.bytes,
              a.sha256,
              f.form,
              f.filing_date,
              f.period_of_report,
              f.cik,
              f.ticker,
              f.company
            FROM artifact_files a
            JOIN filings f ON f.accession = a.accession
            WHERE a.id = ?
            """,
            (artifact_id,),
        ).fetchone()
    if row is None:
        return {
            "ok": False,
            "object_type": "edgar_filing_library_error",
            "error": f"unknown artifact file id: {artifact_id}",
            "next_moves": ["./xctx discover stock_intelligence_hub::edgar_filing_library::list_artifacts"],
        }
    artifact = _artifact_projection(root, row)
    path = Path(str(row["path"]))
    payload: dict[str, Any] = {
        "object_type": "edgar_artifact_file_observation",
        "id": artifact["id"],
        "artifact": artifact,
        "exists": path.exists(),
        "data_boundary": "Artifact observation returns metadata plus bounded previews for text, CSV, and JSON files.",
    }
    if path.exists() and artifact["kind"] == "csv":
        payload["csv_preview"] = _csv_preview(root, path)
    if path.exists() and artifact["kind"] in {"json", "manifest", "metadata", "structured"}:
        payload["json_preview"] = _json_preview(root, path)
    preview = _bounded_text_preview(root, path, preview_chars)
    if preview:
        payload["bounded_preview"] = {**preview, "kind": artifact["kind"]}
    return payload


def observe_filing(root: Path, identifier: str, args: list[str]) -> dict[str, Any]:
    target = identifier.strip()
    preview_chars = _int_option(args, "--preview-chars", 0, minimum=0, maximum=2000)
    if not target or target == "status":
        return {
            "object_type": "edgar_filing_library_status",
            "stats": registry_stats(root),
            "next_moves": [
                "./xctx discover stock_intelligence_hub::edgar_filing_library::list_available_filings",
                "./xctx plan stock_intelligence_hub::edgar_filing_library::download_key_filings --identifier AAPL --forms critical",
            ],
        }
    artifact_id = _artifact_numeric_id(target)
    if artifact_id is not None:
        return _observe_artifact_file(root, artifact_id, preview_chars)
    if target.startswith(("artifact_file:", "artifact:")):
        return {
            "ok": False,
            "object_type": "edgar_filing_library_error",
            "error": f"invalid artifact file ref: {target}",
            "next_moves": ["./xctx discover stock_intelligence_hub::edgar_filing_library::list_artifacts"],
        }
    accession = target[len("filing:") :] if target.startswith("filing:") else target
    accession = _normalize_accession(accession)
    conn = _connect_existing(root)
    if conn is None:
        return {
            "ok": False,
            "object_type": "edgar_filing_library_error",
            "error": "filing registry is not initialized",
            "next_moves": [
                "./xctx plan stock_intelligence_hub::edgar_filing_library::download_key_filings --identifier AAPL --forms critical"
            ],
        }
    with conn:
        row = conn.execute("SELECT * FROM filings WHERE accession = ?", (accession,)).fetchone()
        if row is None:
            return {
                "ok": False,
                "object_type": "edgar_filing_library_error",
                "error": f"unknown filing accession: {accession}",
                "next_moves": [
                    "./xctx discover stock_intelligence_hub::edgar_filing_library::list_available_filings",
                    "./xctx plan stock_intelligence_hub::edgar_filing_library::download_key_filings --identifier AAPL --forms critical",
                ],
            }
        artifacts = _artifact_rows(root, conn, accession)
    metadata = json.loads(row["metadata_json"] or "{}")
    artifact_dir = Path(str(row["artifact_dir"])) if row["artifact_dir"] else Path("")
    payload = {
        "object_type": "edgar_filing_observation",
        "id": f"filing:{accession}",
        "accession": accession,
        "form": row["form"],
        "filing_date": row["filing_date"],
        "period_of_report": row["period_of_report"],
        "issuer": {
            "cik": row["cik"],
            "ticker": row["ticker"],
            "company": row["company"],
        },
        "local_state": row["local_state"],
        **({"artifact_dir": _display_path(root, artifact_dir)} if row["artifact_dir"] else {"artifact_dir": None}),
        "metadata": metadata,
        "artifact_count": len(artifacts),
        "artifacts": _public_artifacts(artifacts),
        "data_boundary": "Observation returns metadata and bounded artifact references. Full filing bodies remain files on disk.",
    }
    if _detail_is_max() and row["artifact_dir"]:
        payload["resolved_path"] = str(artifact_dir.resolve())
    preview = _preview_artifact(root, artifacts, preview_chars)
    if preview:
        payload["bounded_preview"] = preview
    return payload


def filing_audit(root: Path) -> dict[str, Any]:
    stats = registry_stats(root)
    paths = library_paths(root)
    checks = [
        {
            "id": "audit:edgar_filing_library:registry_path_configured",
            "status": "pass",
            "path": _display_path(root, paths["registry"]),
        },
        {
            "id": "audit:edgar_filing_library:artifact_root_configured",
            "status": "pass",
            "path": _display_path(root, paths["artifacts"]),
        },
        {
            "id": "audit:edgar_filing_library:registry_initialized",
            "status": "pass",
            "value": stats["registry_initialized"],
            "note": "An empty or uninitialized filing registry is valid before the first planned acquisition/index run.",
        },
        {
            "id": "audit:edgar_filing_library:edgartools_import",
            "status": "pass" if _edgartools_importable() else "warn",
        },
        {
            "id": "audit:edgar_filing_library:edgar_identity",
            "status": "pass",
            "available": _edgar_identity_status()["available"],
            "value_printed": False,
        },
    ]
    return {
        "object_type": "edgar_filing_library_audit",
        "checks": checks,
        "stats": stats,
    }


def _edgartools_importable() -> bool:
    try:
        import edgar  # noqa: F401
    except Exception:
        return False
    return True
