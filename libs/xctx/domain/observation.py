"""Observation payload construction for xctx discovered objects."""

from __future__ import annotations

from typing import Any

from xctx.domain.core import joined_identifier, offline_subdomain_payload, resolve_subdomain
from xctx.domain.discovery import domain_discovery_payload
from xctx.domain.routing import observe_adapter_option_args, parse_ref
from xctx.errors import XctxError
from xctx.ports.external_command import call_external_command
from xctx.store.runtime_artifacts import is_runtime_ref, result_observation_payload


## Protocol boundary: observation routes scoped requests to adapters. Protocol-local
## runtime artifacts such as result:<sha256> are observed before scoped routing;
## their payload meaning remains adapter-owned.
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
    artifact_identifier = item_id or joined_identifier([target, *rest])
    if artifact_identifier and is_runtime_ref("result", artifact_identifier):
        if options:
            raise XctxError("result observation does not accept scoped observe options")
        return "root", result_observation_payload(store, artifact_identifier)
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
            next_moves=["./xctx observe <agent_domain>::<agent_subdomain> <id>"],
        )
    raise XctxError(
        f"unscoped observe target requires explicit agent_subdomain scope: {identifier}",
        next_moves=["./xctx observe <agent_domain>::<agent_subdomain> <id>"],
    )
