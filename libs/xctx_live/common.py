from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml


def project_root_from_file(file_path: str | Path) -> Path:
    path = Path(file_path).resolve()
    # entrypoints live at project root; library files live below libs/.
    for candidate in [path.parent, *path.parents]:
        if (candidate / "yaml_dynamic_config").exists() and (candidate / "data").exists():
            return candidate
    return path.parent


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping in YAML file: {path}")
    return data


def emit_json(payload: Any, compact: bool = False) -> None:
    if compact:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))


def take_flag(argv: list[str], flag: str) -> tuple[bool, list[str]]:
    present = flag in argv
    return present, [item for item in argv if item != flag]


def joined_query(parts: Iterable[str]) -> str:
    return " ".join(str(part) for part in parts if str(part).strip()).strip()


def normalize_search_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(normalize_search_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(normalize_search_text(item) for item in value.values())
    return str(value)


def usage_error(message: str) -> int:
    emit_json({"ok": False, "error": message}, compact=True)
    return 2
