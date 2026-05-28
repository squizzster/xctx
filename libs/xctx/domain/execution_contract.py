"""Protocol-level argument contract for plan and execute.

This module keeps shape validation for the rehearsal/commit boundary out of the
command handlers. It owns only generic xctx contract syntax, not domain meaning.
"""

from __future__ import annotations

from dataclasses import dataclass

from xctx.errors import XctxError


@dataclass(frozen=True)
class PlanRequest:
    """A parsed non-mutating plan request."""

    raw_args: tuple[str, ...]
    operation: str
    target: str | None

    @property
    def operation_text(self) -> str:
        return " ".join(self.raw_args).strip()


@dataclass(frozen=True)
class ExecuteRequest:
    """A parsed execute request bound to one plan identifier."""

    plan_identifier: str
    commit: bool


PLAN_USAGE = "./xctx plan <operation> <target>"
EXECUTE_USAGE = "./xctx execute <PLAN_ID> --commit"


def parse_plan_request(args: list[str]) -> PlanRequest:
    """Parse the generic plan shape without interpreting domain operations."""

    cleaned = [str(arg).strip() for arg in args if str(arg).strip()]
    if not cleaned:
        raise XctxError("missing plan arguments", next_moves=[PLAN_USAGE])
    operation = cleaned[0]
    target = " ".join(cleaned[1:]).strip() or None
    return PlanRequest(raw_args=tuple(cleaned), operation=operation, target=target)


def parse_execute_request(args: list[str], *, commit: bool) -> ExecuteRequest:
    """Parse execute's single-plan-token boundary."""

    cleaned = [str(arg).strip() for arg in args if str(arg).strip()]
    if not cleaned:
        raise XctxError("missing execute target", next_moves=[EXECUTE_USAGE])
    if len(cleaned) != 1:
        raise XctxError("expected exactly one canonical plan id to execute")
    return ExecuteRequest(plan_identifier=cleaned[0], commit=commit)
