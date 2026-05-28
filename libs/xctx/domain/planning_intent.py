"""Planned-effect intent resolution and argument parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xctx.domain.actions import parse_scoped_subdomain_mode_ref, validate_declared_action_args
from xctx.domain.core import resolve_subdomain
from xctx.domain.routing import parse_scoped_action
from xctx.errors import XctxError
from xctx.protocol.option_encoding import encode_cli_options_for_target
from xctx.protocol.option_specs import target_cli_option_specs


@dataclass(frozen=True)
class PlannedAction:
    domain_id: str
    subdomain_id: str
    action_name: str
    action: dict[str, Any]
    planning: dict[str, Any]
    domain_action_name: str | None = None


@dataclass(frozen=True)
class PlannedActionArgs:
    values: dict[str, Any]
    adapter_args: list[str]
    positional_args: list[str]


def planning_contract(action: dict[str, Any]) -> dict[str, Any]:
    planning = action.get("planning") or {}
    if not isinstance(planning, dict):
        return {}
    if planning.get("planned_effect") is True:
        return planning
    if str(planning.get("mode") or "").strip() == "planned_effect":
        return planning
    return {}


def resolve_planned_action(store: dict[str, Any], operation_token: str, action_args: list[str]) -> PlannedAction | None:
    if "::" not in operation_token:
        return None

    domain_id, subdomain_id, action_name, action = parse_scoped_subdomain_mode_ref(store, operation_token)
    if domain_id and subdomain_id and action_name and action:
        planning = planning_contract(action)
        if planning:
            return PlannedAction(domain_id, subdomain_id, action_name, action, planning)
        return None

    domain_id, domain_action_name, domain_action = parse_scoped_action(store, operation_token, action_args=action_args)
    if domain_id and domain_action_name and domain_action:
        planning = planning_contract(domain_action)
        if not planning:
            return None
        return PlannedAction(
            domain_id,
            str(domain_action["agent_subdomain"]),
            str(domain_action.get("_source_action_name") or domain_action_name),
            domain_action,
            planning,
            domain_action_name=domain_action_name,
        )
    return None


def coerce_plan_option(value: Any, spec: dict[str, Any]) -> Any:
    option_type = str(spec.get("_option_type", "str"))
    flag = str(spec.get("_primary_flag") or spec.get("_dest") or "option")
    if option_type == "int":
        if isinstance(value, bool):
            raise XctxError(f"invalid integer for {flag}")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise XctxError(f"invalid integer for {flag}") from exc
    if option_type == "float":
        if isinstance(value, bool):
            raise XctxError(f"invalid number for {flag}")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise XctxError(f"invalid number for {flag}") from exc
    if option_type == "bool":
        return bool(value) if isinstance(value, bool) else str(value).lower() not in {"0", "false", "no", "off"}
    return str(value)


def parse_planned_action_args(
    store: dict[str, Any],
    planned: PlannedAction,
    action_args: list[str],
) -> PlannedActionArgs:
    subdomain = resolve_subdomain(store, planned.domain_id, planned.subdomain_id)
    validate_declared_action_args(planned.action, action_args)
    specs = target_cli_option_specs(
        store,
        subdomain,
        "plan",
        action_name=planned.action_name,
        action=planned.action,
    )
    by_flag = {str(flag): spec for spec in specs for flag in spec.get("_flags", [])}
    values: dict[str, Any] = {}
    positional: list[str] = []
    index = 0
    while index < len(action_args):
        token = action_args[index]
        if token.startswith("-"):
            spec = by_flag.get(token)
            if not spec:
                raise XctxError(
                    f"unsupported option {token} for {planned.domain_id}::{planned.subdomain_id} plan",
                    next_moves=[
                        str(
                            planned.action.get("run_cmd")
                            or f"./xctx plan {planned.domain_id}::{planned.subdomain_id}::{planned.action_name}"
                        )
                    ],
                )
            dest = str(spec["_dest"])
            option_type = str(spec.get("_option_type", "str"))
            action = str(spec.get("action", "")).strip()
            if option_type == "bool" or action in {"store_true", "store_false"}:
                values[dest] = action != "store_false"
                index += 1
                continue
            if index + 1 >= len(action_args):
                raise XctxError(f"missing value for {token}")
            values[dest] = coerce_plan_option(action_args[index + 1], spec)
            index += 2
            continue
        positional.append(token)
        index += 1

    for spec in specs:
        dest = str(spec["_dest"])
        if dest in values:
            continue
        if "default" in spec:
            values[dest] = coerce_plan_option(spec["default"], spec)
    missing = [str(spec.get("_primary_flag") or spec["_dest"]) for spec in specs if spec.get("required") and spec["_dest"] not in values]
    if missing:
        raise XctxError(f"missing required plan option: {missing[0]}")

    option_args = encode_cli_options_for_target(
        store,
        subdomain,
        "plan",
        action_name=planned.action_name,
        action=planned.action,
        values=values,
    )
    return PlannedActionArgs(values=values, adapter_args=[*positional, *option_args], positional_args=positional)


def planning_default(
    store: dict[str, Any],
    planned: PlannedAction,
    key: str,
    default: Any,
) -> Any:
    domain = store.get("agent_domains", {}).get(planned.domain_id) or {}
    subdomain = resolve_subdomain(store, planned.domain_id, planned.subdomain_id)
    for container in (
        planned.planning,
        subdomain.get("planning_defaults") or {},
        domain.get("planning_defaults") or {},
    ):
        if isinstance(container, dict) and container.get(key) is not None:
            return container[key]
    return default


def render_template(template: str, values: dict[str, Any]) -> str:
    rendered = str(template)
    for key, value in sorted(values.items(), key=lambda item: len(str(item[0])), reverse=True):
        rendered = rendered.replace("{{ " + str(key) + " }}", str(value))
        rendered = rendered.replace("{{" + str(key) + "}}", str(value))
    return rendered
