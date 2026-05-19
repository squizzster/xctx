#!/usr/bin/env python3
"""Guardrail checks for xctx YAML protocol surface edits.

This script is intentionally conservative. It validates that the YAML can be
loaded through the real xctx loader and checks common scope-creep mistakes before
running heavier smoke/pressure tests.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[4]
LIBS = ROOT / "libs"
if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

ALLOWED_STATUSES = {"online", "offline", "down_for_maintenance"}
ROOT_SURFACE_FORBIDDEN_TOKENS = (
    "--bars",
    "--calendar-days",
    "configured_options",
    "root_affordances",
    "search_entity_instrument",
    "search_market_series",
    "search_filing_form",
    "search_forms",
    "list_forms",
    "latest_price",
    "latest-price",
)

CORE_RUNTIME_FORBIDDEN_TOKENS = (
    "stock_intelligence_hub",
    "market_data_gateway",
    "equity_filing",
    "search_entity_instrument",
    "search_filing_form",
    "list_forms",
    "latest_price",
    "latest-price",
    "--bars",
    "--calendar-days",
    "ticker",
    "symbol",
)


def finding(level: str, check_id: str, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"level": level, "id": check_id, "message": message}
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def _json_payload_for_xctx(args: list[str]) -> dict[str, Any]:
    from xctx.process.runtime import main as xctx_main

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = xctx_main(["--json", *args], root=ROOT)
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    if code != 0 or len(lines) != 1 or err.getvalue():
        raise RuntimeError(
            f"xctx {' '.join(args) or '<default>'} failed: rc={code}; stdout={out.getvalue()!r}; stderr={err.getvalue()!r}"
        )
    return json.loads(lines[0])


def _contains_token(value: Any, token: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_token(key, token) or _contains_token(child, token) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_token(child, token) for child in value)
    return token in str(value)


def main() -> int:
    findings: list[dict[str, Any]] = []

    try:
        from xctx.config.loader import load_store
        from xctx.protocol.actions import action_matches
        from xctx.protocol.options import option_config_checks, option_surface, target_option_surface
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(json.dumps({"ok": False, "error": f"import_failed: {exc}"}, indent=2))
        return 2

    try:
        store = load_store(root=ROOT)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"load_store_failed: {exc}"}, indent=2))
        return 1

    domains = store.get("agent_domains") or {}
    active_domain = store.get("active_agent_domain")
    if active_domain not in domains:
        findings.append(
            finding(
                "error",
                "active_domain_known",
                "active_agent_domain must reference a known domain",
                active_agent_domain=active_domain,
            )
        )

    universe = store.get("universe") or {}
    if universe.get("root_affordances"):
        findings.append(
            finding(
                "error",
                "universe:root_affordances_removed",
                "domain affordances must live under scoped agent subdomain actions, not universe root_affordances",
            )
        )
    if universe.get("command_shortcuts"):
        findings.append(
            finding(
                "error",
                "universe:command_shortcuts_removed",
                "root command shortcuts must not encode domain-specific action routing",
            )
        )

    for payload_name, args in {
        "universe_default": [],
        "help": ["help"],
        "version": ["--version"],
        "root_discover": ["discover"],
    }.items():
        try:
            payload = _json_payload_for_xctx(args)
        except Exception as exc:
            findings.append(finding("error", f"root_surface:{payload_name}:runs", "root surface command must run", error=str(exc)))
            continue
        for token in ROOT_SURFACE_FORBIDDEN_TOKENS:
            if _contains_token(payload, token):
                findings.append(
                    finding(
                        "error",
                        f"root_surface:{payload_name}:no_{token}",
                        "root/universe/help/version surfaces must not expose scoped domain action tokens",
                        token=token,
                    )
                )

    for rel in (
        "xctx",
        "bin/xctx",
        "libs/xctx/process/parser.py",
        "libs/xctx/process/runtime.py",
        "libs/xctx/commands/discover.py",
        "libs/xctx/commands/observe.py",
        "libs/xctx/domain/agent_domains.py",
        "libs/xctx/domain/identity.py",
        "libs/xctx/commands/identify.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for token in CORE_RUNTIME_FORBIDDEN_TOKENS:
            if token in text:
                findings.append(
                    finding(
                        "error",
                        f"core_runtime:{rel}:no_{token}",
                        "generic xctx runtime must not contain domain-specific literals",
                        token=token,
                    )
                )

    for domain_id, domain in sorted(domains.items()):
        check_prefix = f"domain:{domain_id}"
        if domain.get("id") != domain_id:
            findings.append(finding("error", f"{check_prefix}:id_match", "domain id should match universe key", declared_id=domain.get("id")))
        status = str(domain.get("status") or "unknown")
        if status not in ALLOWED_STATUSES:
            findings.append(finding("error", f"{check_prefix}:status", "domain status must be online, offline, or down_for_maintenance", status=status))
        if status == "down_for_maintenance" and domain.get("repair_path"):
            findings.append(finding("warning", f"{check_prefix}:maintenance_repair", "maintenance domains should normally be terminal instead of repairable"))
        if not (domain.get("basic_description") or domain.get("full_description")):
            findings.append(finding("warning", f"{check_prefix}:description", "domain should describe what is real and what is not"))

        domain_affordance_names: dict[str, str] = {}
        for subdomain_id, subdomain in sorted((domain.get("_subdomains") or {}).items()):
            sub_prefix = f"subdomain:{domain_id}::{subdomain_id}"
            sub_status = str(subdomain.get("status") or "unknown")
            if sub_status not in ALLOWED_STATUSES:
                findings.append(finding("error", f"{sub_prefix}:status", "subdomain status must be online, offline, or down_for_maintenance", status=sub_status))
            entrypoint = subdomain.get("entrypoint") or {}
            entrypoint_file = entrypoint.get("file")
            if sub_status == "online" and entrypoint_file and not (ROOT / str(entrypoint_file)).exists():
                findings.append(finding("error", f"{sub_prefix}:entrypoint_exists", "online subdomain entrypoint file does not exist", entrypoint_file=entrypoint_file))
            if sub_status == "online" and not (subdomain.get("actions") or {}):
                findings.append(finding("error", f"{sub_prefix}:actions", "online subdomain must expose actions"))
            for action_name, action in sorted((subdomain.get("actions") or {}).items()):
                action_prefix = f"action:{domain_id}::{subdomain_id}:{action_name}"
                run_cmd = str(action.get("run_cmd") or "")
                if not run_cmd.startswith("./xctx "):
                    findings.append(finding("error", f"{action_prefix}:run_cmd", "action run_cmd must start with ./xctx", run_cmd=run_cmd))
                if not (action.get("desc") or action.get("description")):
                    findings.append(finding("warning", f"{action_prefix}:description", "action should describe its operational meaning"))
                aliases = [str(alias) for alias in (action.get("aliases") or [])]
                if len(aliases) != len(set(aliases)):
                    findings.append(finding("error", f"{action_prefix}:aliases", "action aliases must be unique", aliases=aliases))
                if action.get("domain_affordance"):
                    public_name = str(action.get("domain_action_name") or action_name)
                    existing = domain_affordance_names.get(public_name)
                    if existing:
                        findings.append(
                            finding(
                                "error",
                                f"domain_affordance:{domain_id}:{public_name}:unique",
                                "domain affordance names must be unique within an agent domain",
                                first=existing,
                                second=f"{subdomain_id}:{action_name}",
                            )
                        )
                    domain_affordance_names[public_name] = f"{subdomain_id}:{action_name}"
                    if not action_matches(public_name, {**action, "aliases": aliases + [action_name]}, public_name):
                        findings.append(finding("error", f"{action_prefix}:domain_action_name", "domain affordance name must resolve through action matching"))

    routing = universe.get("agent_routing") or {}
    for route in routing.get("observe_routes", []) or []:
        route_id = str(route.get("id") or "<unnamed>")
        domain_id = str(route.get("agent_domain") or "")
        subdomain_id = str(route.get("agent_subdomain") or "")
        route_prefix = f"observe_route:{route_id}"
        if domain_id not in domains:
            findings.append(finding("error", f"{route_prefix}:domain", "observe route references unknown domain", agent_domain=domain_id))
            continue
        if subdomain_id not in (domains[domain_id].get("_subdomains") or {}):
            findings.append(finding("error", f"{route_prefix}:subdomain", "observe route references unknown subdomain", agent_domain=domain_id, agent_subdomain=subdomain_id))
        if not (route.get("prefixes") or route.get("unprefixed_exact")):
            findings.append(finding("error", f"{route_prefix}:matchers", "observe route needs prefixes or unprefixed_exact tokens"))

    default_route = routing.get("default_observe_route") or {}
    if default_route:
        domain_id = str(default_route.get("agent_domain") or "")
        subdomain_id = str(default_route.get("agent_subdomain") or "")
        if domain_id not in domains or subdomain_id not in (domains.get(domain_id, {}).get("_subdomains") or {}):
            findings.append(finding("error", "default_observe_route", "default observe route must reference a known subdomain", agent_domain=domain_id, agent_subdomain=subdomain_id))

    identity_fields = universe.get("identity_resolution", {}).get("query_fields") or []
    if not identity_fields or not all(isinstance(item, str) and item.strip() for item in identity_fields):
        findings.append(finding("error", "identity_resolution:query_fields", "identity query_fields must be a non-empty list of strings"))
    if len(identity_fields) != len(set(identity_fields)):
        findings.append(finding("error", "identity_resolution:query_fields_unique", "identity query_fields must be unique", query_fields=identity_fields))
    if any(field in {"ticker", "symbol"} for field in identity_fields):
        findings.append(finding("error", "identity_resolution:generic_fields_only", "universe identity fields must stay generic; ticker/symbol belong in domain adapters"))

    for check in option_config_checks(store):
        if check.get("status") != "pass":
            findings.append(finding("error", check.get("id", "cli_options"), "configured CLI option surface failed audit", check=check))

    parser_surface = option_surface(store)
    scoped_option_surfaces: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for domain_id, domain in sorted(domains.items()):
        for subdomain_id, subdomain in sorted((domain.get("_subdomains") or {}).items()):
            surface = target_option_surface(store, subdomain)
            if surface:
                scoped_option_surfaces[f"{domain_id}::{subdomain_id}"] = surface

    errors = [item for item in findings if item["level"] == "error"]
    warnings = [item for item in findings if item["level"] == "warning"]
    payload = {
        "ok": not errors,
        "repo_root": str(ROOT),
        "active_agent_domain": active_domain,
        "domain_count": len(domains),
        "parser_option_counts": {command: len(entries) for command, entries in parser_surface.items()},
        "scoped_configured_options": scoped_option_surfaces,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "findings": findings,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
