"""Thin public CLI API for xctx.

The process runtime lives in xctx.process.runtime so CLI mechanics do not mix
with command handlers, protocol formatting, IO, or domain behavior.
"""

from __future__ import annotations

from xctx.process.runtime import main, run

__all__ = ["main", "run"]
