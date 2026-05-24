"""Shared command helpers."""

from __future__ import annotations

import argparse
from typing import Any


def cmdline_arg(args: argparse.Namespace, command: str) -> str:
    return getattr(args, "cmdline_arg", command)


def live_payload_failed(payload: Any) -> bool:
    """Return true when a shaped live payload represents connector failure."""
    if not isinstance(payload, dict):
        return False
    object_type = str(payload.get("object_type", "")).lower()
    if object_type.endswith("_error"):
        return True
    command_status = payload.get("command_status")
    if isinstance(command_status, dict):
        if command_status.get("timed_out") is True:
            return True
        if command_status.get("ok") is False:
            return True
    target_payload = payload.get("target_payload")
    if isinstance(target_payload, dict) and target_payload.get("ok") is False:
        return True
    return False


def command_payload_failed(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("status") in {"offline", "down_for_maintenance"}:
        return True
    return live_payload_failed(payload.get("live_data"))


def command_payload_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("status") in {"offline", "down_for_maintenance"}:
        return str(payload.get("status"))
    live = payload.get("live_data")
    if not isinstance(live, dict):
        return None
    command_status = live.get("command_status")
    if isinstance(command_status, dict):
        error = command_status.get("error")
        if error:
            return str(error)
        if command_status.get("timed_out") is True:
            return "connector_timeout"
    target_payload = live.get("target_payload")
    if isinstance(target_payload, dict) and target_payload.get("error"):
        return str(target_payload["error"])
    object_type = live.get("object_type")
    return str(object_type) if object_type else None
