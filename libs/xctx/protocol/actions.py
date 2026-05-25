"""Helpers for resolving configured protocol actions."""

from __future__ import annotations

from typing import Any


def action_tokens(action_name: str, action: dict[str, Any]) -> set[str]:
    return {action_name}


def action_matches(action_name: str, action: dict[str, Any], token: str) -> bool:
    return token in action_tokens(action_name, action)
