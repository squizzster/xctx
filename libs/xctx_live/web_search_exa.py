from __future__ import annotations

import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import random
import re
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


SCHEMA_VERSION = "1"
LIBRARY_RUNTIME_PATH = Path("web_search") / "exa_search"
REGISTRY_FILENAME = "registry.sqlite"
ARTIFACTS_DIRNAME = "artifacts"
RATE_LIMIT_FILENAME = "exa_rate_limits.sqlite"
RATE_LIMIT_LOCK_FILENAME = "exa_rate_limits.lock"
LIST_DEFAULT_LIMIT = 10
LIST_MAX_LIMIT = 100
FAST_DEFAULT_RESULTS = 6
DEEP_DEFAULT_RESULTS = 3
PAGE_DEFAULT_MAX_CHARACTERS = 4096
OBSERVE_HELPER_PREVIEW_CHARS = 1200
SEARCH_DEFAULT_QPS = 8
CONTENTS_DEFAULT_QPS = 80
RETRY_MAX_ATTEMPTS = 4
RETRY_BASE_SECONDS = 0.75
RETRY_MAX_SECONDS = 12.0
TIMEOUT_RETRY_SECONDS = 30.0
WEB_SEARCH_REF = "web_search::exa_search"
URL_RE = re.compile(r"^https?://[^/\s]+", re.IGNORECASE)


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
    for method_name in ("model_dump", "to_dict", "dict", "to_json"):
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
            except json.JSONDecodeError:
                return result
        return _json_safe(result)
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value))
    return str(value)


def _runtime_root(root: Path) -> Path:
    configured = os.environ.get("XCTX_RUNTIME_DIR")
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else root / path
    return root / ".xctx_runtime"


def library_paths(root: Path) -> dict[str, Path]:
    base = _runtime_root(root) / LIBRARY_RUNTIME_PATH
    state_override = os.environ.get("EXA_RATE_LIMIT_STATE_DIR")
    if state_override:
        state_dir = Path(state_override)
        if not state_dir.is_absolute():
            state_dir = root / state_dir
    else:
        state_dir = base
    return {
        "base": base,
        "registry": base / REGISTRY_FILENAME,
        "artifacts": base / ARTIFACTS_DIRNAME,
        "rate_db": state_dir / RATE_LIMIT_FILENAME,
        "rate_lock": state_dir / RATE_LIMIT_LOCK_FILENAME,
    }


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _fsync_parent(path: Path) -> None:
    try:
        fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    _ensure_parent(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _fsync_parent(path)
    finally:
        if tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_text(path, _pretty_json(value))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _connect(root: Path) -> sqlite3.Connection:
    paths = library_paths(root)
    paths["registry"].parent.mkdir(parents=True, exist_ok=True)
    paths["artifacts"].mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(paths["registry"])
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _connect_existing(root: Path) -> sqlite3.Connection | None:
    path = library_paths(root)["registry"]
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS registry_meta(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs(
          run_id TEXT PRIMARY KEY,
          operation TEXT NOT NULL,
          source TEXT NOT NULL,
          query TEXT,
          url TEXT,
          status TEXT NOT NULL,
          result_count INTEGER NOT NULL DEFAULT 0,
          plan_id TEXT,
          commit_id TEXT,
          result_id TEXT,
          created_at TEXT NOT NULL,
          finished_at TEXT NOT NULL,
          raw_path TEXT,
          results_path TEXT,
          markdown_path TEXT,
          manifest_path TEXT,
          summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS results(
          result_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL,
          ordinal INTEGER NOT NULL,
          operation TEXT NOT NULL,
          title TEXT,
          url TEXT,
          published_date TEXT,
          author TEXT,
          score REAL,
          text_preview TEXT,
          raw_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS artifacts(
          artifact_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          path TEXT NOT NULL,
          bytes INTEGER NOT NULL,
          sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_runs_created
          ON runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_results_run
          ON results(run_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_results_url
          ON results(url);
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO registry_meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def _empty_stats(root: Path) -> dict[str, Any]:
    paths = library_paths(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "registry_initialized": False,
        "registry_path": _display_path(root, paths["registry"]),
        "artifact_root": _display_path(root, paths["artifacts"]),
        "run_count": 0,
        "result_count": 0,
        "artifact_count": 0,
        "last_run_at": None,
        "operations": {},
    }


def registry_stats(root: Path) -> dict[str, Any]:
    conn = _connect_existing(root)
    if conn is None:
        return _empty_stats(root)
    with conn:
        stats = _empty_stats(root)
        stats["registry_initialized"] = True
        stats["run_count"] = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        stats["result_count"] = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        stats["artifact_count"] = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        stats["last_run_at"] = conn.execute("SELECT MAX(created_at) FROM runs").fetchone()[0]
        stats["operations"] = {
            str(row["operation"]): int(row["count"])
            for row in conn.execute("SELECT operation, COUNT(*) AS count FROM runs GROUP BY operation ORDER BY operation")
        }
        return stats


def _exa_identity_status() -> dict[str, Any]:
    for key in ("XCTX_EXA_API_KEY", "EXA_API_KEY"):
        value = os.environ.get(key)
        if value and value.strip():
            return {"available": True, "source": key, "value_printed": False}
    return {"available": False, "source": None, "value_printed": False}


def _exa_api_key() -> str | None:
    for key in ("XCTX_EXA_API_KEY", "EXA_API_KEY"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    return None


def _exa_sdk_available() -> bool:
    return importlib.util.find_spec("exa_py") is not None


def _detail_level() -> str:
    level = str(os.environ.get("XCTX_DETAIL_LEVEL") or "basic").strip().lower()
    return level if level in {"basic", "more", "max"} else "basic"


def _load_exa_class() -> Any:
    from exa_py import Exa  # noqa: PLC0415

    return Exa


def _provider_readiness() -> dict[str, Any]:
    identity = _exa_identity_status()
    sdk_available = _exa_sdk_available()
    return {
        "identity": identity,
        "sdk": {"available": sdk_available, "package": "exa-py", "import_name": "exa_py"},
        "ready_for_live": bool(identity["available"] and sdk_available),
    }


def _search_plan_cmd(query: str | None = None) -> str:
    text = str(query or "latest SEC EDGAR rate limits").strip()
    return f"./xctx plan {WEB_SEARCH_REF}::search_fast --query {json.dumps(text)}"


def _deep_plan_cmd(query: str | None = None) -> str:
    text = str(query or "OpenAI latest model documentation").strip()
    return f"./xctx plan {WEB_SEARCH_REF}::search_deep --deep-query {json.dumps(text)}"


def _page_plan_cmd(url: str | None = None) -> str:
    target = str(url or "https://docs.exa.ai/reference/search").strip()
    return f"./xctx plan {WEB_SEARCH_REF}::fetch_page --url {target}"


def _list_runs_cmd() -> str:
    return f"./xctx discover {WEB_SEARCH_REF}::list_search_runs"


def _list_results_cmd() -> str:
    return f"./xctx discover {WEB_SEARCH_REF}::list_results"


def discover_exa_search(root: Path, projection: str = "compact") -> dict[str, Any]:
    if projection not in {"compact", "full"}:
        raise ValueError("--projection must be compact or full")
    if projection == "compact" and _detail_level() in {"more", "max"}:
        projection = "full"
    stats = registry_stats(root)
    paths = library_paths(root)
    payload: dict[str, Any] = {
        "object_type": "web_search_exa_discovery",
        "provider": "exa",
        "projection": projection,
        "storage": {
            "engine": "sqlite",
            "registry_path": stats["registry_path"],
            "artifact_root": stats["artifact_root"],
            "registry_initialized": stats["registry_initialized"],
        },
        "local_availability": {
            "runs": stats["run_count"],
            "results": stats["result_count"],
            "artifacts": stats["artifact_count"],
            "last_run_at": stats["last_run_at"],
        },
        "provider_readiness": _provider_readiness(),
        "planned_effects": [
            {
                "action": "search_fast",
                "recommended": True,
                "run_cmd": _search_plan_cmd(),
                "writes_to_db": True,
            },
            {
                "action": "search_deep",
                "recommended": False,
                "run_cmd": _deep_plan_cmd(),
                "writes_to_db": True,
            },
            {
                "action": "fetch_page",
                "recommended": False,
                "run_cmd": _page_plan_cmd(),
                "writes_to_db": True,
            },
        ],
        "discoverable_modes": [
            {"id": "list_search_runs", "run_cmd": _list_runs_cmd()},
            {"id": "list_results", "run_cmd": _list_results_cmd()},
            {"id": "observe", "run_cmd": f"./xctx observe {WEB_SEARCH_REF} status"},
        ],
        "next_moves": [
            {"run_cmd": _search_plan_cmd(), "why": "Run a broad Exa search and index result cards."},
            {"run_cmd": _list_results_cmd(), "why": "Inspect local web results that are already available."},
            {"run_cmd": f"./xctx audit {WEB_SEARCH_REF}", "why": "Check provider readiness and registry paths."},
        ],
        "rate_limits": {
            "search_qps_default": SEARCH_DEFAULT_QPS,
            "contents_qps_default": CONTENTS_DEFAULT_QPS,
            "state_path": _display_path(root, paths["rate_db"]),
            "retry_policy": "429, retryable 5xx, timeouts, Retry-After, exponential backoff, jitter",
        },
        "framework_boundary": "Exa provider calls, search artifacts, registry state, retries, and rate limits are owned by this web_search domain adapter, not by generic xctx runtime code.",
    }
    if projection == "full":
        payload["stats"] = stats
        payload["artifact_kinds"] = ["raw_json", "results_json", "markdown", "manifest"]
        payload["identity_notes"] = [
            "XCTX_EXA_API_KEY is preferred when set.",
            "EXA_API_KEY is accepted as a provider fallback.",
            "Credential values are never printed.",
        ]
    return payload


def _parse_int(value: Any, *, default: int, minimum: int, maximum: int, flag: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{flag} requires an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{flag} must be at least {minimum}")
    if parsed > maximum:
        raise ValueError(f"{flag} must be at most {maximum}")
    return parsed


def _option(args: list[str], flag: str, *, default: str | None = None, required: bool = False) -> str | None:
    if flag not in args:
        if required:
            raise ValueError(f"{flag} is required")
        return default
    index = args.index(flag)
    if index + 1 >= len(args):
        raise ValueError(f"{flag} requires a value")
    return args[index + 1]


def _parse_request(args: list[str], operation: str) -> dict[str, Any]:
    source = str(_option(args, "--source", default="live") or "live").strip()
    if source not in {"live", "fixture"}:
        raise ValueError("--source must be live or fixture")
    request: dict[str, Any] = {
        "operation": operation,
        "source": source,
        "fixture_path": _option(args, "--fixture-path"),
    }
    if operation in {"search_fast", "search_deep"}:
        query = str(_option(args, "--query", required=True) or "").strip()
        if not query:
            raise ValueError("--query must be non-empty")
        default_results = FAST_DEFAULT_RESULTS if operation == "search_fast" else DEEP_DEFAULT_RESULTS
        max_results = 10 if operation == "search_fast" else 5
        request["query"] = query
        request["num_results"] = _parse_int(
            _option(args, "--num-results"),
            default=default_results,
            minimum=1,
            maximum=max_results,
            flag="--num-results",
        )
    elif operation == "fetch_page":
        url = str(_option(args, "--url", required=True) or "").strip()
        if not _looks_like_url(url):
            raise ValueError("--url must start with http:// or https:// and include a host")
        request["url"] = url
        request["max_characters"] = _parse_int(
            _option(args, "--max-characters"),
            default=PAGE_DEFAULT_MAX_CHARACTERS,
            minimum=256,
            maximum=20000,
            flag="--max-characters",
        )
    else:
        raise ValueError(f"unknown Exa operation: {operation}")
    return request


def _looks_like_url(value: str) -> bool:
    if not URL_RE.match(value.strip()):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _fixture_path(root: Path, request: dict[str, Any]) -> Path:
    raw = str(request.get("fixture_path") or "").strip()
    if not raw:
        raise ValueError("--fixture-path is required when --source fixture is selected")
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        raise ValueError(f"fixture path is not a file: {path}")
    return path


def _validate_plan(root: Path, args: list[str], operation: str) -> dict[str, Any]:
    try:
        request = _parse_request(args, operation)
        if request["source"] == "fixture":
            fixture = _fixture_path(root, request)
            source_status = {"kind": "fixture", "fixture_path": _display_path(root, fixture)}
        else:
            readiness = _provider_readiness()
            if not readiness["identity"]["available"]:
                return {
                    "ok": False,
                    "error": "live Exa search requires XCTX_EXA_API_KEY or EXA_API_KEY",
                    "next_moves": [
                        {"run_cmd": "export XCTX_EXA_API_KEY=<exa-api-key>"},
                        {"run_cmd": _search_plan_cmd(request.get("query"))},
                    ],
                }
            if not readiness["sdk"]["available"]:
                return {
                    "ok": False,
                    "error": "live Exa search requires the exa-py package",
                    "next_moves": [
                        {"run_cmd": "uv pip install exa-py"},
                        {"run_cmd": _search_plan_cmd(request.get("query"))},
                    ],
                }
            source_status = {"kind": "live", "provider": "exa", "identity_source": readiness["identity"]["source"]}
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "next_moves": [{"run_cmd": f"./xctx plan {WEB_SEARCH_REF}::{operation}"}]}
    return {
        "ok": True,
        "object_type": "web_search_exa_preflight",
        "operation": operation,
        "source": source_status,
        "request": _redacted_request(request),
        "writes_to_db": True,
        "result_handle": "created after execute --commit",
    }


def validate_search_fast(root: Path, args: list[str]) -> dict[str, Any]:
    return _validate_plan(root, args, "search_fast")


def validate_search_deep(root: Path, args: list[str]) -> dict[str, Any]:
    return _validate_plan(root, args, "search_deep")


def validate_fetch_page(root: Path, args: list[str]) -> dict[str, Any]:
    return _validate_plan(root, args, "fetch_page")


def _redacted_request(request: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in request.items() if key != "fixture_path"}


def _xctx_context(args: list[str]) -> dict[str, str]:
    return {
        "plan_id": str(_option(args, "--xctx-plan-id", required=True)),
        "commit_id": str(_option(args, "--xctx-commit-id", required=True)),
        "result_id": str(_option(args, "--xctx-result-id", required=True)),
    }


def _run_id(operation: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{operation.replace('_', '-')}-{os.getpid()}-{random.randrange(1_000_000_000):09d}"


def _artifact_paths(root: Path, run_id: str, operation: str) -> dict[str, Path]:
    run_dir = library_paths(root)["artifacts"] / "runs" / run_id
    raw_label = "raw_page" if operation == "fetch_page" else f"raw_{operation}"
    return {
        "run_dir": run_dir,
        "raw_json": run_dir / f"{raw_label}.json",
        "results_json": run_dir / "results.json",
        "markdown": run_dir / "search.md",
        "manifest": run_dir / "manifest.json",
    }


def _execute_fixture(root: Path, request: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    fixture = _fixture_path(root, request)
    raw = _read_json(fixture)
    results = _extract_results(raw)
    heartbeats = [
        {
            "phase": "fixture_loaded",
            "message": "Loaded fixture response and will index it as Exa-shaped search data.",
            "fixture_path": _display_path(root, fixture),
            "result_count": len(results),
        }
    ]
    return _json_safe(raw), results, heartbeats


def _execute_live(root: Path, request: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    api_key = _exa_api_key()
    if not api_key:
        raise ValueError("live Exa search requires XCTX_EXA_API_KEY or EXA_API_KEY")
    if not _exa_sdk_available():
        raise ValueError("live Exa search requires the exa-py package")
    Exa = _load_exa_class()
    client = Exa(api_key=api_key)
    heartbeats: list[dict[str, Any]] = []
    operation = str(request["operation"])
    if operation == "search_fast":
        response = _call_exa_with_retries(
            root,
            "search",
            lambda: client.search(
                str(request["query"]),
                num_results=int(request["num_results"]),
                type="auto",
                contents={"highlights": True},
            ),
            heartbeats,
        )
    elif operation == "search_deep":
        response = _call_exa_with_retries(
            root,
            "search",
            lambda: client.search(
                str(request["query"]),
                num_results=int(request["num_results"]),
                type="deep-lite",
                output_schema={"type": "text"},
                contents={"highlights": True},
            ),
            heartbeats,
        )
    elif operation == "fetch_page":
        response = _call_exa_with_retries(
            root,
            "contents",
            lambda: client.get_contents(
                [str(request["url"])],
                highlights={"max_characters": int(request["max_characters"])},
            ),
            heartbeats,
        )
    else:
        raise ValueError(f"unknown Exa operation: {operation}")
    raw = _json_safe(response)
    return raw, _extract_results(raw), heartbeats


def _extract_results(raw: Any) -> list[dict[str, Any]]:
    value = _json_safe(raw)
    if isinstance(value, dict):
        results = value.get("results")
        if isinstance(results, list):
            return [_coerce_result(item) for item in results]
        if any(key in value for key in ("url", "title", "text", "highlights")):
            return [_coerce_result(value)]
    if isinstance(value, list):
        return [_coerce_result(item) for item in value]
    return []


def _coerce_result(item: Any) -> dict[str, Any]:
    value = _json_safe(item)
    if isinstance(value, dict):
        return value
    return {"value": value}


def _result_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    seen: set[str] = set()

    def add_part(value: Any) -> None:
        if not isinstance(value, str):
            return
        text = value.strip()
        if not text or text in seen:
            return
        seen.add(text)
        parts.append(text)

    for key in ("summary", "text", "highlight", "snippet"):
        add_part(result.get(key))
    highlights = result.get("highlights")
    if isinstance(highlights, list):
        for item in highlights:
            if isinstance(item, str):
                add_part(item)
            elif isinstance(item, dict):
                add_part(item.get("text") or item.get("highlight"))
    return "\n\n".join(parts)


def _primary_result_text(result: dict[str, Any]) -> str:
    for key in ("text", "summary", "highlight", "snippet"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    highlights = result.get("highlights")
    if isinstance(highlights, list):
        for item in highlights:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                text = item.get("text") or item.get("highlight")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return ""


def _results_to_markdown(operation: str, request: dict[str, Any], results: list[dict[str, Any]]) -> str:
    source_line = f"- Query: {request.get('query')}" if request.get("query") else f"- URL: {request.get('url')}"
    lines = [
        f"# Exa {operation.replace('_', ' ')}",
        "",
        f"- Generated: {_now()}",
        f"- Source: {request.get('source')}",
        source_line,
        f"- Results: {len(results)}",
        "",
    ]
    for index, result in enumerate(results, start=1):
        title = str(result.get("title") or result.get("url") or f"Result {index}")
        url = str(result.get("url") or "").strip()
        lines.extend([f"## {index}. {title}", ""])
        if url:
            lines.extend([f"- URL: {url}"])
        for key in ("publishedDate", "published_date", "author", "score"):
            value = result.get(key)
            if value not in (None, ""):
                lines.append(f"- {key}: {value}")
        text = _result_text(result)
        if text:
            lines.extend(["", text[:3000], ""])
        else:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _result_id(run_id: str, index: int, result: dict[str, Any]) -> str:
    seed = _json({"run_id": run_id, "index": index, "url": result.get("url"), "title": result.get("title")})
    return "web_result:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _artifact_id(path: Path) -> str:
    return "web_artifact:" + _file_sha256(path)


def _write_run_artifacts(
    root: Path,
    *,
    run_id: str,
    operation: str,
    request: dict[str, Any],
    raw: dict[str, Any],
    results: list[dict[str, Any]],
    markdown: str,
    heartbeats: list[dict[str, Any]],
) -> dict[str, Path]:
    paths = _artifact_paths(root, run_id, operation)
    _atomic_write_json(paths["raw_json"], raw)
    _atomic_write_json(paths["results_json"], results)
    _atomic_write_text(paths["markdown"], markdown)
    manifest = {
        "success": True,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _now(),
        "provider": "exa",
        "operation": operation,
        "source": request.get("source"),
        "run_id": run_id,
        "search_run_ref": f"search_run:{run_id}",
        "request": _redacted_request(request),
        "files": {
            key: _display_path(root, value)
            for key, value in paths.items()
            if key != "run_dir"
        },
        "result_count": len(results),
        "heartbeats": heartbeats,
        "preview": markdown[:1200],
    }
    _atomic_write_json(paths["manifest"], manifest)
    return paths


def _index_run(
    root: Path,
    *,
    run_id: str,
    operation: str,
    request: dict[str, Any],
    raw: dict[str, Any],
    results: list[dict[str, Any]],
    paths: dict[str, Path],
    xctx: dict[str, str],
    heartbeats: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    created_at = _now()
    indexed_results: list[dict[str, Any]] = []
    with _connect(root) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs(
              run_id, operation, source, query, url, status, result_count,
              plan_id, commit_id, result_id, created_at, finished_at,
              raw_path, results_path, markdown_path, manifest_path, summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                operation,
                str(request.get("source") or ""),
                request.get("query"),
                request.get("url"),
                "ok",
                len(results),
                xctx.get("plan_id"),
                xctx.get("commit_id"),
                xctx.get("result_id"),
                created_at,
                created_at,
                str(paths["raw_json"]),
                str(paths["results_json"]),
                str(paths["markdown"]),
                str(paths["manifest"]),
                _json({"heartbeats": heartbeats, "raw_shape": sorted(raw.keys()) if isinstance(raw, dict) else []}),
            ),
        )
        for kind in ("raw_json", "results_json", "markdown", "manifest"):
            path = paths[kind]
            sha = _file_sha256(path)
            conn.execute(
                """
                INSERT OR REPLACE INTO artifacts(artifact_id, run_id, kind, path, bytes, sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "web_artifact:" + sha,
                    run_id,
                    kind,
                    str(path),
                    path.stat().st_size,
                    sha,
                    created_at,
                ),
            )
        for index, result in enumerate(results, start=1):
            rid = _result_id(run_id, index, result)
            text_preview = _result_text(result)[:2000]
            conn.execute(
                """
                INSERT OR REPLACE INTO results(
                  result_id, run_id, ordinal, operation, title, url, published_date,
                  author, score, text_preview, raw_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rid,
                    run_id,
                    index,
                    operation,
                    result.get("title"),
                    result.get("url"),
                    result.get("publishedDate") or result.get("published_date"),
                    result.get("author"),
                    result.get("score") if isinstance(result.get("score"), (int, float)) else None,
                    text_preview,
                    _json(result),
                    created_at,
                ),
            )
            indexed_results.append(
                {
                    "id": rid,
                    "title": result.get("title") or result.get("url") or f"Result {index}",
                    "url": result.get("url"),
                    "observe_cmd": f"./xctx observe {WEB_SEARCH_REF} {rid}",
                }
            )
        conn.commit()
    return indexed_results


def _commit(root: Path, args: list[str], operation: str) -> dict[str, Any]:
    request = _parse_request(args, operation)
    xctx = _xctx_context(args)
    run_id = _run_id(operation)
    if request["source"] == "fixture":
        raw, results, heartbeats = _execute_fixture(root, request)
    else:
        raw, results, heartbeats = _execute_live(root, request)
    markdown = _results_to_markdown(operation, request, results)
    paths = _write_run_artifacts(
        root,
        run_id=run_id,
        operation=operation,
        request=request,
        raw=raw,
        results=results,
        markdown=markdown,
        heartbeats=heartbeats,
    )
    indexed_results = _index_run(
        root,
        run_id=run_id,
        operation=operation,
        request=request,
        raw=raw,
        results=results,
        paths=paths,
        xctx=xctx,
        heartbeats=heartbeats,
    )
    artifacts = [
        {
            "id": _artifact_id(paths[kind]),
            "kind": kind,
            "path": _display_path(root, paths[kind]),
            "observe_cmd": f"./xctx observe {WEB_SEARCH_REF} {_artifact_id(paths[kind])}",
        }
        for kind in ("raw_json", "results_json", "markdown", "manifest")
    ]
    return {
        "object_type": "web_search_exa_commit_result",
        "status": "committed",
        "provider": "exa",
        "operation": operation,
        "source": request["source"],
        "request": _redacted_request(request),
        "run_id": run_id,
        "search_run_ref": f"search_run:{run_id}",
        "result_count": len(indexed_results),
        "results": indexed_results[:25],
        "artifacts": artifacts,
        "registry": registry_stats(root),
        "heartbeats": heartbeats,
        "xctx": {"plan_id": xctx["plan_id"], "commit_id": xctx["commit_id"], "result_id": xctx["result_id"]},
        "next_moves": [
            {"run_cmd": f"./xctx observe {xctx['result_id']}"},
            {"run_cmd": f"./xctx observe {WEB_SEARCH_REF} search_run:{run_id}"},
            {"run_cmd": _list_results_cmd()},
        ],
    }


def commit_search_fast(root: Path, args: list[str]) -> dict[str, Any]:
    return _commit(root, args, "search_fast")


def commit_search_deep(root: Path, args: list[str]) -> dict[str, Any]:
    return _commit(root, args, "search_deep")


def commit_fetch_page(root: Path, args: list[str]) -> dict[str, Any]:
    return _commit(root, args, "fetch_page")


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _qps_for_endpoint(endpoint: str) -> int:
    if endpoint == "contents":
        return _int_env("EXA_CONTENTS_QPS", CONTENTS_DEFAULT_QPS)
    return _int_env("EXA_SEARCH_QPS", SEARCH_DEFAULT_QPS)


def _reserve_exa_slot(
    root: Path,
    endpoint: str,
    *,
    now_func: Callable[[], float] = time.time,
    sleep_func: Callable[[float], None] = time.sleep,
) -> float:
    qps = _qps_for_endpoint(endpoint)
    interval = 1.0 / max(1, qps)
    paths = library_paths(root)
    paths["rate_db"].parent.mkdir(parents=True, exist_ok=True)
    paths["rate_lock"].parent.mkdir(parents=True, exist_ok=True)
    now = now_func()
    with paths["rate_lock"].open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            conn = sqlite3.connect(paths["rate_db"])
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rate_slots(
                      scope TEXT PRIMARY KEY,
                      next_allowed REAL NOT NULL,
                      updated_at REAL NOT NULL
                    )
                    """
                )
                row = conn.execute("SELECT next_allowed FROM rate_slots WHERE scope = ?", (endpoint,)).fetchone()
                next_allowed = float(row[0]) if row else now
                wait_seconds = max(0.0, next_allowed - now)
                reserved_next = max(now, next_allowed) + interval
                conn.execute(
                    "INSERT OR REPLACE INTO rate_slots(scope, next_allowed, updated_at) VALUES (?, ?, ?)",
                    (endpoint, reserved_next, now),
                )
                conn.commit()
            finally:
                conn.close()
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    if wait_seconds > 0:
        sleep_func(wait_seconds)
    return wait_seconds


def _status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None) if response is not None else None
    return value if isinstance(value, int) else None


def _retry_after_seconds(exc: BaseException, *, now_func: Callable[[], float] = time.time) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    value = headers.get("Retry-After") if headers is not None and hasattr(headers, "get") else None
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        target = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max(0.0, target.timestamp() - now_func())


def _is_timeout(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "timeout" in text or "timed out" in text


def _should_retry(exc: BaseException) -> bool:
    status = _status_code(exc)
    if status == 429 or (status is not None and 500 <= status < 600):
        return True
    text = str(exc).lower()
    return "rate limit" in text or "temporar" in text or _is_timeout(exc)


def _retry_delay_seconds(
    exc: BaseException,
    *,
    attempt_index: int,
    jitter_func: Callable[[], float] = random.random,
    now_func: Callable[[], float] = time.time,
) -> float:
    retry_after = _retry_after_seconds(exc, now_func=now_func)
    if retry_after is not None:
        return retry_after
    if _is_timeout(exc):
        return _float_env("EXA_TIMEOUT_RETRY_SECONDS", TIMEOUT_RETRY_SECONDS, minimum=0.0)
    base = _float_env("EXA_RETRY_BASE_SECONDS", RETRY_BASE_SECONDS, minimum=0.0)
    maximum = _float_env("EXA_RETRY_MAX_SECONDS", RETRY_MAX_SECONDS, minimum=0.0)
    delay = min(maximum, base * (2 ** max(0, attempt_index)))
    return delay + min(0.25, max(0.0, jitter_func()) * 0.25)


def _call_exa_with_retries(
    root: Path,
    endpoint: str,
    call: Callable[[], Any],
    heartbeats: list[dict[str, Any]],
) -> Any:
    attempts = _int_env("EXA_RETRIES", RETRY_MAX_ATTEMPTS)
    last_exc: BaseException | None = None
    for attempt_index in range(attempts):
        queued_seconds = _reserve_exa_slot(root, endpoint)
        if queued_seconds > 0:
            heartbeats.append(
                {
                    "phase": "rate_limit_wait",
                    "endpoint": endpoint,
                    "wait_seconds": round(queued_seconds, 3),
                }
            )
        try:
            heartbeats.append({"phase": "provider_call", "endpoint": endpoint, "attempt": attempt_index + 1})
            return call()
        except Exception as exc:
            last_exc = exc
            if attempt_index >= attempts - 1 or not _should_retry(exc):
                raise
            delay = _retry_delay_seconds(exc, attempt_index=attempt_index)
            heartbeats.append(
                {
                    "phase": "retry_wait",
                    "endpoint": endpoint,
                    "attempt": attempt_index + 1,
                    "status_code": _status_code(exc),
                    "wait_seconds": round(delay, 3),
                }
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _parse_list_args(args: list[str]) -> dict[str, Any]:
    values: dict[str, Any] = {"limit": LIST_DEFAULT_LIMIT, "cursor": 0}
    query_parts: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in {"--limit", "--cursor", "--operation", "--status", "--query"}:
            if index + 1 >= len(args):
                raise ValueError(f"{token} requires a value")
            raw_value = args[index + 1]
            if token == "--limit":
                values["limit"] = _parse_int(raw_value, default=LIST_DEFAULT_LIMIT, minimum=1, maximum=LIST_MAX_LIMIT, flag=token)
            elif token == "--cursor":
                values["cursor"] = _parse_int(raw_value, default=0, minimum=0, maximum=1_000_000_000, flag=token)
            elif token == "--operation":
                if raw_value not in {"search_fast", "search_deep", "fetch_page"}:
                    raise ValueError("--operation must be search_fast, search_deep, or fetch_page")
                values["operation"] = raw_value
            elif token == "--status":
                if raw_value not in {"ok", "failed"}:
                    raise ValueError("--status must be ok or failed")
                values["status"] = raw_value
            else:
                values["query"] = raw_value
            index += 2
            continue
        if token.startswith("--"):
            raise ValueError(f"unsupported list option: {token}")
        query_parts.append(token)
        index += 1
    if query_parts and not values.get("query"):
        values["query"] = " ".join(query_parts)
    return values


def list_search_runs(root: Path, args: list[str]) -> dict[str, Any]:
    filters = _parse_list_args(args)
    conn = _connect_existing(root)
    if conn is None:
        return _empty_run_list(root, filters)
    clauses: list[str] = []
    params: list[Any] = []
    if filters.get("operation"):
        clauses.append("operation = ?")
        params.append(filters["operation"])
    if filters.get("status"):
        clauses.append("status = ?")
        params.append(filters["status"])
    if filters.get("query"):
        clauses.append("(query LIKE ? OR url LIKE ?)")
        like = f"%{filters['query']}%"
        params.extend([like, like])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    limit = int(filters["limit"])
    cursor = int(filters["cursor"])
    with conn:
        rows = conn.execute(
            f"""
            SELECT run_id, operation, source, query, url, status, result_count, created_at, manifest_path
            FROM runs
            {where}
            ORDER BY created_at DESC, run_id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, cursor),
        ).fetchall()
    runs = [
        {
            "id": f"search_run:{row['run_id']}",
            "run_id": row["run_id"],
            "operation": row["operation"],
            "source": row["source"],
            "query": row["query"],
            "url": row["url"],
            "status": row["status"],
            "result_count": row["result_count"],
            "created_at": row["created_at"],
            "observe_cmd": f"./xctx observe {WEB_SEARCH_REF} search_run:{row['run_id']}",
        }
        for row in rows
    ]
    return {
        "object_type": "web_search_exa_run_list",
        "filters": filters,
        "runs": runs,
        "count": len(runs),
        "next_cursor": str(cursor + limit) if len(runs) == limit else None,
        "next_moves": _list_empty_next_moves(filters.get("query")) if not runs else [{"run_cmd": _list_results_cmd()}],
    }


def _empty_run_list(root: Path, filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_type": "web_search_exa_run_list",
        "filters": filters,
        "runs": [],
        "count": 0,
        "next_cursor": None,
        "registry": registry_stats(root),
        "next_moves": _list_empty_next_moves(filters.get("query")),
    }


def list_results(root: Path, args: list[str]) -> dict[str, Any]:
    filters = _parse_list_args(args)
    conn = _connect_existing(root)
    if conn is None:
        return _empty_result_list(root, filters)
    clauses: list[str] = []
    params: list[Any] = []
    if filters.get("operation"):
        clauses.append("results.operation = ?")
        params.append(filters["operation"])
    if filters.get("query"):
        clauses.append("(results.title LIKE ? OR results.url LIKE ? OR results.text_preview LIKE ?)")
        like = f"%{filters['query']}%"
        params.extend([like, like, like])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    limit = int(filters["limit"])
    cursor = int(filters["cursor"])
    with conn:
        rows = conn.execute(
            f"""
            SELECT results.result_id, results.run_id, results.ordinal, results.operation,
                   results.title, results.url, results.published_date, results.text_preview,
                   runs.created_at
            FROM results
            JOIN runs ON runs.run_id = results.run_id
            {where}
            ORDER BY runs.created_at DESC, results.ordinal ASC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, cursor),
        ).fetchall()
    results = [
        {
            "id": row["result_id"],
            "run": f"search_run:{row['run_id']}",
            "ordinal": row["ordinal"],
            "operation": row["operation"],
            "title": row["title"] or row["url"] or row["result_id"],
            "url": row["url"],
            "published_date": row["published_date"],
            "preview": row["text_preview"][:300] if row["text_preview"] else "",
            "observe_cmd": f"./xctx observe {WEB_SEARCH_REF} {row['result_id']}",
        }
        for row in rows
    ]
    return {
        "object_type": "web_search_exa_result_list",
        "filters": filters,
        "results": results,
        "count": len(results),
        "next_cursor": str(cursor + limit) if len(results) == limit else None,
        "next_moves": _list_empty_next_moves(filters.get("query")) if not results else [{"run_cmd": _search_plan_cmd(filters.get("query"))}],
    }


def _empty_result_list(root: Path, filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_type": "web_search_exa_result_list",
        "filters": filters,
        "results": [],
        "count": 0,
        "next_cursor": None,
        "registry": registry_stats(root),
        "next_moves": _list_empty_next_moves(filters.get("query")),
    }


def _list_empty_next_moves(query: Any = None) -> list[dict[str, str]]:
    return [
        {"run_cmd": _search_plan_cmd(str(query)) if query else _search_plan_cmd()},
        {"run_cmd": _deep_plan_cmd(str(query)) if query else _deep_plan_cmd()},
        {"run_cmd": _page_plan_cmd()},
    ]


def _preview_text(text: str, limit: int) -> dict[str, Any] | None:
    if limit <= 0:
        return None
    bounded = text[:limit]
    return {
        "chars_returned": len(bounded),
        "truncated": len(text) > limit,
        "text": bounded,
    }


def _preview_cmd(target: str, chars: int = OBSERVE_HELPER_PREVIEW_CHARS) -> str:
    return f"./xctx observe {WEB_SEARCH_REF} {target} --web-preview-chars {chars}"


def _content_helper(target: str, text: str, *, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "content_chars": len(text),
        "bounded_preview_flag": "--web-preview-chars N",
        "preview_cmd": _preview_cmd(target),
    }


def _jq_child_path(prefix: str, key: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f".{key}" if prefix == "." else f"{prefix}.{key}"
    return f".[{json.dumps(key)}]" if prefix == "." else f"{prefix}[{json.dumps(key)}]"


def _json_content_paths(value: Any, prefix: str = ".") -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key in ("text", "summary", "content", "markdown", "preview"):
            text = value.get(key)
            if isinstance(text, str) and text:
                paths.append({"path": _jq_child_path(prefix, key), "chars": len(text)})
        results = value.get("results")
        if isinstance(results, list) and results:
            paths.extend(_json_content_paths(results[0], f"{_jq_child_path(prefix, 'results')}[0]"))
    elif isinstance(value, list) and value:
        paths.extend(_json_content_paths(value[0], f"{prefix}[0]"))
    return paths[:8]


def _json_shape_helper(value: Any) -> dict[str, Any]:
    helper: dict[str, Any] = {"safe_jq_examples": ["."]}
    if isinstance(value, list):
        helper.update(
            {
                "root_type": "array",
                "root_length": len(value),
                "root_access_path": ".[0]" if value else ".",
            }
        )
        if value and isinstance(value[0], dict):
            helper["first_item_keys"] = sorted(str(key) for key in value[0].keys())
            helper["safe_jq_examples"].append(".[0]")
        helper["content_paths"] = _json_content_paths(value)
        for item in helper["content_paths"][:3]:
            helper["safe_jq_examples"].append(str(item["path"]))
        return helper
    if isinstance(value, dict):
        helper.update({"root_type": "object", "top_keys": sorted(str(key) for key in value.keys())})
        results = value.get("results")
        if isinstance(results, list):
            helper["results_path"] = ".results"
            helper["result_count"] = len(results)
            helper["safe_jq_examples"].append(".results")
            if results:
                helper["first_result_path"] = ".results[0]"
                helper["safe_jq_examples"].append(".results[0]")
                if isinstance(results[0], dict):
                    helper["first_result_keys"] = sorted(str(key) for key in results[0].keys())
        helper["content_paths"] = _json_content_paths(value)
        for item in helper["content_paths"][:3]:
            helper["safe_jq_examples"].append(str(item["path"]))
        return helper
    helper["root_type"] = type(value).__name__
    return helper


def _artifact_json_helper(path: Path) -> dict[str, Any] | None:
    try:
        value = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return _json_shape_helper(value)


def _parse_preview_chars(args: list[str]) -> int:
    value = _option(args, "--preview-chars", default="0")
    return _parse_int(value, default=0, minimum=0, maximum=4000, flag="--preview-chars")


def observe_exa_search(root: Path, identifier: str, args: list[str]) -> dict[str, Any]:
    target = str(identifier or "status").strip() or "status"
    preview_chars = _parse_preview_chars(args)
    if target == "status":
        payload = {
            "object_type": "web_search_exa_observation",
            "target": "status",
            "stats": registry_stats(root),
            "provider_readiness": _provider_readiness(),
            "next_moves": [{"run_cmd": _search_plan_cmd()}, {"run_cmd": _list_results_cmd()}],
        }
        return payload
    if target.startswith("search_run:"):
        return _observe_run(root, target[len("search_run:") :], preview_chars)
    if target.startswith("web_result:"):
        return _observe_result(root, target, preview_chars)
    if target.startswith("web_artifact:"):
        return _observe_artifact(root, target, preview_chars)
    raise ValueError("observe target must be status, search_run:<id>, web_result:<id>, or web_artifact:<id>")


def _observe_run(root: Path, run_id: str, preview_chars: int) -> dict[str, Any]:
    conn = _connect_existing(root)
    if conn is None:
        raise ValueError(f"unknown search run: {run_id}")
    with conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown search run: {run_id}")
        artifacts = conn.execute(
            "SELECT artifact_id, kind, path, bytes, sha256 FROM artifacts WHERE run_id = ? ORDER BY kind",
            (run_id,),
        ).fetchall()
        results = conn.execute(
            "SELECT result_id, ordinal, title, url, text_preview FROM results WHERE run_id = ? ORDER BY ordinal",
            (run_id,),
        ).fetchall()
    payload: dict[str, Any] = {
        "object_type": "web_search_exa_observation",
        "target": f"search_run:{run_id}",
        "run": {
            "run_id": run_id,
            "operation": row["operation"],
            "source": row["source"],
            "query": row["query"],
            "url": row["url"],
            "status": row["status"],
            "result_count": row["result_count"],
            "created_at": row["created_at"],
        },
        "artifacts": [
            {
                "id": item["artifact_id"],
                "kind": item["kind"],
                "path": _display_path(root, Path(item["path"])),
                "bytes": item["bytes"],
                "sha256": item["sha256"],
                "observe_cmd": f"./xctx observe {WEB_SEARCH_REF} {item['artifact_id']}",
            }
            for item in artifacts
        ],
        "results": [
            {
                "id": item["result_id"],
                "ordinal": item["ordinal"],
                "title": item["title"] or item["url"] or item["result_id"],
                "url": item["url"],
                "preview": item["text_preview"][:300] if item["text_preview"] else "",
                "observe_cmd": f"./xctx observe {WEB_SEARCH_REF} {item['result_id']}",
            }
            for item in results
        ],
        "next_moves": [{"run_cmd": _list_results_cmd()}, {"run_cmd": _search_plan_cmd(row["query"])}],
    }
    markdown_path = Path(row["markdown_path"] or "")
    if preview_chars > 0 and markdown_path.is_file():
        payload["bounded_preview"] = _preview_text(markdown_path.read_text(encoding="utf-8", errors="replace"), preview_chars)
    return payload


def _observe_result(root: Path, result_id: str, preview_chars: int) -> dict[str, Any]:
    conn = _connect_existing(root)
    if conn is None:
        raise ValueError(f"unknown web result: {result_id}")
    with conn:
        row = conn.execute("SELECT * FROM results WHERE result_id = ?", (result_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown web result: {result_id}")
    raw = json.loads(row["raw_json"])
    payload: dict[str, Any] = {
        "object_type": "web_search_exa_observation",
        "target": result_id,
        "result": {
            "id": result_id,
            "run": f"search_run:{row['run_id']}",
            "ordinal": row["ordinal"],
            "operation": row["operation"],
            "title": row["title"] or row["url"] or result_id,
            "url": row["url"],
            "published_date": row["published_date"],
            "author": row["author"],
            "score": row["score"],
            "text_preview": row["text_preview"][:500] if row["text_preview"] else "",
        },
        "raw_keys": sorted(raw.keys()) if isinstance(raw, dict) else [],
        "next_moves": [
            {"run_cmd": f"./xctx observe {WEB_SEARCH_REF} search_run:{row['run_id']}"},
            {"run_cmd": _preview_cmd(result_id), "why": "Return a bounded preview of the stored result content."},
            {"run_cmd": _search_plan_cmd(row["title"] or row["url"])},
        ],
    }
    text = _primary_result_text(raw) or row["text_preview"] or ""
    payload["content_helper"] = _content_helper(result_id, text, source="result_raw_json")
    if preview_chars > 0:
        payload["bounded_preview"] = _preview_text(text, preview_chars)
    return payload


def _observe_artifact(root: Path, artifact_id: str, preview_chars: int) -> dict[str, Any]:
    conn = _connect_existing(root)
    if conn is None:
        raise ValueError(f"unknown web artifact: {artifact_id}")
    with conn:
        row = conn.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown web artifact: {artifact_id}")
    path = Path(row["path"])
    payload: dict[str, Any] = {
        "object_type": "web_search_exa_observation",
        "target": artifact_id,
        "artifact": {
            "id": artifact_id,
            "run": f"search_run:{row['run_id']}",
            "kind": row["kind"],
            "path": _display_path(root, path),
            "bytes": row["bytes"],
            "sha256": row["sha256"],
        },
        "next_moves": [
            {"run_cmd": f"./xctx observe {WEB_SEARCH_REF} search_run:{row['run_id']}"},
            {"run_cmd": _preview_cmd(artifact_id), "why": "Return a bounded preview of the artifact body."},
        ],
    }
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        payload["content_helper"] = _content_helper(artifact_id, text, source="artifact_file")
        if row["kind"] in {"raw_json", "results_json", "manifest"}:
            json_helper = _artifact_json_helper(path)
            if json_helper is not None:
                payload["json_helper"] = json_helper
        if preview_chars > 0:
            payload["bounded_preview"] = _preview_text(text, preview_chars)
    return payload


def exa_search_audit(root: Path) -> dict[str, Any]:
    paths = library_paths(root)
    readiness = _provider_readiness()
    checks = [
        {
            "id": "audit:web_search:exa_search:registry_path_configured",
            "status": "pass",
            "path": _display_path(root, paths["registry"]),
        },
        {
            "id": "audit:web_search:exa_search:artifact_root_configured",
            "status": "pass",
            "path": _display_path(root, paths["artifacts"]),
        },
        {
            "id": "audit:web_search:exa_search:exa_py_import",
            "status": "pass" if readiness["sdk"]["available"] else "warn",
            "package": "exa-py",
        },
        {
            "id": "audit:web_search:exa_search:exa_api_key",
            "status": "pass",
            **readiness["identity"],
        },
        {
            "id": "audit:web_search:exa_search:rate_limit_store",
            "status": "pass",
            "path": _display_path(root, paths["rate_db"]),
        },
    ]
    return {
        "object_type": "web_search_exa_audit",
        "checks": checks,
        "stats": registry_stats(root),
    }
