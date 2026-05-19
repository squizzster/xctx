"""Stdout serialization for xctx protocol records."""

from __future__ import annotations

import sys
from typing import Any

import yaml

from xctx.io.jsonl import write_jsonl


def write_yaml_doc(payload: dict[str, Any]) -> None:
    yaml.safe_dump(payload, sys.stdout, sort_keys=False, allow_unicode=False, explicit_start=True)
    sys.stdout.flush()


def write_stdout_record(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "yaml":
        write_yaml_doc(payload)
        return
    write_jsonl(payload)
