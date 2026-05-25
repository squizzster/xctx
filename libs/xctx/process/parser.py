"""Argparse construction isolated from runtime and command handlers."""

from __future__ import annotations

import argparse
from typing import Any, Callable

from xctx.errors import XctxError
from xctx.protocol.accessors import canonical_command, configured_command_names
from xctx.protocol.command_policy import hidden_commands, visible_commands
from xctx.protocol.option_specs import command_cli_option_specs


## Protocol boundary: argparse may expose configured option syntax so the
## interface can parse argv, but option meaning must stay in scoped packs.


class XctxParser(argparse.ArgumentParser):
    """Argument parser that keeps errors inside the xctx JSON contract."""

    def error(self, message: str) -> None:
        raise XctxError(f"next valid move: adjust arguments ({message})")


def _add_discover_parser(subparsers: argparse._SubParsersAction, name: str) -> None:
    parser = subparsers.add_parser(name, add_help=False)
    parser.add_argument("--id")
    parser.add_argument("target", nargs="?")
    parser.add_argument("target_args", nargs=argparse.REMAINDER)


def _argparse_type(option_type: str) -> Callable[[str], Any]:
    if option_type == "int":
        return int
    if option_type == "float":
        return float
    return str


def _add_configured_cli_options(parser: argparse.ArgumentParser, store: dict[str, Any], command: str) -> None:
    """Attach YAML-declared options without hardcoding domain option names."""
    ## Boundary guard: register opaque configured flags; never branch on their
    ## domain-pack semantics in the generic parser.
    for spec in command_cli_option_specs(store, command):
        flags = [str(flag) for flag in spec.get("_flags", [])]
        if not flags:
            continue
        option_type = str(spec.get("_option_type", "str"))
        action = str(spec.get("action", "")).strip()
        kwargs: dict[str, Any] = {
            "dest": spec["_dest"],
            "default": None,
            "required": bool(spec.get("required", False)),
        }
        description = spec.get("desc") or spec.get("description")
        if description:
            kwargs["help"] = str(description)
        if option_type == "bool" or action in {"store_true", "store_false"}:
            kwargs["action"] = action if action in {"store_true", "store_false"} else "store_true"
        else:
            kwargs["type"] = _argparse_type(option_type)
            if spec.get("choices"):
                kwargs["choices"] = list(spec.get("choices") or [])
        parser.add_argument(*flags, **kwargs)


def build_parser(store: dict[str, Any]) -> argparse.ArgumentParser:
    parser = XctxParser(prog="xctx", add_help=False)
    subparsers = parser.add_subparsers(dest="command", parser_class=XctxParser)

    configured = configured_command_names(store)
    visible = visible_commands(store)
    hidden = hidden_commands(store)
    if "help" in configured or not configured:
        subparsers.add_parser("help", add_help=False)
    for command in sorted({name for name in configured if canonical_command(store, name) == "discover"}):
        _add_discover_parser(subparsers, command)
    if "observe" in visible:
        observe = subparsers.add_parser("observe", add_help=False)
        observe.add_argument("target", nargs="?")
        observe.add_argument("target_args", nargs="*")
        observe.add_argument("--id")
        _add_configured_cli_options(observe, store, "observe")
    if "plan" in visible:
        plan = subparsers.add_parser("plan", add_help=False)
        plan.add_argument("plan_args", nargs=argparse.REMAINDER)
    if "execute" in visible:
        execute = subparsers.add_parser("execute", add_help=False)
        execute.add_argument("execute_args", nargs="*")
        execute.add_argument("--commit", action="store_true")
    if "audit" in visible:
        audit = subparsers.add_parser("audit", add_help=False)
        audit.add_argument("scope", nargs="?", default="root")
    if "repair" in visible:
        repair = subparsers.add_parser("repair", add_help=False)
        repair.add_argument("target", nargs="?")
    if "other" in hidden:
        other = subparsers.add_parser("other", add_help=False)
        other.add_argument("--topic", required=True)
        other.add_argument("--reason", default="task dynamic selected the extension lane")

    return parser
