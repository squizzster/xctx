from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from xctx_live.instruments import find_instrument, public_instrument, search_instruments

SQLITE_PATH = Path("data/edgar_form_reference_taxonomy.sqlite")
LIST_DEFAULT_LIMIT = 25
LIST_MAX_LIMIT = 100


def sqlite_path(root: Path) -> Path:
    return root / SQLITE_PATH


def connect(root: Path) -> sqlite3.Connection:
    path = sqlite_path(root)
    if not path.exists():
        raise FileNotFoundError(f"filing taxonomy sqlite not found: {path}")
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def stats(root: Path) -> dict[str, Any]:
    with connect(root) as conn:
        return {
            "total_lookup_filings": conn.execute("SELECT COUNT(*) FROM forms").fetchone()[0],
            "canonical_families": conn.execute("SELECT COUNT(*) FROM canonical_families").fetchone()[0],
            "priority_buckets": conn.execute("SELECT COUNT(*) FROM priority_buckets").fetchone()[0],
            "category_labels": conn.execute("SELECT COUNT(DISTINCT sec_edgarlink_category) FROM forms WHERE sec_edgarlink_category IS NOT NULL AND TRIM(sec_edgarlink_category) != ''").fetchone()[0],
            "amendment_forms": conn.execute("SELECT COALESCE(SUM(is_amendment), 0) FROM forms").fetchone()[0],
            "storage_engine": "sqlite",
            "read_only": True,
            "database_path": str(SQLITE_PATH),
        }


def form_projection(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    form_code = d.get("form_code")
    return {
        "id": f"form:{form_code}",
        "form_code": form_code,
        "name": d.get("name"),
        "canonical_family": {
            "id": f"family:{d.get('family_code')}",
            "code": d.get("family_code"),
            "name": d.get("family_name"),
        },
        "priority_bucket": {
            "id": f"priority:{d.get('priority_code')}",
            "code": d.get("priority_code"),
            "name": d.get("priority_name"),
        },
        "is_amendment": bool(d.get("is_amendment")),
        "sec_edgarlink_category": d.get("sec_edgarlink_category"),
        "run_cmd": f"./xctx observe stock_intelligence_hub::equity_filing form:{form_code}",
    }


def compact_form_projection(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    form_code = d.get("form_code")
    family = d.get("family_code")
    priority = d.get("priority_code")
    if family is None and isinstance(d.get("canonical_family"), dict):
        family = d["canonical_family"].get("code")
    if priority is None and isinstance(d.get("priority_bucket"), dict):
        priority = d["priority_bucket"].get("code")
    return {
        "id": f"form:{form_code}",
        "form_code": form_code,
        "name": d.get("name"),
        "family": family,
        "priority": priority,
        "is_amendment": bool(d.get("is_amendment")),
    }


def compact_family_projection(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    return {
        "id": f"family:{d.get('code')}",
        "code": d.get("code"),
        "name": d.get("name"),
        "form_count": d.get("form_count"),
    }


def compact_priority_projection(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    return {
        "id": f"priority:{d.get('code')}",
        "code": d.get("code"),
        "name": d.get("name"),
        "form_count": d.get("form_count"),
    }


def pagination_payload(
    *,
    limit: int,
    cursor: int | None,
    returned_count: int,
    total_count: int,
    next_cursor: int | None,
) -> dict[str, Any]:
    return {
        "limit": limit,
        "returned_count": returned_count,
        "cursor": str(cursor) if cursor else None,
        "next_cursor": str(next_cursor) if next_cursor is not None else None,
        "has_more": next_cursor is not None,
        "total_count": total_count,
    }


def list_page_run_cmd(action: str, *, limit: int, cursor: int | None, shape: str) -> str:
    parts = [f"./xctx discover stock_intelligence_hub::equity_filing {action}"]
    if limit != LIST_DEFAULT_LIMIT:
        parts.append(f"--limit {limit}")
    if cursor is not None:
        parts.append(f"--cursor {cursor}")
    if shape != "compact":
        parts.append(f"--shape {shape}")
    return " ".join(parts)


def _form_join_sql(where: str = "") -> str:
    base = """
        SELECT
          f.id,
          f.form_code,
          f.name,
          f.description,
          f.when_to_use,
          f.is_amendment,
          f.sec_edgarlink_category,
          f.created_at,
          f.updated_at,
          cf.code AS family_code,
          cf.name AS family_name,
          cf.description AS family_description,
          cf.sort_order AS family_sort_order,
          pb.code AS priority_code,
          pb.name AS priority_name,
          pb.sort_order AS priority_sort_order
        FROM forms f
        JOIN canonical_families cf ON cf.id = f.canonical_families_id
        JOIN priority_buckets pb ON pb.id = f.priority_buckets_id
    """
    return base + (" " + where if where else "")


def _exact_form_code_rows(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    exact = conn.execute(_form_join_sql("WHERE lower(f.form_code) = lower(?) LIMIT 1"), (query,)).fetchone()
    if not exact:
        return []
    form_code = str(exact["form_code"])
    if form_code.lower().endswith("/a"):
        return [exact]
    amendment_code = f"{form_code}/A"
    return conn.execute(
        _form_join_sql(
            """
            WHERE lower(f.form_code) IN (lower(?), lower(?))
            ORDER BY
              CASE WHEN lower(f.form_code) = lower(?) THEN 0 ELSE 1 END,
              f.form_code
            """
        ),
        (form_code, amendment_code, form_code),
    ).fetchall()


def search_forms(root: Path, query: str, limit: int = 25) -> list[dict[str, Any]]:
    query = query.strip()
    with connect(root) as conn:
        if not query:
            rows = conn.execute(_form_join_sql("ORDER BY pb.sort_order, cf.sort_order, f.form_code LIMIT ?"), (limit,)).fetchall()
        else:
            rows = _exact_form_code_rows(conn, query)
            if not rows:
                like = f"%{query.lower()}%"
                rows = conn.execute(
                    _form_join_sql(
                        """
                        WHERE lower(f.form_code) LIKE ?
                           OR lower(f.name) LIKE ?
                           OR lower(f.description) LIKE ?
                           OR lower(f.when_to_use) LIKE ?
                           OR lower(COALESCE(f.sec_edgarlink_category, '')) LIKE ?
                           OR lower(cf.code) LIKE ?
                           OR lower(cf.name) LIKE ?
                           OR lower(cf.description) LIKE ?
                           OR lower(pb.code) LIKE ?
                           OR lower(pb.name) LIKE ?
                        """
                    ),
                    (like, like, like, like, like, like, like, like, like, like),
                ).fetchall()
        q = query.lower()
        projected: list[dict[str, Any]] = []
        for row in rows:
            item = form_projection(row)
            score = 100
            if q and q == str(row["form_code"]).lower():
                score = 0
            elif q and str(row["form_code"]).lower().startswith(q):
                score = 5
            elif q and q in str(row["name"]).lower():
                score = 10
            elif q and q in str(row["family_code"]).lower():
                score = 20
            elif q and q in str(row["priority_code"]).lower():
                score = 30
            item["_score"] = score
            projected.append(item)
        projected.sort(key=lambda item: (item.pop("_score"), item.get("form_code", "")))
        return projected[:limit]


def search_families(root: Path, query: str, limit: int = 25) -> list[dict[str, Any]]:
    query = query.strip().lower()
    with connect(root) as conn:
        params: tuple[Any, ...] = ()
        where = ""
        if query:
            exact = conn.execute(
                "SELECT id FROM canonical_families WHERE lower(code) = lower(?) LIMIT 1",
                (query,),
            ).fetchone()
            if exact:
                where = "WHERE cf.id = ?"
                params = (exact["id"],)
            else:
                like = f"%{query}%"
                where = "WHERE lower(cf.code) LIKE ? OR lower(cf.name) LIKE ? OR lower(cf.description) LIKE ?"
                params = (like, like, like)
        rows = conn.execute(
            f"""
            SELECT cf.*, COUNT(f.id) AS form_count
            FROM canonical_families cf
            LEFT JOIN forms f ON f.canonical_families_id = cf.id
            {where}
            GROUP BY cf.id
            ORDER BY cf.sort_order
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    return [
        {
            "id": f"family:{row['code']}",
            "code": row["code"],
            "name": row["name"],
            "description": row["description"],
            "form_count": row["form_count"],
            "run_cmd": f"./xctx observe stock_intelligence_hub::equity_filing family:{row['code']}",
        }
        for row in rows
    ]


def search_priority_buckets(root: Path, query: str, limit: int = 25) -> list[dict[str, Any]]:
    query = query.strip().lower()
    with connect(root) as conn:
        params: tuple[Any, ...] = ()
        where = ""
        if query:
            exact = conn.execute(
                "SELECT id FROM priority_buckets WHERE lower(code) = lower(?) LIMIT 1",
                (query,),
            ).fetchone()
            if exact:
                where = "WHERE pb.id = ?"
                params = (exact["id"],)
            else:
                like = f"%{query}%"
                where = "WHERE lower(pb.code) LIKE ? OR lower(pb.name) LIKE ?"
                params = (like, like)
        rows = conn.execute(
            f"""
            SELECT pb.*, COUNT(f.id) AS form_count
            FROM priority_buckets pb
            LEFT JOIN forms f ON f.priority_buckets_id = pb.id
            {where}
            GROUP BY pb.id
            ORDER BY pb.sort_order
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    return [
        {
            "id": f"priority:{row['code']}",
            "code": row["code"],
            "name": row["name"],
            "form_count": row["form_count"],
            "run_cmd": f"./xctx observe stock_intelligence_hub::equity_filing priority:{row['code']}",
        }
        for row in rows
    ]


def list_forms(root: Path, *, limit: int = LIST_DEFAULT_LIMIT, cursor: int = 0, shape: str = "compact") -> dict[str, Any]:
    with connect(root) as conn:
        total = conn.execute("SELECT COUNT(*) FROM forms").fetchone()[0]
        rows = conn.execute(
            _form_join_sql("ORDER BY pb.sort_order, cf.sort_order, f.form_code LIMIT ? OFFSET ?"),
            (limit, cursor),
        ).fetchall()
    next_cursor = cursor + limit if cursor + limit < total else None
    projection = form_projection if shape == "full" else compact_form_projection
    pagination = pagination_payload(
        limit=limit,
        cursor=cursor,
        returned_count=len(rows),
        total_count=total,
        next_cursor=next_cursor,
    )
    next_moves = [
        "./xctx discover stock_intelligence_hub::equity_filing::search_forms",
        "./xctx discover stock_intelligence_hub::equity_filing search_forms <form code|text>",
    ]
    if next_cursor is not None:
        next_moves.append(list_page_run_cmd("list_forms", limit=limit, cursor=next_cursor, shape=shape))
    return {
        "object_type": "equity_filing_form_list",
        "description": "Compact bounded index of SEC/EDGAR filing form taxonomy records.",
        "shape": shape,
        "observe_shape": "./xctx observe stock_intelligence_hub::equity_filing form:<form_code>",
        "total_count": total,
        "returned_count": len(rows),
        "limit": limit,
        "cursor": str(cursor) if cursor else None,
        "next_cursor": str(next_cursor) if next_cursor is not None else None,
        "pagination": pagination,
        "forms": [projection(row) for row in rows],
        "next_moves": next_moves,
    }


def list_families(root: Path, *, limit: int = LIST_DEFAULT_LIMIT, cursor: int = 0, shape: str = "compact") -> dict[str, Any]:
    with connect(root) as conn:
        total = conn.execute("SELECT COUNT(*) FROM canonical_families").fetchone()[0]
        rows = conn.execute(
            """
            SELECT cf.*, COUNT(f.id) AS form_count
            FROM canonical_families cf
            LEFT JOIN forms f ON f.canonical_families_id = cf.id
            GROUP BY cf.id
            ORDER BY cf.sort_order
            LIMIT ? OFFSET ?
            """,
            (limit, cursor),
        ).fetchall()
    next_cursor = cursor + limit if cursor + limit < total else None
    projection = (
        lambda row: {
            "id": f"family:{row['code']}",
            "code": row["code"],
            "name": row["name"],
            "description": row["description"],
            "form_count": row["form_count"],
            "run_cmd": f"./xctx observe stock_intelligence_hub::equity_filing family:{row['code']}",
        }
    ) if shape == "full" else compact_family_projection
    pagination = pagination_payload(
        limit=limit,
        cursor=cursor,
        returned_count=len(rows),
        total_count=total,
        next_cursor=next_cursor,
    )
    next_moves = [
        "./xctx discover stock_intelligence_hub::equity_filing::search_families",
        "./xctx discover stock_intelligence_hub::equity_filing search_families <family|text>",
    ]
    if next_cursor is not None:
        next_moves.append(list_page_run_cmd("list_families", limit=limit, cursor=next_cursor, shape=shape))
    return {
        "object_type": "equity_filing_family_list",
        "description": "Compact bounded index of canonical filing families.",
        "shape": shape,
        "observe_shape": "./xctx observe stock_intelligence_hub::equity_filing family:<family_code>",
        "total_count": total,
        "returned_count": len(rows),
        "limit": limit,
        "cursor": str(cursor) if cursor else None,
        "next_cursor": str(next_cursor) if next_cursor is not None else None,
        "pagination": pagination,
        "families": [projection(row) for row in rows],
        "next_moves": next_moves,
    }


def list_priority_buckets(root: Path, *, limit: int = LIST_DEFAULT_LIMIT, shape: str = "compact") -> dict[str, Any]:
    with connect(root) as conn:
        total = conn.execute("SELECT COUNT(*) FROM priority_buckets").fetchone()[0]
        rows = conn.execute(
            """
            SELECT pb.*, COUNT(f.id) AS form_count
            FROM priority_buckets pb
            LEFT JOIN forms f ON f.priority_buckets_id = pb.id
            GROUP BY pb.id
            ORDER BY pb.sort_order
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    projection = (
        lambda row: {
            "id": f"priority:{row['code']}",
            "code": row["code"],
            "name": row["name"],
            "form_count": row["form_count"],
            "run_cmd": f"./xctx observe stock_intelligence_hub::equity_filing priority:{row['code']}",
        }
    ) if shape == "full" else compact_priority_projection
    pagination = pagination_payload(
        limit=limit,
        cursor=None,
        returned_count=len(rows),
        total_count=total,
        next_cursor=None,
    )
    return {
        "object_type": "equity_filing_priority_bucket_list",
        "description": "Compact bounded index of filing priority buckets.",
        "shape": shape,
        "observe_shape": "./xctx observe stock_intelligence_hub::equity_filing priority:<priority_code>",
        "total_count": total,
        "returned_count": len(rows),
        "limit": limit,
        "pagination": pagination,
        "priority_buckets": [projection(row) for row in rows],
        "next_moves": [
            "./xctx discover stock_intelligence_hub::equity_filing::search_priority_buckets",
            "./xctx discover stock_intelligence_hub::equity_filing search_priority_buckets <priority|text>",
        ],
    }


def high_impact_forms(root: Path) -> list[dict[str, Any]]:
    codes = ["10-K", "10-Q", "8-K", "DEF 14A", "4", "SC 13D", "S-3", "424B5"]
    results = []
    for code in codes:
        found = search_forms(root, code, limit=1)
        if found:
            results.append(compact_form_projection(found[0]))
    return results


def filing_taxonomy_discovery(root: Path, *, shape: str = "compact") -> dict[str, Any]:
    stats_payload = stats(root)
    next_moves = [
        "./xctx discover stock_intelligence_hub::equity_filing::search_forms",
        "./xctx discover stock_intelligence_hub::equity_filing list_forms",
        "./xctx discover stock_intelligence_hub::equity_filing search_forms 10-K",
        "./xctx observe stock_intelligence_hub::equity_filing form:10-K",
    ]
    if shape == "compact":
        return {
            "object_type": "equity_filing_discovery",
            "shape": "compact",
            "context_state": "without_equity",
            "description": "Discover filing taxonomy modes and observable filing objects.",
            "stats": {
                "total_lookup_filings": stats_payload["total_lookup_filings"],
                "canonical_families": stats_payload["canonical_families"],
                "priority_buckets": stats_payload["priority_buckets"],
                "amendment_forms": stats_payload["amendment_forms"],
            },
            "observable_objects": {
                "form": {
                    "id_shape": "form:<form_code>",
                    "observe_shape": "./xctx observe stock_intelligence_hub::equity_filing form:<form_code>",
                },
                "family": {
                    "id_shape": "family:<canonical_family_code>",
                    "observe_shape": "./xctx observe stock_intelligence_hub::equity_filing family:<family_code>",
                },
                "priority": {
                    "id_shape": "priority:<priority_bucket_code>",
                    "observe_shape": "./xctx observe stock_intelligence_hub::equity_filing priority:<priority_code>",
                },
                "equity_context": {
                    "id_shape": "instrument:<lowercase_ticker>",
                    "observe_shape": "./xctx observe stock_intelligence_hub::equity_filing instrument:<ticker>",
                },
            },
            "discoverable_modes": [
                {
                    "id": "search_forms",
                    "mode_kind": "search",
                    "query_shape": "<form code|name|family|priority|text>",
                    "run_cmd": "./xctx discover stock_intelligence_hub::equity_filing search_forms <query>",
                },
                {
                    "id": "search_families",
                    "mode_kind": "search",
                    "query_shape": "<family code|name|text>",
                    "run_cmd": "./xctx discover stock_intelligence_hub::equity_filing search_families <query>",
                },
                {
                    "id": "search_priority_buckets",
                    "mode_kind": "search",
                    "query_shape": "<priority code|name>",
                    "run_cmd": "./xctx discover stock_intelligence_hub::equity_filing search_priority_buckets <query>",
                },
                {
                    "id": "list_forms",
                    "mode_kind": "list",
                    "run_cmd": "./xctx discover stock_intelligence_hub::equity_filing list_forms [--limit N] [--shape compact|full]",
                },
                {
                    "id": "list_families",
                    "mode_kind": "list",
                    "run_cmd": "./xctx discover stock_intelligence_hub::equity_filing list_families [--limit N] [--shape compact|full]",
                },
                {
                    "id": "list_priority_buckets",
                    "mode_kind": "list",
                    "run_cmd": "./xctx discover stock_intelligence_hub::equity_filing list_priority_buckets [--limit N] [--shape compact|full]",
                },
            ],
            "full_shape_cmd": "./xctx discover stock_intelligence_hub::equity_filing --shape full",
            "next_moves": next_moves,
        }
    return {
        "object_type": "equity_filing_discovery",
        "shape": "full",
        "context_state": "without_equity",
        "description": "Use this subdomain when the agent needs to understand SEC/EDGAR company filing forms, families, priorities, amendments, and when-to-use guidance.",
        "data_description": "Bundled read-only SQLite filing taxonomy. It is a real lookup database, not a simulated YAML list and not an issuer-specific submission history feed.",
        "stats": stats_payload,
        "identity_shapes": {
            "form": "form:<form_code>, e.g. form:10-K",
            "family": "family:<canonical_family_code>, e.g. family:ANNUAL_REPORT",
            "priority": "priority:<priority_bucket_code>, e.g. priority:critical_always",
            "equity_context": "instrument:<lowercase_ticker>, e.g. instrument:aapl",
        },
        "command_grammar": {
            "mode_discovery": "./xctx discover stock_intelligence_hub::equity_filing::<mode>",
            "mode_discovery_alt": "./xctx discover stock_intelligence_hub::equity_filing <mode>",
            "mode_query": "./xctx discover stock_intelligence_hub::equity_filing <mode> <query>",
            "domain_affordance": "./xctx discover stock_intelligence_hub::<domain_affordance> <query>",
            "observation": "./xctx observe stock_intelligence_hub::equity_filing <form|family|priority|instrument id>",
        },
        "modes": {
            "search_forms": {
                "desc": "Search filing form taxonomy records. Exact form-code queries return the exact form and direct amendment only.",
                "arguments": ["<form code>", "<form name text>", "<family text>", "<priority text>", "<descriptive text>"],
                "examples": [
                    "./xctx discover stock_intelligence_hub::equity_filing search_forms 10-K",
                    "./xctx discover stock_intelligence_hub::equity_filing search_forms annual",
                    "./xctx discover stock_intelligence_hub::search_filing_form 8-K",
                ],
                "discover_cmd": "./xctx discover stock_intelligence_hub::equity_filing::search_forms",
            },
            "search_families": {
                "desc": "Search canonical filing families. Exact family code queries return the exact family only.",
                "arguments": ["<family code>", "<family name text>", "<descriptive text>"],
                "examples": [
                    "./xctx discover stock_intelligence_hub::equity_filing search_families ANNUAL_REPORT",
                    "./xctx discover stock_intelligence_hub::search_filing_family annual",
                ],
                "discover_cmd": "./xctx discover stock_intelligence_hub::equity_filing::search_families",
            },
            "search_priority_buckets": {
                "desc": "Search filing priority buckets. Exact priority code queries return the exact bucket only.",
                "arguments": ["<priority code>", "<priority name text>"],
                "examples": [
                    "./xctx discover stock_intelligence_hub::equity_filing search_priority_buckets critical_always",
                    "./xctx discover stock_intelligence_hub::search_priority_bucket critical",
                ],
                "discover_cmd": "./xctx discover stock_intelligence_hub::equity_filing::search_priority_buckets",
            },
            "list_forms": {
                "desc": "List a compact, bounded form taxonomy index without treating the mode name as a search query.",
                "arguments": ["optional --limit N", "optional --cursor CURSOR", "optional --shape compact|full"],
                "run_cmd": "./xctx discover stock_intelligence_hub::equity_filing list_forms [--limit N] [--cursor CURSOR] [--shape compact|full]",
            },
            "list_families": {
                "desc": "List a compact, bounded canonical filing-family index.",
                "arguments": ["optional --limit N", "optional --cursor CURSOR", "optional --shape compact|full"],
                "run_cmd": "./xctx discover stock_intelligence_hub::equity_filing list_families [--limit N] [--cursor CURSOR] [--shape compact|full]",
            },
            "list_priority_buckets": {
                "desc": "List a compact, bounded filing-priority bucket index.",
                "arguments": ["optional --limit N", "optional --shape compact|full"],
                "run_cmd": "./xctx discover stock_intelligence_hub::equity_filing list_priority_buckets [--limit N] [--shape compact|full]",
            },
            "observe": {
                "desc": "Observe a form, family, priority bucket, or equity instrument filing context.",
                "arguments": ["form:<code>", "family:<code>", "priority:<code>", "instrument:<ticker>"],
                "examples": [
                    "./xctx observe stock_intelligence_hub::equity_filing form:10-K",
                    "./xctx observe stock_intelligence_hub::equity_filing family:ANNUAL_REPORT",
                    "./xctx observe stock_intelligence_hub::equity_filing instrument:aapl",
                ],
            },
        },
        "actions": {
            "search_filing_form": {
                "priority": 10,
                "desc": "Search filing forms by code, name, family, priority, category, or descriptive text.",
                "run_cmd": "./xctx discover stock_intelligence_hub::search_filing_form <form code|text>",
            },
            "search_filing_family": {
                "priority": 20,
                "desc": "Search canonical filing families.",
                "run_cmd": "./xctx discover stock_intelligence_hub::search_filing_family <family|text>",
            },
            "search_priority_bucket": {
                "priority": 30,
                "desc": "Search filing priority buckets.",
                "run_cmd": "./xctx discover stock_intelligence_hub::search_priority_bucket <priority|text>",
            },
            "observe_filing_object": {
                "priority": 40,
                "desc": "Observe a form, family, priority bucket, or equity context.",
                "run_cmd": "./xctx observe stock_intelligence_hub::equity_filing <form:10-K|family:ANNUAL_REPORT|priority:critical_always|instrument:aapl>",
            },
        },
        "sample_high_impact_forms": high_impact_forms(root),
        "next_moves": next_moves,
    }


def equity_context_payload(root: Path, identifier: str) -> dict[str, Any]:
    record = find_instrument(root, identifier)
    if not record:
        candidate_matches = search_instruments(root, identifier, limit=5)
        return {
            "object_type": "equity_filing_equity_context",
            "context_state": "with_equity_requested_but_not_resolved",
            "query": identifier,
            "found": False,
            "candidate_instruments": candidate_matches,
            "next_move": "./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument <company|ticker|CIK|alias>",
        }
    public = public_instrument(record, include_aliases=True)
    return {
        "object_type": "equity_filing_equity_context",
        "context_state": "with_equity",
        "found": True,
        "instrument": public,
        "trusted_id_scope": "stock_intelligence_hub",
        "data_boundary": "This proof-of-concept has the real filing-form taxonomy. Issuer-specific EDGAR submission history is marked offline_not_bundled in this build.",
        "issuer_submission_feed_status": "offline_not_bundled",
        "useful_form_starting_points": high_impact_forms(root),
        "agent_guidance": [
            "Use form:10-K for annual business, audited financials, risk, strategy, and controls context.",
            "Use form:10-Q for interim financials and quarterly operating updates.",
            "Use form:8-K for material current events.",
            "Use proxy and ownership forms for governance, voting, incentives, insiders, and major holders.",
        ],
        "next_moves": [
            "./xctx discover stock_intelligence_hub::search_filing_form 10-K",
            "./xctx discover stock_intelligence_hub::search_filing_form 8-K",
            f"./xctx observe stock_intelligence_hub::market_data_gateway {record['instrument_id']}",
        ],
    }


def discover_with_query(root: Path, query: str) -> dict[str, Any]:
    query = query.strip()
    if not query:
        return filing_taxonomy_discovery(root)
    # First resolve explicit equity context, then try form/family/priority search.
    if query.lower().startswith(("instrument:", "issuer:cik:")) or find_instrument(root, query):
        return equity_context_payload(root, query)
    forms = search_forms(root, query)
    families = search_families(root, query)
    priorities = search_priority_buckets(root, query)
    return {
        "object_type": "equity_filing_query_discovery",
        "context_state": "without_equity",
        "query": query,
        "matches": {
            "forms": forms,
            "canonical_families": families,
            "priority_buckets": priorities,
        },
        "empty_result_guidance": None if any([forms, families, priorities]) else "Try an EDGAR form code such as 10-K, a concept such as proxy, or an impact bucket such as critical.",
    }


def observe_form(root: Path, code: str) -> dict[str, Any] | None:
    code = code.removeprefix("form:").strip()
    with connect(root) as conn:
        row = conn.execute(_form_join_sql("WHERE lower(f.form_code) = lower(?) LIMIT 1"), (code,)).fetchone()
    if not row:
        return None
    payload = form_projection(row)
    payload.update(
        {
            "object_type": "filing_form_observation",
            "description": row["description"],
            "when_to_use": row["when_to_use"],
            "family_description": row["family_description"],
            "family_sort_order": row["family_sort_order"],
            "priority_sort_order": row["priority_sort_order"],
            "source_table": "forms",
        }
    )
    return payload


def observe_family(root: Path, code: str) -> dict[str, Any] | None:
    code = code.removeprefix("family:").strip()
    with connect(root) as conn:
        family = conn.execute("SELECT * FROM canonical_families WHERE lower(code) = lower(?) LIMIT 1", (code,)).fetchone()
        if not family:
            return None
        forms = conn.execute(
            _form_join_sql("WHERE cf.id = ? ORDER BY pb.sort_order, f.form_code LIMIT 30"),
            (family["id"],),
        ).fetchall()
        count = conn.execute("SELECT COUNT(*) FROM forms WHERE canonical_families_id = ?", (family["id"],)).fetchone()[0]
    return {
        "object_type": "filing_family_observation",
        "id": f"family:{family['code']}",
        "code": family["code"],
        "name": family["name"],
        "description": family["description"],
        "sort_order": family["sort_order"],
        "form_count": count,
        "sample_forms": [form_projection(row) for row in forms],
    }


def observe_priority(root: Path, code: str) -> dict[str, Any] | None:
    code = code.removeprefix("priority:").strip()
    with connect(root) as conn:
        priority = conn.execute("SELECT * FROM priority_buckets WHERE lower(code) = lower(?) LIMIT 1", (code,)).fetchone()
        if not priority:
            return None
        forms = conn.execute(
            _form_join_sql("WHERE pb.id = ? ORDER BY cf.sort_order, f.form_code LIMIT 30"),
            (priority["id"],),
        ).fetchall()
        count = conn.execute("SELECT COUNT(*) FROM forms WHERE priority_buckets_id = ?", (priority["id"],)).fetchone()[0]
    return {
        "object_type": "filing_priority_observation",
        "id": f"priority:{priority['code']}",
        "code": priority["code"],
        "name": priority["name"],
        "sort_order": priority["sort_order"],
        "form_count": count,
        "sample_forms": [form_projection(row) for row in forms],
    }


def observe_any(root: Path, identifier: str) -> dict[str, Any]:
    item = identifier.strip()
    lowered = item.lower()
    if lowered.startswith("instrument:") or lowered.startswith("issuer:cik:") or find_instrument(root, item):
        return equity_context_payload(root, item)
    if lowered.startswith("family:"):
        result = observe_family(root, item)
    elif lowered.startswith("priority:"):
        result = observe_priority(root, item)
    else:
        result = observe_form(root, item)
    if result:
        return result
    return {
        "object_type": "equity_filing_observation",
        "found": False,
        "query": identifier,
        "next_moves": [
            "./xctx discover stock_intelligence_hub::search_filing_form <form code|text>",
            "./xctx discover stock_intelligence_hub::search_filing_family <family|text>",
            "./xctx discover stock_intelligence_hub::search_priority_bucket <priority|text>",
        ],
    }


def filing_audit(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    path = sqlite_path(root)
    checks.append({"id": "audit:equity_filing:sqlite_exists", "status": "pass" if path.exists() else "fail", "path": str(SQLITE_PATH)})
    if not path.exists():
        return {"object_type": "equity_filing_audit", "checks": checks}
    with connect(root) as conn:
        s = stats(root)
        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    checks.extend(
        [
            {"id": "audit:equity_filing:required_tables", "status": "pass" if {"forms", "canonical_families", "priority_buckets"} <= tables else "fail", "value": sorted(tables)},
            {"id": "audit:equity_filing:forms_count", "status": "pass" if s["total_lookup_filings"] == 412 else "warn", "value": s["total_lookup_filings"]},
            {"id": "audit:equity_filing:canonical_families_count", "status": "pass" if s["canonical_families"] == 41 else "warn", "value": s["canonical_families"]},
            {"id": "audit:equity_filing:priority_buckets_count", "status": "pass" if s["priority_buckets"] == 12 else "warn", "value": s["priority_buckets"]},
            {"id": "audit:equity_filing:foreign_key_check", "status": "pass" if not fk_rows else "fail", "violations": [tuple(row) for row in fk_rows]},
        ]
    )
    return {"object_type": "equity_filing_audit", "checks": checks, "stats": s}
