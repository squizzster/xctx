"""Domain-owned external-command filesystem adapter for file_manager scopes."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MAX_CONTENT_BYTES = 65536


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


def _entry_projection(path: Path, safe_root: Path, *, kind: str, domain_ref: str, projection: str) -> dict[str, Any]:
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
    if projection == "full":
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


def _filesystem_config(context: Any) -> tuple[Path, int, int, float, int]:
    connector = context.connector_config
    raw_safe_root = Path(str(connector.get("safe_root", "data/file_manager_home")))
    if raw_safe_root.is_absolute():
        raise ValueError("safe_root must be relative to the workspace root")
    workspace_root = context.workspace_root.resolve()
    safe_root = (workspace_root / raw_safe_root).resolve()
    if safe_root != workspace_root and workspace_root not in safe_root.parents:
        raise ValueError("safe_root escapes workspace root")
    default_limit = int(connector.get("default_limit", 25))
    max_limit = int(connector.get("max_limit", 100))
    timeout = float(connector.get("timeout_seconds", 5))
    max_output_bytes = int(connector.get("max_output_bytes", 20000))
    return safe_root, default_limit, max_limit, timeout, max_output_bytes


def _file_type_payload(path: Path, *, timeout: float, max_output_bytes: int, runtime: Any) -> tuple[str, dict[str, Any]]:
    result = runtime.run_command(["file", "--brief", str(path)], timeout=timeout, max_output_bytes=max_output_bytes)
    return (result.get("stdout") or "").strip(), result


def _ls_payload(path: Path, *, timeout: float, max_output_bytes: int, runtime: Any) -> dict[str, Any]:
    return runtime.run_command(["ls", "-lt", str(path)], timeout=timeout, max_output_bytes=max_output_bytes)


def _discover_filesystem_object(
    context: Any,
    target_text: str,
    *,
    projection: str,
    runtime: Any,
) -> dict[str, Any]:
    safe_root, _default_limit, _max_limit, timeout, max_output_bytes = _filesystem_config(context)
    expected = "directory" if target_text.startswith("directory:") else "file" if target_text.startswith("file:") else None
    target = _safe_path(safe_root, target_text, expected=expected)
    if not target.path.exists():
        return _filesystem_not_found(context, target.relative, expected=expected or "file_or_directory", runtime=runtime)

    kind = "directory" if target.path.is_dir() else "file"
    domain_ref = context.adapter_ref
    stat = target.path.stat()
    ls_result = _ls_payload(target.path, timeout=timeout, max_output_bytes=max_output_bytes, runtime=runtime)
    include_diagnostics = runtime.detail_is_max(context)
    payload: dict[str, Any] = {
        "object_type": f"external_command_filesystem_{kind}_discovery",
        "projection": projection,
        "found": True,
        "id": _entry_id(target, kind=kind),
        "name": target.path.name,
        "relative_path": target.relative,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "observe_cmd": f"./xctx observe {domain_ref} {_entry_id(target, kind=kind)}",
        "data_boundary": f"Discovery returns {kind} identity and metadata. Use observe for materialized {kind} data.",
    }
    if projection == "full":
        payload.update(
            {
                f"{kind}_id": _entry_id(target, kind=kind),
                "modified_display": _display_mtime(target.path),
            }
        )
    if include_diagnostics:
        payload["external_commands"] = {
            "stat_line": " ".join(shlex.quote(item) for item in ls_result["argv"]),
        }
        payload["command_status"] = {
            "stat_line": runtime.command_status_from_external_result(ls_result, include_argv=True),
        }
    if kind == "file":
        file_type, file_result = _file_type_payload(target.path, timeout=timeout, max_output_bytes=max_output_bytes, runtime=runtime)
        payload.update(
            {
                "type": file_type,
                "size_bytes": stat.st_size,
            }
        )
        if projection == "full":
            payload["file_type"] = file_type
        if include_diagnostics:
            payload.setdefault("external_commands", {})["type"] = " ".join(shlex.quote(item) for item in file_result["argv"])
            payload.setdefault("command_status", {})["type"] = runtime.command_status_from_external_result(file_result, include_argv=True)
    else:
        children = list(target.path.iterdir())
        payload.update(
            {
                "child_count": len(children),
                "file_count": sum(1 for item in children if item.is_file()),
                "directory_count": sum(1 for item in children if item.is_dir()),
            }
        )
    if projection == "full":
        payload.update(
            {
                "mode_octal": oct(stat.st_mode & 0o777),
                "inode": stat.st_ino,
            }
        )
    return payload


def _filesystem_discovery(context: Any, args: list[str], *, runtime: Any) -> dict[str, Any]:
    connector = context.connector_config
    rest, controls = runtime.parse_controls(
        args,
        default_limit=int(connector.get("default_limit", 25)),
        max_limit=int(connector.get("max_limit", 100)),
    )
    projection = str(controls["projection"])
    if rest:
        return _discover_filesystem_object(context, " ".join(rest), projection=projection, runtime=runtime)
    domain_ref = context.adapter_ref
    payload: dict[str, Any] = {
        "object_type": "external_command_filesystem_discovery",
        "projection": projection,
        "description": "Discover filesystem objects exposed through a safe external-command connector.",
        "observable_objects": {
            "file": {"id_pattern": "file:<relative_path>", "observe_cmd_pattern": f"./xctx observe {domain_ref} file:<relative_path>"},
            "directory": {"id_pattern": "directory:<relative_path>", "observe_cmd_pattern": f"./xctx observe {domain_ref} directory:<relative_path>"},
        },
        "discoverable_modes": [
            {
                "id": "list_files",
                "mode_kind": "list",
                "run_cmd": f"./xctx discover {domain_ref}::list_files [--limit N] [--cursor CURSOR] [--projection compact|full]",
            },
            {
                "id": "list_directories",
                "mode_kind": "list",
                "run_cmd": f"./xctx discover {domain_ref}::list_directories [--limit N] [--cursor CURSOR] [--projection compact|full]",
            },
        ],
        "data_boundary": "Discovery returns file and directory identities. Use observe to inspect a selected object.",
        "next_moves": [
            f"./xctx discover {domain_ref}::list_files",
            f"./xctx discover {domain_ref}::list_directories",
            f"./xctx observe {domain_ref} file:<relative_path>",
            f"./xctx observe {domain_ref} directory:<relative_path>",
        ],
    }
    if not safe_root_exists(context):
        payload["connector_status"] = "safe_root_missing"
        payload["warning"] = "Configured safe root is not available; audit this subdomain before observing filesystem objects."
    if projection != "full":
        payload["projection_controls"] = {
            "current": "compact",
            "available": [{"projection": "full", "run_cmd": f"./xctx discover {domain_ref} --projection full"}],
        }
    if runtime.detail_is_max(context):
        safe_root, *_ = _filesystem_config(context)
        payload["safe_root"] = str(safe_root.relative_to(context.workspace_root))
        payload["external_commands"] = {
            "list": "ls -lt",
            "observe_file": "file --brief",
        }
    return payload


def _list_filesystem(
    context: Any,
    args: list[str],
    *,
    kind: str,
    runtime: Any,
) -> dict[str, Any]:
    safe_root, default_limit, max_limit, timeout, max_output_bytes = _filesystem_config(context)
    rest, controls = runtime.parse_controls(args, default_limit=default_limit, max_limit=max_limit)
    target = _safe_path(safe_root, " ".join(rest) if rest else ".", expected="directory")
    if not target.path.exists():
        return _filesystem_not_found(context, target.relative, expected="directory", runtime=runtime)
    result = _ls_payload(target.path, timeout=timeout, max_output_bytes=max_output_bytes, runtime=runtime)
    entries = [item for item in target.path.iterdir() if (item.is_file() if kind == "file" else item.is_dir())]
    entries.sort(key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    page, pagination = _paginate(entries, limit=int(controls["limit"]), cursor=int(controls["cursor"]))
    domain_ref = context.adapter_ref
    result_key = "files" if kind == "file" else "directories"
    projection = str(controls["projection"])
    payload = {
        "object_type": f"external_command_filesystem_{'file' if kind == 'file' else 'directory'}_list",
        "projection": projection,
        "found": True,
        "directory_id": _entry_id(target, kind="directory"),
        "directory_relative_path": target.relative,
        result_key: [_entry_projection(item, safe_root, kind=kind, domain_ref=domain_ref, projection=projection) for item in page],
        "data_boundary": f"Discovery index of {result_key}. Use observe on an emitted id for materialized object details.",
    }
    if runtime.detail_is_max(context):
        payload["external_command"] = " ".join(shlex.quote(item) for item in result["argv"])
        payload["command_status"] = runtime.command_status_from_external_result(result, include_argv=True)
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


def _filesystem_not_found(context: Any, relative: str, *, expected: str, runtime: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "object_type": "external_command_filesystem_observation",
        "found": False,
        "expected_type": expected,
        "relative_path": relative,
        "status": "not_found",
        "next_moves": [
            f"./xctx discover {context.adapter_ref}::list_files",
            f"./xctx discover {context.adapter_ref}::list_directories",
        ],
    }
    if runtime.detail_is_max(context):
        payload["command_status"] = runtime.command_status(ok=True)
    return payload


def _observe_filesystem(context: Any, args: list[str], *, runtime: Any) -> dict[str, Any]:
    safe_root, _default_limit, _max_limit, timeout, max_output_bytes = _filesystem_config(context)
    max_content_bytes = int(context.connector_config.get("max_content_bytes", DEFAULT_MAX_CONTENT_BYTES))
    identifier = " ".join(args).strip()
    expected = "directory" if identifier.startswith("directory:") else "file" if identifier.startswith("file:") else None
    target = _safe_path(safe_root, identifier, expected=expected)
    if not target.path.exists():
        return _filesystem_not_found(context, target.relative, expected=expected or "file_or_directory", runtime=runtime)
    if target.path.is_dir():
        result = _ls_payload(target.path, timeout=timeout, max_output_bytes=max_output_bytes, runtime=runtime)
        children = sorted(target.path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        payload = {
            "object_type": "external_command_filesystem_directory_observation",
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
            "data_boundary": "Directory observation returns materialized directory metadata and a bounded child summary.",
        }
        if runtime.detail_is_max(context):
            payload["external_command"] = " ".join(shlex.quote(item) for item in result["argv"])
            payload["command_status"] = runtime.command_status_from_external_result(result)
        return payload
    file_type, result = _file_type_payload(target.path, timeout=timeout, max_output_bytes=max_output_bytes, runtime=runtime)
    stat = target.path.stat()
    payload = {
        "object_type": "external_command_filesystem_file_observation",
        "found": True,
        "file_id": _entry_id(target, kind="file"),
        "relative_path": target.relative,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "modified_display": _display_mtime(target.path),
        "file_type": file_type,
        "content": _read_text_content(target.path, max_content_bytes=max_content_bytes),
        "data_boundary": "File observation returns materialized filesystem metadata and bounded text content when safely readable.",
    }
    if runtime.detail_is_max(context):
        payload["external_command"] = " ".join(shlex.quote(item) for item in result["argv"])
        payload["command_status"] = runtime.command_status_from_external_result(result)
    return payload


def _filesystem_audit(context: Any, *, runtime: Any) -> dict[str, Any]:
    safe_root, _default_limit, _max_limit, timeout, max_output_bytes = _filesystem_config(context)
    checks = [
        {
            "id": f"audit:{context.domain_id}:{context.subdomain_id}:safe_root_exists",
            "status": "pass" if safe_root.exists() and safe_root.is_dir() else "fail",
            "path": str(safe_root.relative_to(context.workspace_root)),
        }
    ]
    for binary in ("ls", "file"):
        proc = runtime.run_command([binary, "--version"], timeout=timeout, max_output_bytes=max_output_bytes)
        if binary == "file" and not proc["ok"]:
            proc = runtime.run_command([binary, "-v"], timeout=timeout, max_output_bytes=max_output_bytes)
        checks.append(
            {
                "id": f"audit:{context.domain_id}:{context.subdomain_id}:external_command:{binary}",
                "status": "pass" if proc["ok"] else "fail",
                "command": binary,
            }
        )
    return {"object_type": "external_command_filesystem_audit", "checks": checks}


def safe_root_exists(context: Any) -> bool:
    safe_root, *_ = _filesystem_config(context)
    return safe_root.exists() and safe_root.is_dir()


def run(context: Any, command: str, rest: list[str], runtime: Any) -> dict[str, Any]:
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
        return _filesystem_discovery(context, rest, runtime=runtime)
    if resolved == "list_files":
        return _list_filesystem(context, rest, kind="file", runtime=runtime)
    if resolved == "list_directories":
        return _list_filesystem(context, rest, kind="directory", runtime=runtime)
    if resolved == "observe":
        return _observe_filesystem(context, rest, runtime=runtime)
    if resolved == "audit":
        return _filesystem_audit(context, runtime=runtime)
    raise ValueError(f"unknown filesystem connector command: {command}")
