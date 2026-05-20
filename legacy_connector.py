#!/usr/bin/env python3
"""Generic xctx middleware entrypoint for legacy and pass-through connectors."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIBS = ROOT / "libs"
if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from xctx_connectors.middleware import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
