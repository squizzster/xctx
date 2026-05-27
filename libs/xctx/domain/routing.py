"""Reference parsing and target-routing helpers for xctx domains."""

from __future__ import annotations

from typing import Any

from xctx.domain.actions import domain_action_config, iter_domain_action_configs, subdomain_action_config
from xctx.protocol.actions import action_matches
from xctx.protocol.option_encoding import encode_cli_options_for_target


## Protocol boundary: routing is structural. Domain identifiers and prefixes are
## configuration data; the generic layer does not infer business meaning.
def parse_ref(store: dict[str, Any], token: str | None) -> tuple[str | None, str | None]:
    if not token:
        return None, None
    domains = store.get("agent_domains", {})
    if "::" in token:
        domain_id, subdomain_id = token.split("::", 1)
        if domain_id not in domains:
            return None, None
        if not subdomain_id:
            return domain_id, None
        return domain_id, subdomain_id
    if token in domains:
        return token, None
    return None, None

def parse_scoped_action(
    store: dict[str, Any],
    token: str | None,
    action_args: list[str] | None = None,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Parse <agent_domain>::<domain_affordance> without mistaking the affordance for a subdomain."""
    if not token or "::" not in token:
        return None, None, None
    domain_id, scoped_token = token.split("::", 1)
    if not domain_id or not scoped_token:
        return None, None, None
    if domain_id not in store.get("agent_domains", {}):
        return None, None, None
    action = domain_action_config(store, domain_id, scoped_token, action_args=action_args)
    if action:
        return domain_id, str(action.get("_action_name", scoped_token)), action
    return None, None, None

def observe_adapter_option_args(store: dict[str, Any], subdomain: dict[str, Any], options: dict[str, Any]) -> list[str]:
    """Encode observe options only after the concrete subdomain is resolved."""
    action_name, action = subdomain_action_config(subdomain, "observe")
    return encode_cli_options_for_target(
        store,
        subdomain,
        "observe",
        action_name=action_name,
        action=action,
        values=options or {},
    )

def scoped_action_run_cmd(store: dict[str, Any], action_name: str) -> str:
    domains = store.get("agent_domains", {})
    for domain_id in domains:
        for name, action in iter_domain_action_configs(store, domain_id):
            if action_matches(name, action, action_name):
                return f"./xctx discover {domain_id}::{name}"
    return ""
