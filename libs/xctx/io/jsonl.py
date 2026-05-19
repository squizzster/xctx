"""JSONL stdout helpers."""

from __future__ import annotations

import json
import sys
from typing import Any


def write_jsonl(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=False) + "\n")
    sys.stdout.flush()
