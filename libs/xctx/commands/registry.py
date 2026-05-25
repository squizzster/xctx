"""Command registry for the modular xctx engine."""

from __future__ import annotations

from typing import Any, Callable

from xctx.commands import audit, discover, execute, help, observe, other, plan, repair

CommandHandler = Callable[[dict[str, Any], Any], int]


def command_handlers() -> dict[str, CommandHandler]:
    return {
        "help": help.handle,
        "discover": discover.handle,
        "observe": observe.handle,
        "plan": plan.handle,
        "execute": execute.handle,
        "audit": audit.handle,
        "repair": repair.handle,
        "other": other.handle,
    }
