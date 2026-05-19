"""Helpers for resolving configured protocol actions."""

from __future__ import annotations

from typing import Any


def action_tokens(action_name: str, action: dict[str, Any]) -> set[str]:
    tokens = {action_name}
    entrypoint_command = action.get("entrypoint_command")
    if entrypoint_command:
        tokens.add(str(entrypoint_command))
    tokens.update(str(alias) for alias in action.get("aliases", []) or [])
    return tokens


def action_matches(action_name: str, action: dict[str, Any], token: str) -> bool:
    return token in action_tokens(action_name, action)
