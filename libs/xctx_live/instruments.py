from __future__ import annotations

import csv
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from xctx_live.common import load_yaml, normalize_search_text

INSTRUMENT_DATA = Path("yaml_dynamic_config/agent_domains/stock_intelligence_hub/subdomains/market_data_gateway/instruments.yaml")
MINI_STOCKS_DB = Path("data/mini_stocks.sqlite")
EXPORT_DIR = Path(".xctx_runtime/exports")
PRICE_SCALE = 1_000_000
DEFAULT_SEARCH_LIMIT = 10
INLINE_BAR_LIMIT = 30
BAR_CSV_COLUMNS = ["bar_start_ts", "date", "open", "high", "low", "close", "vwap", "volume_raw", "transaction_count"]

EXCHANGE_NAMES = {
    "XNAS": "Nasdaq",
    "XNYS": "NYSE",
    "ARCX": "NYSE Arca",
}

SECURITY_TYPE_NAMES = {
    "CS": "common_stock",
    "ETF": "exchange_traded_fund",
}

COMMON_COMPANY_WORDS = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "plc",
    "class",
    "ordinary",
    "share",
    "shares",
    "common",
    "stock",
    "the",
}


def agent_domain_id() -> str:
    return os.environ.get("XCTX_AGENT_DOMAIN", "stock_intelligence_hub")


def agent_subdomain_id() -> str:
    return os.environ.get("XCTX_AGENT_SUBDOMAIN", "market_data_gateway")


def scoped_ref() -> str:
    return f"{agent_domain_id()}::{agent_subdomain_id()}"


def instrument_gateway_ref() -> str:
    return f"{agent_domain_id()}::market_data_gateway"


def instrument_data_path(root: Path) -> Path:
    return root / INSTRUMENT_DATA


def market_db_path(root: Path) -> Path:
    return root / MINI_STOCKS_DB


def connect_market(root: Path) -> sqlite3.Connection:
    path = market_db_path(root)
    if not path.exists():
        raise FileNotFoundError(f"mini_stocks sqlite not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def load_instruments(root: Path) -> list[dict[str, Any]]:
    doc = load_yaml(instrument_data_path(root))
    instruments = doc.get("instruments", [])
    if not isinstance(instruments, list):
        raise ValueError("instruments.yaml must contain a list under instruments")
    return instruments


def _exchange_name(mic: str) -> str:
    return EXCHANGE_NAMES.get(str(mic).upper(), str(mic))


def _security_type(value: str) -> str:
    return SECURITY_TYPE_NAMES.get(str(value).upper(), str(value).lower() or "unknown")


def _currency_from_raw_json(value: str) -> str:
    try:
        payload = json.loads(value or "{}")
    except json.JSONDecodeError:
        return "USD"
    currency = str(payload.get("currency_name") or payload.get("currency") or "USD")
    return currency.upper()


def _unique_text(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _normalized_text(value: Any) -> str:
    text = normalize_search_text(value).lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_search_text(value).lower())


def _company_key(value: Any) -> str:
    words = [word for word in _normalized_text(value).split() if word not in COMMON_COMPANY_WORDS]
    return " ".join(words)


def _digits_only(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _cik_key(value: Any) -> str:
    digits = _digits_only(value)
    return digits.lstrip("0") if digits else ""


def _query_cik_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    digits = _digits_only(text)
    if not digits:
        return ""
    alpha = re.sub(r"[^a-z]+", "", text)
    if re.fullmatch(r"0*\d{1,10}", text):
        return digits.lstrip("0") or "0"
    if alpha in {"cik", "issuercik"} or text.startswith(("issuer:cik:", "cik:")):
        return digits.lstrip("0") or "0"
    return ""


def _alias_symbols(record: dict[str, Any]) -> list[str]:
    aliases: list[Any] = list(record.get("aliases") or [])
    for alias_record in record.get("ticker_aliases") or []:
        if isinstance(alias_record, dict):
            aliases.append(alias_record.get("ticker"))
        else:
            aliases.append(alias_record)
    return _unique_text(aliases)


def _instrument_lookup_token(identifier: str) -> str:
    lowered = identifier.strip().lower()
    if lowered.startswith("market_series:"):
        parts = lowered.split(":")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    if lowered.startswith("ticker:"):
        return lowered.replace("ticker:", "", 1)
    return identifier.strip()


def load_reference_instruments(root: Path) -> list[dict[str, Any]]:
    """Load canonical instrument candidates from the bundled market fixture.

    The YAML seed remains the curated canonical handoff sample. The SQLite market
    fixture adds the larger real reference universe used for ticker-first search,
    e.g. a query of "A" can resolve the ticker A before broader text matches.
    Ticker aliases from the fixture are also folded into identity resolution so
    former or provider-observed symbols can lead back to the canonical object.
    """
    path = market_db_path(root)
    if not path.exists():
        return []
    with connect_market(root) as conn:
        rows = conn.execute(
            """
            SELECT provider, ticker, ohlcv_series_id, active_flag, company_name, cik,
                   composite_figi, share_class_figi, security_type, primary_exchange,
                   market, locale, identity_status, raw_json
            FROM reference_universe_snapshots
            ORDER BY ticker
            """
        ).fetchall()
        alias_rows = conn.execute(
            """
            SELECT ohlcv_series_id, ticker, active, as_of_date, source
            FROM ticker_aliases
            ORDER BY ohlcv_series_id, active DESC, ticker, as_of_date
            """
        ).fetchall()
    alias_map: dict[int, list[dict[str, Any]]] = {}
    for alias in alias_rows:
        alias_map.setdefault(int(alias["ohlcv_series_id"]), []).append(
            {
                "ticker": str(alias["ticker"]).upper(),
                "active": None if alias["active"] is None else bool(alias["active"]),
                "as_of_date": alias["as_of_date"],
                "source": alias["source"],
            }
        )

    out: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row["ticker"]).upper()
        cik = str(row["cik"] or "")
        mic = str(row["primary_exchange"] or "")
        ohlcv_series_id = int(row["ohlcv_series_id"])
        ticker_aliases = alias_map.get(ohlcv_series_id, [])
        alias_symbols = _unique_text(
            [alias["ticker"] for alias in ticker_aliases if alias.get("ticker") and str(alias.get("ticker")).upper() != ticker]
        )
        out.append(
            {
                "instrument_id": f"instrument:{ticker.lower()}",
                "issuer_id": f"issuer:cik:{cik}" if cik else None,
                "cik": cik,
                "ticker": ticker,
                "name": row["company_name"],
                "aliases": alias_symbols,
                "ticker_aliases": ticker_aliases,
                "exchange": _exchange_name(mic),
                "mic": mic,
                "security_type": _security_type(str(row["security_type"] or "")),
                "currency": _currency_from_raw_json(str(row["raw_json"] or "{}")),
                "status": "active" if int(row["active_flag"] or 0) else "inactive",
                "market": row["market"],
                "locale": row["locale"],
                "identity_status": row["identity_status"],
                "ohlcv_series_id": ohlcv_series_id,
                "provider": row["provider"],
                "composite_figi": row["composite_figi"],
                "share_class_figi": row["share_class_figi"],
                "data_origin": "mini_stocks.reference_universe_snapshots",
            }
        )
    return out


def load_all_instruments(root: Path) -> list[dict[str, Any]]:
    """Return deduplicated instruments from SQLite reference data plus YAML seed.

    Deduplication uses the protocol identity, instrument:<lowercase_primary_ticker>.
    Curated YAML records enrich matching SQLite records without changing the stable
    insertion order of the SQLite reference universe.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for record in load_reference_instruments(root):
        instrument_id = str(record.get("instrument_id") or "")
        if instrument_id:
            by_id[instrument_id] = dict(record)
    for record in load_instruments(root):
        instrument_id = str(record.get("instrument_id") or "")
        if not instrument_id:
            continue
        existing = by_id.get(instrument_id, {})
        merged = {**existing, **record, "data_origin": existing.get("data_origin", "canonical_seed_yaml")}
        merged["aliases"] = _unique_text([*(existing.get("aliases") or []), *(record.get("aliases") or [])])
        merged["ticker_aliases"] = existing.get("ticker_aliases", record.get("ticker_aliases", []))
        if existing:
            merged["canonical_seed"] = True
        by_id[instrument_id] = merged
    return list(by_id.values())


def public_instrument(record: dict[str, Any], *, include_aliases: bool = False) -> dict[str, Any]:
    keys = [
        "instrument_id",
        "issuer_id",
        "ticker",
        "name",
        "cik",
        "exchange",
        "mic",
        "security_type",
        "currency",
        "status",
    ]
    out = {key: record.get(key) for key in keys if key in record}
    if include_aliases:
        out["aliases"] = _alias_symbols(record)
    out["run_cmd"] = f"./xctx observe {instrument_gateway_ref()} {record.get('instrument_id')}"
    ticker = str(record.get("ticker", "")).lower()
    has_series_hint = bool(record.get("ohlcv_series_id"))
    if ticker and has_series_hint:
        out["market_series_run_cmd"] = f"./xctx observe {instrument_gateway_ref()} market_series:{ticker}:daily"
    next_moves: list[dict[str, str]] = []
    instrument_id = record.get("instrument_id")
    if instrument_id:
        next_moves.append(
            {
                "desc": "Observe the canonical instrument record.",
                "run_cmd": f"./xctx observe {instrument_gateway_ref()} {instrument_id}",
            }
        )
        next_moves.append(
            {
                "desc": "Discover filing context for this instrument.",
                "run_cmd": f"./xctx discover stock_intelligence_hub::equity_filing {instrument_id}",
            }
        )
    if ticker and has_series_hint:
        next_moves.append(
            {
                "desc": "Get the latest available bundled daily price for this ticker.",
                "run_cmd": f"./xctx discover {agent_domain_id()}::latest_price {record.get('ticker')}",
            }
        )
        next_moves.append(
            {
                "desc": "Discover the bundled market series for this ticker.",
                "run_cmd": f"./xctx discover {instrument_gateway_ref()} search_market_series {record.get('ticker')}",
            }
        )
        next_moves.append(
            {
                "desc": "Observe a five-bar bundled daily price range for this ticker.",
                "run_cmd": f"./xctx observe {instrument_gateway_ref()} {record.get('ticker')} --bars 5",
            }
        )
    elif ticker:
        next_moves.append(
            {
                "desc": "Check whether a bundled market series exists for this ticker.",
                "run_cmd": f"./xctx discover {instrument_gateway_ref()} search_market_series {record.get('ticker')}",
            }
        )
    if next_moves:
        out["next_moves"] = next_moves
    return out


def _candidate_values(record: dict[str, Any]) -> list[str]:
    return [
        normalize_search_text(record.get("instrument_id")),
        normalize_search_text(record.get("issuer_id")),
        normalize_search_text(record.get("ticker")),
        normalize_search_text(record.get("name")),
        normalize_search_text(record.get("cik")),
        normalize_search_text(_alias_symbols(record)),
        normalize_search_text(record.get("ticker_aliases")),
        normalize_search_text(record.get("exchange")),
        normalize_search_text(record.get("mic")),
        normalize_search_text(record.get("market")),
        normalize_search_text(record.get("locale")),
        normalize_search_text(record.get("identity_status")),
        normalize_search_text(record.get("provider")),
        normalize_search_text(record.get("composite_figi")),
        normalize_search_text(record.get("share_class_figi")),
    ]


def _strip_cik(value: str) -> str:
    stripped = value.lower().replace("issuer:cik:", "").replace("cik:", "").strip()
    digits = _digits_only(stripped)
    if digits:
        return digits.lstrip("0") or "0"
    return stripped.lstrip("0") or stripped


def match_instrument(record: dict[str, Any], query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    q_lower = q.lower()
    q_norm = _normalized_text(q)
    q_compact = _compact_text(q)
    q_company = _company_key(q)
    q_cik = _query_cik_key(q)
    q_words = [word for word in q_norm.split() if word]
    symbolish = bool(re.fullmatch(r"[a-z0-9.]+", q_lower))
    if symbolish and len(q_lower.replace(".", "")) <= 2 and not q_cik:
        ticker = str(record.get("ticker", "")).lower()
        aliases = {alias.lower() for alias in _alias_symbols(record)}
        return ticker.startswith(q_lower) or q_lower in aliases
    for value in _candidate_values(record):
        text_lower = value.lower()
        text_norm = _normalized_text(value)
        text_compact = _compact_text(value)
        text_company = _company_key(value)
        if q_lower and q_lower in text_lower:
            return True
        if q_norm and q_norm in text_norm:
            return True
        if q_company and q_company == text_company:
            return True
        if q_compact and q_compact == text_compact:
            return True
        if q_words and all(word in text_norm for word in q_words):
            return True
        if q_cik and q_cik == _cik_key(value):
            return True
    return False


def _instrument_match_reason(record: dict[str, Any], query: str) -> str:
    q = query.strip()
    q_lower = q.lower()
    q_norm = _normalized_text(q)
    q_company = _company_key(q)
    q_cik = _query_cik_key(q)
    ticker = str(record.get("ticker", "")).lower()
    instrument_id = str(record.get("instrument_id", "")).lower()
    issuer_id = str(record.get("issuer_id", "")).lower()
    cik = str(record.get("cik", ""))
    name = str(record.get("name", ""))
    aliases = [alias.lower() for alias in _alias_symbols(record)]
    if q_lower == ticker:
        return "exact_ticker"
    if q_lower == instrument_id:
        return "exact_instrument_id"
    if q_lower == issuer_id or (q_cik and q_cik == _cik_key(cik)):
        return "exact_cik"
    if q_lower in aliases:
        return "exact_alias"
    if q_company and q_company == _company_key(name):
        return "normalized_name_exact"
    if q_norm and ticker.startswith(q_lower):
        return "ticker_prefix"
    if q_norm and _normalized_text(name).startswith(q_norm):
        return "name_prefix"
    if q_norm and q_norm in _normalized_text(name):
        return "name_contains"
    if any(q_norm and q_norm in _normalized_text(alias) for alias in aliases):
        return "alias_contains"
    return "field_contains"


def _instrument_match_score(record: dict[str, Any], query: str) -> int:
    q = query.lower().strip()
    q_norm = _normalized_text(query)
    q_company = _company_key(query)
    q_cik = _query_cik_key(query)
    ticker = str(record.get("ticker", "")).lower()
    instrument_id = str(record.get("instrument_id", "")).lower()
    cik = str(record.get("cik", ""))
    issuer_id = str(record.get("issuer_id", "")).lower()
    name = str(record.get("name", ""))
    aliases = [alias.lower() for alias in _alias_symbols(record)]
    if q == ticker:
        return 0
    if q == instrument_id:
        return 1
    if q == issuer_id or (q_cik and q_cik == _cik_key(cik)):
        return 2
    if q in aliases:
        return 3
    if q_company and q_company == _company_key(name):
        return 4
    if q and ticker.startswith(q):
        return 10
    if q and q in ticker:
        return 15
    if q_norm and _normalized_text(name).startswith(q_norm):
        return 20
    if q_norm and q_norm in _normalized_text(name):
        return 30
    if any(q_norm and q_norm in _normalized_text(alias) for alias in aliases):
        return 35
    return 100


def search_instruments_with_total(root: Path, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> tuple[int, list[dict[str, Any]]]:
    query = query.strip()
    if not query:
        return 0, []
    matches: list[dict[str, Any]] = []
    for record in load_all_instruments(root):
        if match_instrument(record, query):
            score = _instrument_match_score(record, query)
            payload = public_instrument(record)
            payload["resolver_match"] = {"reason": _instrument_match_reason(record, query), "score": score}
            matches.append({"_score": score, **payload})
    matches.sort(key=lambda item: (item.pop("_score"), item.get("ticker", "")))
    return len(matches), matches[:limit]


def search_instruments(root: Path, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict[str, Any]]:
    _total, matches = search_instruments_with_total(root, query, limit)
    return matches


def _parse_positive_int(value: str, option_name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{option_name} requires an integer") from exc
    if parsed < 0:
        raise ValueError(f"{option_name} cannot be negative")
    return parsed


def parse_list_options(args: list[str]) -> dict[str, Any]:
    options: dict[str, Any] = {
        "limit": 50,
        "cursor": 0,
        "status": None,
        "exchange": None,
        "security_type": None,
    }
    index = 0
    while index < len(args):
        token = args[index]
        if token in {"--limit", "--cursor", "--status", "--exchange", "--security-type"}:
            if index + 1 >= len(args):
                raise ValueError(f"{token} requires a value")
            value = args[index + 1]
            if token == "--limit":
                limit = _parse_positive_int(value, token)
                if limit == 0:
                    raise ValueError("--limit must be greater than zero")
                options["limit"] = min(limit, 100)
            elif token == "--cursor":
                options["cursor"] = _parse_positive_int(value, token)
            elif token == "--security-type":
                options["security_type"] = value
            else:
                options[token[2:].replace("-", "_")] = value
            index += 2
            continue
        raise ValueError(f"unknown list option: {token}")
    return options


def _matches_filter(record: dict[str, Any], key: str, expected: str | None) -> bool:
    if expected is None:
        return True
    return str(record.get(key, "")).lower() == str(expected).lower()


def _list_run_cmd(options: dict[str, Any], cursor: int | None = None) -> str:
    parts = [f"./xctx discover {scoped_ref()} list_instruments"]
    if options.get("limit") != 50:
        parts.append(f"--limit {options['limit']}")
    if cursor is not None:
        parts.append(f"--cursor {cursor}")
    elif options.get("cursor"):
        parts.append(f"--cursor {options['cursor']}")
    if options.get("status"):
        parts.append(f"--status {options['status']}")
    if options.get("exchange"):
        parts.append(f"--exchange {options['exchange']}")
    if options.get("security_type"):
        parts.append(f"--security-type {options['security_type']}")
    return " ".join(parts)


def list_instruments(root: Path, args: list[str]) -> dict[str, Any]:
    options = parse_list_options(args)
    instruments = load_all_instruments(root)
    filtered = [
        item
        for item in instruments
        if _matches_filter(item, "status", options["status"])
        and _matches_filter(item, "exchange", options["exchange"])
        and _matches_filter(item, "security_type", options["security_type"])
    ]
    cursor = min(options["cursor"], len(filtered))
    limit = options["limit"]
    page = filtered[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < len(filtered) else None
    filters = {
        key: value
        for key, value in (
            ("status", options["status"]),
            ("exchange", options["exchange"]),
            ("security_type", options["security_type"]),
        )
        if value is not None
    }
    payload = {
        "object_type": "market_data_gateway_instrument_list",
        "description": f"Canonical instruments currently known to the {scoped_ref()} subdomain.",
        "total_count": len(instruments),
        "filtered_count": len(filtered),
        "returned_count": len(page),
        "limit": limit,
        "cursor": str(cursor),
        "next_cursor": str(next_cursor) if next_cursor is not None else None,
        "filters": filters,
        "instruments": [public_instrument(item) for item in page],
    }
    if next_cursor is not None:
        payload["next_page_run_cmd"] = _list_run_cmd(options, next_cursor)
    return payload


def find_instrument(root: Path, identifier: str) -> dict[str, Any] | None:
    identifier = _instrument_lookup_token(identifier)
    if not identifier:
        return None
    q = identifier.lower()
    q_cik = _query_cik_key(q)
    instruments = load_all_instruments(root)
    for record in instruments:
        aliases = {alias.lower() for alias in _alias_symbols(record)}
        candidates = {
            str(record.get("instrument_id", "")).lower(),
            str(record.get("issuer_id", "")).lower(),
            str(record.get("ticker", "")).lower(),
            str(record.get("cik", "")).lower(),
            _strip_cik(str(record.get("cik", ""))),
            *aliases,
        }
        if q in candidates or (q_cik and q_cik in candidates):
            return record
    matches = search_instruments(root, identifier, limit=1)
    if matches:
        return next((item for item in instruments if item.get("instrument_id") == matches[0].get("instrument_id")), None)
    return None


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def market_stats(root: Path) -> dict[str, Any]:
    with connect_market(root) as conn:
        meta = {row[0]: row[1] for row in conn.execute("SELECT key, value FROM schema_metadata").fetchall()}
        return {
            "storage_engine": "sqlite",
            "read_only": True,
            "database_path": str(MINI_STOCKS_DB),
            "schema_version": meta.get("schema_version"),
            "mini_fixture": meta.get("mini_fixture") == "true",
            "reference_universe_snapshots": _table_count(conn, "reference_universe_snapshots"),
            "ohlcv_series": _table_count(conn, "ohlcv_series"),
            "bar_datasets": _table_count(conn, "bar_datasets"),
            "ohlcv_bars": _table_count(conn, "ohlcv_bars"),
            "ticker_aliases": _table_count(conn, "ticker_aliases"),
        }


def _price(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value) / PRICE_SCALE, 6)


def _date_key(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if len(text) == 8:
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _bar_payload(row: sqlite3.Row, *, include_ts: bool = False) -> dict[str, Any]:
    payload = {
        "date": _date_key(row["bar_date_key"]),
        "open": _price(row["open_int"]),
        "high": _price(row["high_int"]),
        "low": _price(row["low_int"]),
        "close": _price(row["close_int"]),
        "vwap": _price(row["vwap_int"]),
        "volume_raw": row["volume_int"],
        "transaction_count": row["transaction_count"],
    }
    if include_ts:
        payload = {"bar_start_ts": row["bar_start_ts"], **payload}
    return payload


def _latest_available_price_payload(series: dict[str, Any], currency: str | None = None) -> dict[str, Any]:
    bar = series.get("latest_bar") or {}
    return {
        "source": "latest_available_daily_ohlcv_close",
        "is_live_quote": False,
        "date": bar.get("date"),
        "price": bar.get("close"),
        "price_field": "close",
        "currency": currency or "USD",
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "vwap": bar.get("vwap"),
        "volume_raw": bar.get("volume_raw"),
        "transaction_count": bar.get("transaction_count"),
    }


def _price_range_summary(bars: list[dict[str, Any]]) -> dict[str, Any]:
    if not bars:
        return {"bar_count": 0}
    closes = [float(bar["close"]) for bar in bars if bar.get("close") is not None]
    highs = [float(bar["high"]) for bar in bars if bar.get("high") is not None]
    lows = [float(bar["low"]) for bar in bars if bar.get("low") is not None]
    first_close = closes[0] if closes else None
    last_close = closes[-1] if closes else None
    change = round(last_close - first_close, 6) if first_close is not None and last_close is not None else None
    pct_change = round((change / first_close) * 100, 6) if change is not None and first_close not in (None, 0) else None
    return {
        "bar_count": len(bars),
        "start_date": bars[0].get("date"),
        "end_date": bars[-1].get("date"),
        "first_close": first_close,
        "last_close": last_close,
        "close_change": change,
        "close_change_percent": pct_change,
        "highest_high": max(highs) if highs else None,
        "lowest_low": min(lows) if lows else None,
    }


def _csv_safe_token(value: Any) -> str:
    text = str(value or "unknown").lower().replace(":", "_")
    cleaned = "".join(char if char.isalnum() else "_" for char in text).strip("_")
    return cleaned or "unknown"


def _range_csv_path(root: Path, series: dict[str, Any], value: int, unit: str) -> Path:
    ticker = _csv_safe_token(series.get("ticker") or str(series.get("instrument_id", "")).replace("instrument:", ""))
    amount = "all" if value == 0 else str(value)
    filename = f"instrument_{ticker}_{amount}_{unit}_{secrets.token_hex(4)}.csv"
    return root / EXPORT_DIR / filename


def _write_bars_csv(root: Path, series: dict[str, Any], bars: list[dict[str, Any]], value: int, unit: str) -> Path:
    path = _range_csv_path(root, series, value, unit)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BAR_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(bars)
    return path


def _series_query_sql(where: str = "") -> str:
    return f"""
        SELECT
          s.ohlcv_series_id,
          s.latest_ticker,
          s.company_name,
          s.identity_status,
          s.composite_figi,
          s.share_class_figi,
          COALESCE(r.cik, '') AS cik,
          COALESCE(r.primary_exchange, '') AS primary_exchange,
          COALESCE(r.security_type, '') AS security_type,
          COALESCE(r.market, '') AS market,
          COALESCE(r.locale, '') AS locale,
          d.dataset_id,
          d.bar_count,
          d.min_date_key,
          d.max_date_key,
          d.source_text,
          d.request_hash,
          d.evidence_ledger_hash,
          b.bar_start_ts,
          b.bar_date_key,
          b.open_int,
          b.high_int,
          b.low_int,
          b.close_int,
          b.volume_int,
          b.vwap_int,
          b.transaction_count
        FROM ohlcv_series s
        LEFT JOIN reference_universe_snapshots r ON r.ohlcv_series_id = s.ohlcv_series_id
        LEFT JOIN bar_datasets d ON d.dataset_id = (
          SELECT d2.dataset_id
          FROM bar_datasets d2
          WHERE d2.ohlcv_series_id = s.ohlcv_series_id
          ORDER BY d2.max_date_key DESC, d2.bar_count DESC, d2.dataset_id DESC
          LIMIT 1
        )
        LEFT JOIN ohlcv_bars b ON b.dataset_id = d.dataset_id
          AND b.bar_start_ts = (
            SELECT b2.bar_start_ts
            FROM ohlcv_bars b2
            WHERE b2.dataset_id = d.dataset_id
              AND b2.bar_date_key = d.max_date_key
            ORDER BY b2.bar_start_ts DESC
            LIMIT 1
          )
        {where}
    """


def _market_series_projection(row: sqlite3.Row) -> dict[str, Any]:
    ticker = str(row["latest_ticker"]).upper()
    series_id = f"market_series:{ticker.lower()}:daily"
    payload = {
        "id": series_id,
        "market_series_id": series_id,
        "ohlcv_series_id": f"ohlcv_series:{row['ohlcv_series_id']}",
        "ticker": ticker,
        "issuer_name": row["company_name"],
        "cik": row["cik"],
        "issuer_id": f"issuer:cik:{row['cik']}" if row["cik"] else None,
        "instrument_id": f"instrument:{ticker.lower()}",
        "timeframe": "1d",
        "adjusted": True,
        "provider": row["source_text"],
        "primary_exchange": row["primary_exchange"],
        "security_type": row["security_type"],
        "market": row["market"],
        "locale": row["locale"],
        "dataset_id": row["dataset_id"],
        "bar_count": row["bar_count"],
        "coverage": {"min_date": _date_key(row["min_date_key"]), "max_date": _date_key(row["max_date_key"])},
        "latest_bar": _bar_payload(row),
        "evidence": {
            "request_hash": row["request_hash"],
            "evidence_ledger_hash": row["evidence_ledger_hash"],
        },
        "run_cmd": f"./xctx observe {scoped_ref()} {series_id}",
    }
    return {key: value for key, value in payload.items() if value is not None}


def _series_identifier_where(identifier: str) -> tuple[str, tuple[Any, ...]]:
    raw = identifier.strip()
    lowered = raw.lower()
    if lowered.startswith("market_series:"):
        parts = lowered.split(":")
        ticker = parts[1] if len(parts) >= 2 else lowered.replace("market_series:", "")
        return "WHERE lower(s.latest_ticker) = lower(?)", (ticker,)
    if lowered.startswith("ohlcv_series:"):
        return "WHERE s.ohlcv_series_id = ?", (lowered.replace("ohlcv_series:", ""),)
    if lowered.startswith("instrument:"):
        ticker = lowered.replace("instrument:", "", 1)
        return "WHERE lower(s.latest_ticker) = lower(?)", (ticker,)
    q_cik = _query_cik_key(raw)
    if q_cik:
        return "WHERE ltrim(COALESCE(r.cik, ''), '0') = ?", (q_cik,)
    return "WHERE lower(s.latest_ticker) = lower(?) OR lower(r.cik) = lower(?) OR s.ohlcv_series_id = ?", (
        raw,
        raw.replace("issuer:cik:", ""),
        raw.replace("ohlcv_series:", ""),
    )


def find_market_series(root: Path, identifier: str) -> dict[str, Any] | None:
    where, params = _series_identifier_where(identifier)
    with connect_market(root) as conn:
        row = conn.execute(_series_query_sql(where + " ORDER BY d.max_date_key DESC LIMIT 1"), params).fetchone()
    return _market_series_projection(row) if row else None


def search_market_series(root: Path, query: str, limit: int = 20) -> list[dict[str, Any]]:
    query = query.strip()
    with connect_market(root) as conn:
        if not query:
            rows = conn.execute(_series_query_sql("ORDER BY s.latest_ticker LIMIT ?"), (limit,)).fetchall()
        else:
            lowered = query.lower()
            identifier_like = lowered.startswith(("market_series:", "ohlcv_series:", "instrument:", "issuer:cik:", "cik:")) or bool(_query_cik_key(query))
            if identifier_like:
                found = find_market_series(root, query)
                if not found:
                    record = find_instrument(root, query)
                    if record:
                        found = find_market_series(root, str(record.get("ticker", "")))
                return [found] if found else []
            like = f"%{lowered}%"
            rows = conn.execute(
                _series_query_sql(
                    """
                    WHERE lower(s.latest_ticker) LIKE ?
                       OR lower(s.company_name) LIKE ?
                       OR lower(COALESCE(r.cik, '')) LIKE ?
                       OR lower(COALESCE(r.primary_exchange, '')) LIKE ?
                       OR lower(COALESCE(d.source_text, '')) LIKE ?
                    ORDER BY
                      CASE WHEN lower(s.latest_ticker) = lower(?) THEN 0 ELSE 1 END,
                      s.latest_ticker
                    LIMIT ?
                    """
                ),
                (like, like, like, like, like, query, limit),
            ).fetchall()
    return [_market_series_projection(row) for row in rows]


def _sample_bars(root: Path, dataset_id: int | None, limit: int = 5) -> list[dict[str, Any]]:
    if dataset_id is None:
        return []
    with connect_market(root) as conn:
        rows = conn.execute(
            """
            SELECT * FROM ohlcv_bars
            WHERE dataset_id = ?
            ORDER BY bar_date_key DESC, bar_start_ts DESC
            LIMIT ?
            """,
            (dataset_id, limit),
        ).fetchall()
    return [_bar_payload(row) for row in reversed(rows)]


def _range_bars(root: Path, dataset_id: int | None, *, bars: int | None, calendar_days: int | None) -> list[dict[str, Any]]:
    if dataset_id is None:
        return []
    with connect_market(root) as conn:
        if bars is not None:
            if bars == 0:
                rows = conn.execute(
                    """
                    SELECT * FROM ohlcv_bars
                    WHERE dataset_id = ?
                    ORDER BY bar_date_key ASC, bar_start_ts ASC
                    """,
                    (dataset_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM ohlcv_bars
                    WHERE dataset_id = ?
                    ORDER BY bar_date_key DESC, bar_start_ts DESC
                    LIMIT ?
                    """,
                    (dataset_id, bars),
                ).fetchall()
                rows = list(reversed(rows))
        else:
            if calendar_days == 0:
                rows = conn.execute(
                    """
                    SELECT * FROM ohlcv_bars
                    WHERE dataset_id = ?
                    ORDER BY bar_date_key ASC, bar_start_ts ASC
                    """,
                    (dataset_id,),
                ).fetchall()
            else:
                latest_key = conn.execute(
                    "SELECT MAX(bar_date_key) FROM ohlcv_bars WHERE dataset_id = ?",
                    (dataset_id,),
                ).fetchone()[0]
                if not latest_key:
                    return []
                latest = datetime.strptime(str(latest_key), "%Y%m%d").date()
                start_key = int((latest - timedelta(days=int(calendar_days or 0) - 1)).strftime("%Y%m%d"))
                rows = conn.execute(
                    """
                    SELECT * FROM ohlcv_bars
                    WHERE dataset_id = ? AND bar_date_key >= ?
                    ORDER BY bar_date_key ASC, bar_start_ts ASC
                    """,
                    (dataset_id, start_key),
                ).fetchall()
    return [_bar_payload(row, include_ts=True) for row in rows]


def market_series_range_observation(
    root: Path,
    identifier: str,
    *,
    bars: int | None = None,
    calendar_days: int | None = None,
) -> dict[str, Any]:
    if bars is not None and calendar_days is not None:
        raise ValueError("choose either --bars or --calendar-days")
    if bars is None and calendar_days is None:
        raise ValueError("range observation requires --bars N or --calendar-days N")
    if bars is not None and bars < 0:
        raise ValueError("--bars cannot be negative")
    if calendar_days is not None and calendar_days < 0:
        raise ValueError("--calendar-days cannot be negative")

    found = find_market_series(root, identifier)
    if not found:
        record = find_instrument(root, identifier)
        if record:
            found = find_market_series(root, str(record.get("ticker", "")))
    if not found:
        return {
            "object_type": "market_data_gateway_market_series_range_observation",
            "query": identifier,
            "found": False,
            "candidate_series": search_market_series(root, identifier, limit=5),
            "next_move": f"./xctx discover {scoped_ref()} search_market_series <ticker|issuer|provider|text>",
        }

    unit = "bars" if bars is not None else "calendar_days"
    value = int(bars if bars is not None else calendar_days)
    ranged_bars = _range_bars(root, found.get("dataset_id"), bars=bars, calendar_days=calendar_days)
    csv_path = _write_bars_csv(root, found, ranged_bars, value, unit)
    coverage = {
        "start_date": ranged_bars[0]["date"] if ranged_bars else None,
        "end_date": ranged_bars[-1]["date"] if ranged_bars else None,
    }
    payload = {
        "object_type": "market_data_gateway_market_series_range_observation",
        "found": True,
        "market_series_id": found["market_series_id"],
        "instrument_id": found["instrument_id"],
        "ticker": found["ticker"],
        "request": {"unit": unit, "value": value, "all_available": value == 0},
        "returned_bars": len(ranged_bars),
        "coverage": coverage,
        "latest_bar_date": found.get("latest_bar", {}).get("date"),
        "price_summary": _price_range_summary(ranged_bars),
        "requested_identifier": identifier,
        "csv": {
            "path": str(csv_path.relative_to(root)),
            "format": "csv",
            "columns": BAR_CSV_COLUMNS,
        },
        "bars_inline": len(ranged_bars) <= INLINE_BAR_LIMIT,
        "inline_bar_limit": INLINE_BAR_LIMIT,
        "data_boundary": "Bundled read-only OHLCV fixture; not a live quote feed and not investment advice.",
    }
    if len(ranged_bars) <= INLINE_BAR_LIMIT:
        payload["bars"] = ranged_bars
    else:
        payload["bars_omitted_from_json"] = len(ranged_bars)
    return payload


def latest_price_observation(root: Path, identifier: str) -> dict[str, Any]:
    """Return the latest available daily OHLCV close for an instrument/series.

    This is deliberately a bundled-data observation, not a live quote. The payload
    states that boundary explicitly so agents do not confuse freshness with a
    production market-data feed.
    """
    found = find_market_series(root, identifier)
    record = find_instrument(root, identifier)
    if not found and record:
        found = find_market_series(root, str(record.get("ticker", "")))
    if not found:
        return {
            "object_type": "market_data_gateway_latest_price_observation",
            "query": identifier,
            "found": False,
            "candidate_instruments": search_instruments(root, identifier, limit=5),
            "candidate_series": search_market_series(root, identifier, limit=5),
            "empty_result_guidance": "Try ticker, instrument:<ticker>, issuer:cik:<CIK>, or a company name first.",
            "next_move": f"./xctx discover {scoped_ref()} search_entity_instrument <company|ticker|CIK|alias>",
        }

    if not record:
        record = find_instrument(root, str(found.get("ticker", "")))
    currency = str((record or {}).get("currency") or "USD")
    latest_price = _latest_available_price_payload(found, currency)
    return {
        "object_type": "market_data_gateway_latest_price_observation",
        "found": True,
        "requested_identifier": identifier,
        "market_series_id": found["market_series_id"],
        "ohlcv_series_id": found.get("ohlcv_series_id"),
        "instrument_id": found["instrument_id"],
        "issuer_id": found.get("issuer_id"),
        "ticker": found["ticker"],
        "issuer_name": found.get("issuer_name"),
        "latest_available_price": latest_price,
        "coverage": found.get("coverage"),
        "bar_count": found.get("bar_count"),
        "provider": found.get("provider"),
        "evidence": found.get("evidence"),
        "freshness": {
            "latest_available_bar_date": latest_price.get("date"),
            "is_live_quote": False,
            "boundary": "latest available bar in bundled read-only fixture",
        },
        "data_boundary": "Bundled read-only OHLCV fixture; latest_available_price is not a live market quote and is not investment advice.",
        "next_moves": [
            f"./xctx observe {scoped_ref()} {found['market_series_id']}",
            f"./xctx observe {scoped_ref()} {found['ticker']} --bars 5",
            f"./xctx observe {scoped_ref()} {found['ticker']} --calendar-days 30",
        ],
    }


def market_series_observation(root: Path, identifier: str) -> dict[str, Any]:
    found = find_market_series(root, identifier)
    if not found:
        return {
            "object_type": "market_data_gateway_market_series_observation",
            "query": identifier,
            "found": False,
            "candidate_series": search_market_series(root, identifier, limit=5),
            "next_move": f"./xctx discover {scoped_ref()} search_market_series <ticker|issuer|provider|text>",
        }
    payload = dict(found)
    record = find_instrument(root, str(found.get("ticker", "")))
    currency = str((record or {}).get("currency") or "USD")
    payload.update(
        {
            "object_type": "market_data_gateway_market_series_observation",
            "found": True,
            "latest_available_price": _latest_available_price_payload(found, currency),
            "sample_bars_last_5": _sample_bars(root, found.get("dataset_id")),
            "next_moves": [
                f"./xctx discover {agent_domain_id()}::latest_price {found['ticker']}",
                f"./xctx observe {scoped_ref()} {found['ticker']} --bars 5",
                f"./xctx observe {scoped_ref()} {found['ticker']} --calendar-days 30",
            ],
            "data_boundary": "Bundled read-only OHLCV fixture; not a live quote feed and not investment advice.",
        }
    )
    return payload


def instrument_registry_discovery(root: Path) -> dict[str, Any]:
    instruments = load_all_instruments(root)
    mstats = market_stats(root)
    return {
        "object_type": "market_data_gateway_discovery",
        "context_state": "without_equity",
        "description": "Search this subdomain first when an agent has a company, ticker, CIK, or alias and needs the canonical local ID or a bundled OHLCV series.",
        "data_description": "Bundled read-only canonical instrument seed set plus bundled read-only mini_stocks SQLite market-series fixture.",
        "stats": {
            "canonical_instruments": len(instruments),
            "active_instruments": sum(1 for item in instruments if item.get("status") == "active"),
            "id_namespace": "instrument:<lowercase_primary_ticker>",
            "issuer_namespace": "issuer:cik:<10_digit_cik>",
            "market_series_namespace": "market_series:<lowercase_ticker>:daily",
            **mstats,
        },
        "search_fields": ["instrument_id", "issuer_id", "ticker", "name", "cik", "aliases", "ticker_aliases", "exchange", "mic", "market_series_id", "provider", "figi"],
        "actions": {
            "search_entity_instrument": {
                "priority": 10,
                "desc": "Find the canonical stock_intelligence_hub instrument id.",
                "run_cmd": f"./xctx discover {scoped_ref()} search_entity_instrument <company|ticker|CIK|alias>",
            },
            "search_market_series": {
                "priority": 15,
                "desc": "Find a bundled read-only daily OHLCV series.",
                "run_cmd": f"./xctx discover {scoped_ref()} search_market_series <ticker|issuer|provider|text>",
            },
            "latest_price": {
                "priority": 18,
                "desc": "Return the latest available bundled daily OHLCV close for a resolved instrument or series; not a live quote.",
                "run_cmd": f"./xctx discover {agent_domain_id()}::latest_price <ticker|instrument|CIK>",
            },
            "list_instruments": {
                "priority": 20,
                "desc": "Enumerate canonical instruments without guessing a company name or ticker.",
                "run_cmd": f"./xctx discover {scoped_ref()} list_instruments [--limit N] [--cursor CURSOR] [--status STATUS] [--exchange EXCHANGE] [--security-type TYPE]",
            },
            "observe_instrument_or_series": {
                "priority": 30,
                "desc": "Observe the canonical instrument record or a bundled market series.",
                "run_cmd": f"./xctx observe {scoped_ref()} <instrument_id|ticker|CIK|market_series:ticker:daily>",
            },
        },
        "sample_records": [public_instrument(item) for item in instruments[:3]],
        "sample_market_series": search_market_series(root, "", limit=3),
    }


def instrument_search_payload(root: Path, query: str) -> dict[str, Any]:
    total_matches, matches = search_instruments_with_total(root, query, limit=DEFAULT_SEARCH_LIMIT)
    return {
        "object_type": "market_data_gateway::search_entity_instrument::result",
        "query": query,
        "total_matches": total_matches,
        "matches_returned": len(matches),
        "limit": DEFAULT_SEARCH_LIMIT,
        "resolver_policy": "Exact ticker, instrument id, and CIK matches rank before exact aliases, normalized legal-name matches, prefixes, and broad text matches.",
        "matches": matches,
        "data_boundary": "Minimum identity result only. Use each match next_moves to discover filings, latest available price, or market series explicitly.",
        "empty_result_guidance": None if matches else "Try ticker, company legal name, CIK, or issuer:cik:<CIK>.",
    }


def market_series_search_payload(root: Path, query: str) -> dict[str, Any]:
    matches = search_market_series(root, query)
    return {
        "object_type": "market_data_gateway::search_market_series::result",
        "query": query,
        "matches_returned": len(matches),
        "matches": matches,
        "empty_result_guidance": None if matches else "Try a ticker from the bundled mini fixture, for example AAPL, A, AA, ABNB, or CBOE.",
    }


def instrument_observation(root: Path, identifier: str, range_request: dict[str, int] | None = None) -> dict[str, Any]:
    if range_request:
        return market_series_range_observation(
            root,
            identifier,
            bars=range_request.get("bars"),
            calendar_days=range_request.get("calendar_days"),
        )
    if identifier.lower().startswith(("market_series:", "ohlcv_series:")):
        return market_series_observation(root, identifier)
    record = find_instrument(root, identifier)
    if not record:
        series = find_market_series(root, identifier)
        if series:
            return market_series_observation(root, identifier)
        return {
            "object_type": "market_data_gateway_instrument_observation",
            "query": identifier,
            "found": False,
            "candidate_instruments": search_instruments(root, identifier, limit=5),
            "candidate_market_series": search_market_series(root, identifier, limit=5),
            "next_move": f"./xctx discover {scoped_ref()} search_entity_instrument <company|ticker|CIK|alias>",
        }
    payload = public_instrument(record, include_aliases=True)
    series = find_market_series(root, str(record.get("ticker", "")))
    latest_price = _latest_available_price_payload(series, str(record.get("currency") or "USD")) if series else None
    payload.update(
        {
            "object_type": "market_data_gateway_instrument_observation",
            "found": True,
            "trusted_id_scope": "stock_intelligence_hub",
            "valid_in_subdomains": ["market_data_gateway", "equity_filing"],
            "market_series_available": bool(series),
            "market_series": series,
            "latest_available_price": latest_price,
            "next_moves": [
                f"./xctx discover stock_intelligence_hub::equity_filing {record['instrument_id']}",
                f"./xctx observe stock_intelligence_hub::equity_filing {record['instrument_id']}",
                f"./xctx discover {agent_domain_id()}::latest_price {record['ticker']}",
                f"./xctx discover {scoped_ref()} search_market_series {record['ticker']}",
            ],
        }
    )
    return payload


def instrument_audit(root: Path) -> dict[str, Any]:
    instruments = load_all_instruments(root)
    ids = [item.get("instrument_id") for item in instruments]
    ciks = [item.get("cik") for item in instruments]
    checks = [
        {
            "id": "audit:market_data_gateway:instrument_data_file_exists",
            "status": "pass" if instrument_data_path(root).exists() else "fail",
            "path": str(INSTRUMENT_DATA),
        },
        {
            "id": "audit:market_data_gateway:mini_stocks_sqlite_exists",
            "status": "pass" if market_db_path(root).exists() else "fail",
            "path": str(MINI_STOCKS_DB),
        },
        {
            "id": "audit:market_data_gateway:instrument_count",
            "status": "pass" if instruments else "fail",
            "value": len(instruments),
        },
        {
            "id": "audit:market_data_gateway:unique_instrument_ids",
            "status": "pass" if len(ids) == len(set(ids)) else "fail",
            "value": len(set(ids)),
        },
        {
            "id": "audit:market_data_gateway:cik_shape",
            "status": "pass" if all(isinstance(cik, str) and len(cik) == 10 and cik.isdigit() for cik in ciks) else "fail",
            "value": len(ciks),
        },
    ]
    if market_db_path(root).exists():
        mstats = market_stats(root)
        checks.extend(
            [
                {"id": "audit:market_data_gateway:market_reference_count", "status": "pass" if mstats["reference_universe_snapshots"] > 0 else "fail", "value": mstats["reference_universe_snapshots"]},
                {"id": "audit:market_data_gateway:ohlcv_series_count", "status": "pass" if mstats["ohlcv_series"] > 0 else "fail", "value": mstats["ohlcv_series"]},
                {"id": "audit:market_data_gateway:ohlcv_bars_count", "status": "pass" if mstats["ohlcv_bars"] > 0 else "fail", "value": mstats["ohlcv_bars"]},
                {"id": "audit:market_data_gateway:aapl_market_series_resolves", "status": "pass" if find_market_series(root, "AAPL") else "warn"},
                {"id": "audit:market_data_gateway:aapl_latest_price_resolves", "status": "pass" if latest_price_observation(root, "AAPL").get("found") else "warn"},
                {"id": "audit:market_data_gateway:aapl_cik_resolves", "status": "pass" if (find_instrument(root, "issuer:cik:0000320193") or {}).get("ticker") == "AAPL" else "warn"},
                {"id": "audit:market_data_gateway:apple_punctuation_name_resolves", "status": "pass" if (search_instruments(root, "Apple, Inc.", limit=1) or [{}])[0].get("ticker") == "AAPL" else "warn"},
            ]
        )
    return {"object_type": "market_data_gateway_audit", "checks": checks, "stats": {"canonical_instruments": len(instruments), **(market_stats(root) if market_db_path(root).exists() else {})}}
