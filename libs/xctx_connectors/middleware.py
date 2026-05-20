"""Generic middleware for xctx-native pass-through and legacy command adapters."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xctx.config.loader import load_store


CONNECTOR_VERSION = "legacy_connector.v1"
DEFAULT_MAX_CONTENT_BYTES = 65536


def _emit_json(payload: dict[str, Any], *, compact: bool) -> None:
    if compact:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))


def _take_flag(argv: list[str], flag: str) -> tuple[bool, list[str]]:
    present = flag in argv
    return present, [item for item in argv if item != flag]


def _project_root() -> Path:
    path = Path(__file__).resolve()
    for candidate in path.parents:
        if (candidate / "yaml_dynamic_config").exists() and (candidate / "data").exists():
            return candidate
    return path.parents[2]


def _subdomain_from_env(root: Path) -> dict[str, Any]:
    domain_id = os.environ.get("XCTX_AGENT_DOMAIN")
    subdomain_id = os.environ.get("XCTX_AGENT_SUBDOMAIN")
    if not domain_id or not subdomain_id:
        raise ValueError("XCTX_AGENT_DOMAIN and XCTX_AGENT_SUBDOMAIN are required")
    store = load_store(root=root)
    domain = (store.get("agent_domains") or {}).get(domain_id)
    if not domain:
        raise ValueError(f"unknown connector domain: {domain_id}")
    subdomain = (domain.get("_subdomains") or {}).get(subdomain_id)
    if not subdomain:
        raise ValueError(f"unknown connector subdomain: {domain_id}::{subdomain_id}")
    return subdomain


def _connector_meta(subdomain: dict[str, Any], connector: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": CONNECTOR_VERSION,
        "kind": connector.get("kind", "unknown"),
        "profile": connector.get("profile", subdomain.get("id")),
        "agent_domain": subdomain.get("_domain_id"),
        "agent_subdomain": subdomain.get("id"),
    }


def _command_status(
    *,
    ok: bool,
    argv: list[str] | None = None,
    exit_code: int | None = None,
    timed_out: bool = False,
    error: str | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }
    if argv is not None:
        payload["argv"] = argv
    if error:
        payload["error"] = error
    if stdout is not None:
        payload["stdout_preview"] = stdout[:500]
    if stderr is not None:
        payload["stderr_preview"] = stderr[:500]
    return {key: value for key, value in payload.items() if value is not None}


def _audit_failure_check(subdomain: dict[str, Any] | None, message: str) -> dict[str, Any]:
    domain_id = str((subdomain or {}).get("_domain_id") or "unknown_domain")
    subdomain_id = str((subdomain or {}).get("id") or "unknown_subdomain")
    return {
        "id": f"audit:{domain_id}:{subdomain_id}:middleware_connector",
        "status": "fail",
        "message": message,
    }


def _error_payload(
    subdomain: dict[str, Any] | None,
    connector: dict[str, Any] | None,
    message: str,
    *,
    command: str | None = None,
    args: list[str] | None = None,
) -> dict[str, Any]:
    connector = connector or {}
    payload = {
        "object_type": "legacy_connector_error",
        "found": False,
        "connector": _connector_meta(subdomain or {}, connector),
        "requested_command": command,
        "requested_args": args or [],
        "command_status": _command_status(ok=False, error=message),
        "data_boundary": "Middleware error payload. xctx received a structured object instead of raw legacy failure output.",
        "next_moves": ["./xctx audit root"],
    }
    if command == "audit":
        payload["checks"] = [_audit_failure_check(subdomain, message)]
    return payload


def _parse_controls(args: list[str], *, default_limit: int, max_limit: int) -> tuple[list[str], dict[str, Any]]:
    rest: list[str] = []
    controls: dict[str, Any] = {"limit": default_limit, "cursor": 0, "shape": "compact"}
    index = 0
    while index < len(args):
        token = args[index]
        if token in {"--limit", "--cursor", "--shape"}:
            if index + 1 >= len(args):
                raise ValueError(f"{token} requires a value")
            value = args[index + 1]
            if token == "--limit":
                limit = int(value)
                if limit < 1:
                    raise ValueError("--limit must be at least 1")
                controls["limit"] = min(limit, max_limit)
            elif token == "--cursor":
                cursor = int(value)
                if cursor < 0:
                    raise ValueError("--cursor cannot be negative")
                controls["cursor"] = cursor
            elif token == "--shape":
                if value not in {"compact", "full"}:
                    raise ValueError("--shape must be compact or full")
                controls["shape"] = value
            index += 2
            continue
        rest.append(token)
        index += 1
    return rest, controls


def _run_legacy(argv: list[str], *, timeout: float, max_output_bytes: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "argv": argv,
            "exit_code": None,
            "timed_out": True,
            "stdout": (exc.stdout or "")[:max_output_bytes] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[:max_output_bytes] if isinstance(exc.stderr, str) else "",
            "error": f"legacy command timed out after {timeout} seconds",
        }
    return {
        "ok": proc.returncode == 0,
        "argv": argv,
        "exit_code": proc.returncode,
        "timed_out": False,
        "stdout": proc.stdout[:max_output_bytes],
        "stderr": proc.stderr[:max_output_bytes],
        "error": None if proc.returncode == 0 else (proc.stderr.strip() or proc.stdout.strip() or "legacy command failed"),
    }


def _passthrough(root: Path, subdomain: dict[str, Any], connector: dict[str, Any], args: list[str], *, compact: bool) -> dict[str, Any]:
    target = connector.get("target_entrypoint")
    if not target:
        raise ValueError("xctx_native_passthrough connector requires target_entrypoint")
    target_path = root / str(target)
    if not target_path.exists():
        raise ValueError(f"passthrough target does not exist: {target}")
    timeout = float(connector.get("timeout_seconds", 30))
    argv = [sys.executable, str(target_path), *args]
    if compact and "--compact" not in argv:
        argv.append("--compact")
    env = os.environ.copy()
    proc = subprocess.run(
        argv,
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    text = (proc.stdout or "").strip()
    if proc.returncode == 0:
        try:
            payload = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            return _error_payload(subdomain, connector, f"passthrough target returned invalid JSON: {exc}", command=args[0] if args else "discover", args=args)
        return payload if isinstance(payload, dict) else _error_payload(subdomain, connector, "passthrough target returned non-object JSON", command=args[0] if args else "discover", args=args)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {}
    payload = {
        "object_type": "xctx_native_passthrough_error",
        "found": False,
        "connector": _connector_meta(subdomain, connector),
        "requested_args": args,
        "passthrough_target": str(target),
        "target_payload": payload if isinstance(payload, dict) else {},
        "command_status": _command_status(
            ok=False,
            argv=argv,
            exit_code=proc.returncode,
            error=(proc.stderr.strip() or (payload.get("error") if isinstance(payload, dict) else None) or "passthrough target failed"),
            stdout=proc.stdout,
            stderr=proc.stderr,
        ),
        "data_boundary": "Pass-through connector normalized a target adapter failure into JSON.",
    }
    if args and args[0] == "audit":
        payload["checks"] = [_audit_failure_check(subdomain, payload["command_status"]["error"])]
    return payload


@dataclass(frozen=True)
class SafePath:
    root: Path
    path: Path
    relative: str


def _safe_path(root: Path, raw: str | None, *, expected: str | None = None) -> SafePath:
    raw = (raw or ".").strip()
    for prefix in ("file:", "directory:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    raw = raw or "."
    candidate = (root / raw).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("path escapes configured safe root")
    if expected == "file" and candidate.exists() and not candidate.is_file():
        raise ValueError("target is not a file")
    if expected == "directory" and candidate.exists() and not candidate.is_dir():
        raise ValueError("target is not a directory")
    relative = "." if candidate == resolved_root else candidate.relative_to(resolved_root).as_posix()
    return SafePath(root=resolved_root, path=candidate, relative=relative)


def _iso_mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _display_mtime(path: Path) -> str | None:
    try:
        dt = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None
    return f"{dt:%b} {dt.day} {dt:%H:%M}"


def _entry_id(path: SafePath, *, kind: str) -> str:
    return f"{kind}:{path.relative}"


def _entry_projection(path: Path, safe_root: Path, *, kind: str, domain_ref: str, shape: str) -> dict[str, Any]:
    safe = _safe_path(safe_root, path.relative_to(safe_root).as_posix(), expected=kind)
    stat = path.stat()
    payload = {
        "id": _entry_id(safe, kind=kind),
        f"{kind}_id": _entry_id(safe, kind=kind),
        "name": path.name,
        "relative_path": safe.relative,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "observe_cmd": f"./xctx observe {domain_ref} {_entry_id(safe, kind=kind)}",
    }
    if kind == "file":
        payload["size_bytes"] = stat.st_size
    if shape == "full":
        payload.update(
            {
                "mode_octal": oct(stat.st_mode & 0o777),
                "inode": stat.st_ino,
            }
        )
    return payload


def _paginate(items: list[Path], *, limit: int, cursor: int) -> tuple[list[Path], dict[str, Any]]:
    total = len(items)
    page = items[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < total else None
    return page, {
        "total_count": total,
        "returned_count": len(page),
        "limit": limit,
        "cursor": str(cursor) if cursor else None,
        "next_cursor": str(next_cursor) if next_cursor is not None else None,
        "has_more": next_cursor is not None,
    }


def _filesystem_config(root: Path, connector: dict[str, Any]) -> tuple[Path, int, int, float, int]:
    safe_root = (root / str(connector.get("safe_root", "data/file_manager_home"))).resolve()
    default_limit = int(connector.get("default_limit", 25))
    max_limit = int(connector.get("max_limit", 100))
    timeout = float(connector.get("timeout_seconds", 5))
    max_output_bytes = int(connector.get("max_output_bytes", 20000))
    return safe_root, default_limit, max_limit, timeout, max_output_bytes


def _file_type_payload(path: Path, *, timeout: float, max_output_bytes: int) -> tuple[str, dict[str, Any]]:
    legacy = _run_legacy(["file", "--brief", str(path)], timeout=timeout, max_output_bytes=max_output_bytes)
    return (legacy.get("stdout") or "").strip(), legacy


def _ls_payload(path: Path, *, timeout: float, max_output_bytes: int) -> dict[str, Any]:
    return _run_legacy(["ls", "-lt", str(path)], timeout=timeout, max_output_bytes=max_output_bytes)


def _command_status_from_legacy(legacy: dict[str, Any], *, include_argv: bool = True) -> dict[str, Any]:
    return _command_status(
        ok=bool(legacy["ok"]),
        argv=legacy["argv"] if include_argv else None,
        exit_code=legacy["exit_code"],
        timed_out=bool(legacy["timed_out"]),
        error=legacy.get("error"),
        stderr=legacy.get("stderr"),
    )


def _discover_filesystem_object(
    root: Path,
    subdomain: dict[str, Any],
    connector: dict[str, Any],
    target_text: str,
    *,
    shape: str,
) -> dict[str, Any]:
    safe_root, _default_limit, _max_limit, timeout, max_output_bytes = _filesystem_config(root, connector)
    expected = "directory" if target_text.startswith("directory:") else "file" if target_text.startswith("file:") else None
    target = _safe_path(safe_root, target_text, expected=expected)
    if not target.path.exists():
        return _filesystem_not_found(subdomain, connector, target.relative, expected=expected or "file_or_directory")

    kind = "directory" if target.path.is_dir() else "file"
    domain_ref = f"{subdomain['_domain_id']}::{subdomain['id']}"
    stat = target.path.stat()
    ls_legacy = _ls_payload(target.path, timeout=timeout, max_output_bytes=max_output_bytes)
    payload: dict[str, Any] = {
        "object_type": f"legacy_connector_filesystem_{kind}_discovery",
        "shape": shape,
        "connector": _connector_meta(subdomain, connector),
        "found": True,
        "id": _entry_id(target, kind=kind),
        f"{kind}_id": _entry_id(target, kind=kind),
        "name": target.path.name,
        "relative_path": target.relative,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "modified_display": _display_mtime(target.path),
        "observe_cmd": f"./xctx observe {domain_ref} {_entry_id(target, kind=kind)}",
        "legacy_commands": {
            "stat_line": " ".join(shlex.quote(item) for item in ls_legacy["argv"]),
        },
        "command_status": {
            "stat_line": _command_status_from_legacy(ls_legacy, include_argv=shape == "full"),
        },
        "data_boundary": f"Discovery returns {kind} identity and metadata. Use observe for materialized {kind} data.",
    }
    if kind == "file":
        file_type, file_legacy = _file_type_payload(target.path, timeout=timeout, max_output_bytes=max_output_bytes)
        payload.update(
            {
                "type": file_type,
                "file_type": file_type,
                "size_bytes": stat.st_size,
            }
        )
        payload["legacy_commands"]["type"] = " ".join(shlex.quote(item) for item in file_legacy["argv"])
        payload["command_status"]["type"] = _command_status_from_legacy(file_legacy, include_argv=shape == "full")
    else:
        children = list(target.path.iterdir())
        payload.update(
            {
                "child_count": len(children),
                "file_count": sum(1 for item in children if item.is_file()),
                "directory_count": sum(1 for item in children if item.is_dir()),
            }
        )
    if shape == "full":
        payload.update(
            {
                "mode_octal": oct(stat.st_mode & 0o777),
                "inode": stat.st_ino,
            }
        )
    return payload


def _filesystem_discovery(root: Path, subdomain: dict[str, Any], connector: dict[str, Any], args: list[str]) -> dict[str, Any]:
    rest, controls = _parse_controls(args, default_limit=int(connector.get("default_limit", 25)), max_limit=int(connector.get("max_limit", 100)))
    shape = controls["shape"]
    if rest:
        return _discover_filesystem_object(root, subdomain, connector, " ".join(rest), shape=shape)
    domain_ref = f"{subdomain['_domain_id']}::{subdomain['id']}"
    payload: dict[str, Any] = {
        "object_type": "legacy_connector_filesystem_discovery",
        "shape": shape,
        "connector": _connector_meta(subdomain, connector),
        "description": "Discover filesystem objects exposed through a safe legacy-command connector.",
        "observable_objects": {
            "file": {"id_shape": "file:<relative_path>", "observe_shape": f"./xctx observe {domain_ref} file:<relative_path>"},
            "directory": {"id_shape": "directory:<relative_path>", "observe_shape": f"./xctx observe {domain_ref} directory:<relative_path>"},
        },
        "discoverable_modes": [
            {
                "id": "list_files",
                "mode_kind": "list",
                "run_cmd": f"./xctx discover {domain_ref} list_files [--limit N] [--cursor CURSOR] [--shape compact|full]",
            },
            {
                "id": "list_directories",
                "mode_kind": "list",
                "run_cmd": f"./xctx discover {domain_ref} list_directories [--limit N] [--cursor CURSOR] [--shape compact|full]",
            },
        ],
        "data_boundary": "Discovery returns file and directory identities. Use observe to inspect a selected object.",
        "next_moves": [
            f"./xctx discover {domain_ref} list_files",
            f"./xctx discover {domain_ref} list_directories",
            f"./xctx observe {domain_ref} file:<relative_path>",
            f"./xctx observe {domain_ref} directory:<relative_path>",
        ],
    }
    if not safe_root_exists(root, connector):
        payload["connector_status"] = "safe_root_missing"
        payload["warning"] = "Configured safe root is not available; audit this subdomain before observing filesystem objects."
    if shape == "full":
        safe_root, *_ = _filesystem_config(root, connector)
        payload["safe_root"] = str(safe_root.relative_to(root))
        payload["legacy_commands"] = {
            "list": "ls -lt",
            "observe_file": "file --brief",
        }
    else:
        payload["full_shape_cmd"] = f"./xctx discover {domain_ref} --shape full"
    return payload


def _list_filesystem(
    root: Path,
    subdomain: dict[str, Any],
    connector: dict[str, Any],
    args: list[str],
    *,
    kind: str,
) -> dict[str, Any]:
    safe_root, default_limit, max_limit, timeout, max_output_bytes = _filesystem_config(root, connector)
    rest, controls = _parse_controls(args, default_limit=default_limit, max_limit=max_limit)
    target = _safe_path(safe_root, " ".join(rest) if rest else ".", expected="directory")
    if not target.path.exists():
        return _filesystem_not_found(subdomain, connector, target.relative, expected="directory")
    legacy = _ls_payload(target.path, timeout=timeout, max_output_bytes=max_output_bytes)
    entries = [item for item in target.path.iterdir() if (item.is_file() if kind == "file" else item.is_dir())]
    entries.sort(key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    page, pagination = _paginate(entries, limit=int(controls["limit"]), cursor=int(controls["cursor"]))
    domain_ref = f"{subdomain['_domain_id']}::{subdomain['id']}"
    result_key = "files" if kind == "file" else "directories"
    shape = str(controls["shape"])
    payload = {
        "object_type": f"legacy_connector_filesystem_{'file' if kind == 'file' else 'directory'}_list",
        "shape": shape,
        "connector": _connector_meta(subdomain, connector),
        "found": True,
        "directory_id": _entry_id(target, kind="directory"),
        "directory_relative_path": target.relative,
        "legacy_command": " ".join(shlex.quote(item) for item in legacy["argv"]),
        "command_status": _command_status_from_legacy(legacy, include_argv=shape == "full"),
        result_key: [_entry_projection(item, safe_root, kind=kind, domain_ref=domain_ref, shape=shape) for item in page],
        "data_boundary": f"Discovery index of {result_key}. Use observe on an emitted id for materialized object details.",
    }
    if shape == "full" or not (
        pagination["total_count"] == 1
        and pagination["returned_count"] == 1
        and pagination["cursor"] is None
        and pagination["next_cursor"] is None
    ):
        payload["pagination"] = pagination
    return payload


def _read_text_content(path: Path, *, max_content_bytes: int) -> dict[str, Any]:
    stat = path.stat()
    with path.open("rb") as handle:
        raw = handle.read(max_content_bytes + 1)
    truncated = len(raw) > max_content_bytes
    if truncated:
        raw = raw[:max_content_bytes]
    if b"\x00" in raw:
        return {
            "available": False,
            "reason": "binary_content",
            "bytes_total": stat.st_size,
            "bytes_returned": 0,
            "truncated": truncated,
        }
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "available": False,
            "reason": "not_utf8_text",
            "bytes_total": stat.st_size,
            "bytes_returned": 0,
            "truncated": truncated,
        }
    return {
        "available": True,
        "encoding": "utf-8",
        "bytes_total": stat.st_size,
        "bytes_returned": len(raw),
        "truncated": truncated,
        "text": text,
    }


def _filesystem_not_found(subdomain: dict[str, Any], connector: dict[str, Any], relative: str, *, expected: str) -> dict[str, Any]:
    return {
        "object_type": "legacy_connector_filesystem_observation",
        "connector": _connector_meta(subdomain, connector),
        "found": False,
        "expected_type": expected,
        "relative_path": relative,
        "command_status": _command_status(ok=False, error="target does not exist"),
        "next_moves": [f"./xctx discover {subdomain['_domain_id']}::{subdomain['id']} list_files"],
    }


def _observe_filesystem(root: Path, subdomain: dict[str, Any], connector: dict[str, Any], args: list[str]) -> dict[str, Any]:
    safe_root, _default_limit, _max_limit, timeout, max_output_bytes = _filesystem_config(root, connector)
    max_content_bytes = int(connector.get("max_content_bytes", DEFAULT_MAX_CONTENT_BYTES))
    identifier = " ".join(args).strip()
    expected = "directory" if identifier.startswith("directory:") else "file" if identifier.startswith("file:") else None
    target = _safe_path(safe_root, identifier, expected=expected)
    if not target.path.exists():
        return _filesystem_not_found(subdomain, connector, target.relative, expected=expected or "file_or_directory")
    if target.path.is_dir():
        legacy = _ls_payload(target.path, timeout=timeout, max_output_bytes=max_output_bytes)
        children = sorted(target.path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        return {
            "object_type": "legacy_connector_filesystem_directory_observation",
            "connector": _connector_meta(subdomain, connector),
            "found": True,
            "directory_id": _entry_id(target, kind="directory"),
            "relative_path": target.relative,
            "modified_at": _iso_mtime(target.path),
            "child_count": len(children),
            "sample_children": [
                {
                    "id": _entry_id(_safe_path(safe_root, child.relative_to(safe_root).as_posix()), kind="directory" if child.is_dir() else "file"),
                    "name": child.name,
                    "kind": "directory" if child.is_dir() else "file",
                }
                for child in children[:10]
            ],
            "legacy_command": " ".join(shlex.quote(item) for item in legacy["argv"]),
            "command_status": _command_status_from_legacy(legacy),
            "data_boundary": "Directory observation returns materialized directory metadata and a bounded child summary.",
        }
    file_type, legacy = _file_type_payload(target.path, timeout=timeout, max_output_bytes=max_output_bytes)
    stat = target.path.stat()
    return {
        "object_type": "legacy_connector_filesystem_file_observation",
        "connector": _connector_meta(subdomain, connector),
        "found": True,
        "file_id": _entry_id(target, kind="file"),
        "relative_path": target.relative,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "modified_display": _display_mtime(target.path),
        "file_type": file_type,
        "content": _read_text_content(target.path, max_content_bytes=max_content_bytes),
        "legacy_command": " ".join(shlex.quote(item) for item in legacy["argv"]),
        "command_status": _command_status_from_legacy(legacy),
        "data_boundary": "File observation returns materialized filesystem metadata and bounded text content when safely readable.",
    }


def _filesystem_audit(root: Path, subdomain: dict[str, Any], connector: dict[str, Any]) -> dict[str, Any]:
    safe_root, _default_limit, _max_limit, timeout, max_output_bytes = _filesystem_config(root, connector)
    checks = [
        {
            "id": f"audit:{subdomain['_domain_id']}:{subdomain['id']}:safe_root_exists",
            "status": "pass" if safe_root.exists() and safe_root.is_dir() else "fail",
            "path": str(safe_root.relative_to(root)),
        }
    ]
    for binary in ("ls", "file"):
        proc = _run_legacy([binary, "--version"], timeout=timeout, max_output_bytes=max_output_bytes)
        if binary == "file" and not proc["ok"]:
            proc = _run_legacy([binary, "-v"], timeout=timeout, max_output_bytes=max_output_bytes)
        checks.append(
            {
                "id": f"audit:{subdomain['_domain_id']}:{subdomain['id']}:legacy_command:{binary}",
                "status": "pass" if proc["ok"] else "fail",
                "command": binary,
            }
        )
    return {"object_type": "legacy_connector_filesystem_audit", "checks": checks}


def safe_root_exists(root: Path, connector: dict[str, Any]) -> bool:
    safe_root = (root / str(connector.get("safe_root", "data/file_manager_home"))).resolve()
    return safe_root.exists() and safe_root.is_dir()


def _filesystem(root: Path, subdomain: dict[str, Any], connector: dict[str, Any], command: str, rest: list[str]) -> dict[str, Any]:
    aliases = {
        "discover": "discover",
        "list-files": "list_files",
        "list_files": "list_files",
        "files": "list_files",
        "list-directories": "list_directories",
        "list_directories": "list_directories",
        "directories": "list_directories",
        "observe": "observe",
        "audit": "audit",
    }
    resolved = aliases.get(command)
    if resolved == "discover":
        return _filesystem_discovery(root, subdomain, connector, rest)
    if resolved == "list_files":
        return _list_filesystem(root, subdomain, connector, rest, kind="file")
    if resolved == "list_directories":
        return _list_filesystem(root, subdomain, connector, rest, kind="directory")
    if resolved == "observe":
        return _observe_filesystem(root, subdomain, connector, rest)
    if resolved == "audit":
        return _filesystem_audit(root, subdomain, connector)
    raise ValueError(f"unknown filesystem connector command: {command}")


def run(argv: list[str], *, root: Path | None = None) -> dict[str, Any]:
    root = root or _project_root()
    subdomain = _subdomain_from_env(root)
    connector = subdomain.get("connector") or {}
    kind = str(connector.get("kind", "xctx_native_passthrough"))
    command = argv[0] if argv else "discover"
    rest = argv[1:]
    if kind == "xctx_native_passthrough":
        return _passthrough(root, subdomain, connector, argv, compact=True)
    if kind == "legacy_command" and connector.get("profile") == "filesystem_home":
        return _filesystem(root, subdomain, connector, command, rest)
    raise ValueError(f"unsupported connector kind/profile: {kind}/{connector.get('profile')}")


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    compact, args = _take_flag(raw, "--compact")
    root = _project_root()
    subdomain: dict[str, Any] | None = None
    connector: dict[str, Any] | None = None
    try:
        subdomain = _subdomain_from_env(root)
        connector = subdomain.get("connector") or {}
        payload = run(args, root=root)
    except Exception as exc:  # always return a structured object to xctx
        payload = _error_payload(subdomain, connector, str(exc), command=args[0] if args else "discover", args=args)
    _emit_json(payload, compact=compact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
