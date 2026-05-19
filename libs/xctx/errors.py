"""User-facing xctx exceptions."""

from __future__ import annotations


class XctxError(Exception):
    """Raised when the next valid protocol move should be returned to the caller."""
