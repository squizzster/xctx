"""Observation payload construction for xctx discovered objects."""

from __future__ import annotations

from typing import Any

from xctx.domain.core import joined_identifier, offline_subdomain_payload, resolve_subdomain
from xctx.domain.discovery import domain_discovery_payload
from xctx.domain.routing import observe_adapter_option_args, parse_ref, route_for_identifier
from xctx.errors import XctxError
from xctx.ports.external_command import call_external_command


## Protocol boundary: observation routes read-only requests to scoped adapters.
def observe_payload(
    store: dict[str, Any],
    target: str | None,
    rest: list[str],
    item_id: str | None,
    observe_options: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    rest_identifier = joined_identifier(rest)
    identifier = item_id or rest_identifier
    options = observe_options or {}
    domain_id, subdomain_id = parse_ref(store, target)
    if domain_id and subdomain_id:
        subdomain = resolve_subdomain(store, domain_id, subdomain_id)
        if subdomain.get("status") != "online":
            return "agent_subdomain", offline_subdomain_payload(store, domain_id, subdomain)
        if not identifier:
            if options:
                raise XctxError("missing observation target before configured observe options")
            live = call_external_command(store, subdomain, ["discover"])
        else:
            option_args = observe_adapter_option_args(store, subdomain, options)
            live = call_external_command(store, subdomain, ["observe", identifier, *option_args])
        return "agent_subdomain", {"agent_domain": domain_id, "agent_subdomain": subdomain_id, "live_data": live}
    if domain_id:
        if options:
            raise XctxError(
                f"configured observe options require a scoped observe target: {domain_id}",
                next_moves=[f"./xctx observe {domain_id}::<agent_subdomain> --id <id>"],
            )
        return "agent_domain", domain_discovery_payload(store, domain_id)

    identifier = item_id or joined_identifier([target, *rest])
    if not identifier:
        raise XctxError(
            "missing observe target",
            next_moves=["./xctx observe <thing>", "./xctx observe <target> --id <id>"],
        )
    domain_id, subdomain_id = route_for_identifier(store, identifier)
    if not domain_id or not subdomain_id:
        raise XctxError("unknown observation identifier prefix", next_moves=["./xctx discover"])
    subdomain = resolve_subdomain(store, domain_id, subdomain_id)
    if subdomain.get("status") != "online":
        return "agent_subdomain", offline_subdomain_payload(store, domain_id, subdomain)
    option_args = observe_adapter_option_args(store, subdomain, options)
    live = call_external_command(store, subdomain, ["observe", identifier, *option_args])
    return "agent_subdomain", {"agent_domain": domain_id, "agent_subdomain": subdomain_id, "live_data": live}
