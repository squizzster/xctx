"""Command registry for the modular xctx engine."""

from __future__ import annotations

from typing import Any, Callable

from xctx.commands import audit, discover, doctor, execute, help, identify, observe, other, plan, repair, status, write

CommandHandler = Callable[[dict[str, Any], Any], int]


def command_handlers() -> dict[str, CommandHandler]:
    return {
        "help": help.handle,
        "discovery": discover.handle,
        "status": status.handle,
        "identify": identify.handle,
        "discover": discover.handle,
        "observe": observe.handle,
        "plan": plan.handle,
        "execute": execute.handle,
        "audit": audit.handle,
        "repair": repair.handle,
        "doctor": doctor.handle,
        "write": write.handle,
        "other": other.handle,
    }
