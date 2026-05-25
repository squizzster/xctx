"""User-facing xctx exceptions."""

from __future__ import annotations

from typing import Any


class XctxError(Exception):
    """Raised when xctx should return a protocol-shaped error record."""

    def __init__(self, message: str, *, next_moves: list[Any] | None = None) -> None:
        super().__init__(message)
        self.message = str(message)
        self.next_moves = list(next_moves or [])
