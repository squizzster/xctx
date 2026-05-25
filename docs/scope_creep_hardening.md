# Scope Boundary Contract

## Root Surfaces

```yaml
commands:
  - ./xctx
  - ./xctx help
  - ./xctx --version
  - ./xctx discover
must_expose:
  - generic_xctx_identity
  - visible_core_commands
  - configured_agent_domains
  - generic_next_moves
must_not_expose:
  - --bars
  - --calendar-days
  - --name
  - configured_options
  - root_affordances
  - search_entity_instrument
  - search_market_series
  - latest_price
  - latest-price
```

## Scoped Surfaces

```yaml
domain: ./xctx discover <domain>
subdomain: ./xctx discover <domain>::<subdomain>
subdomain_action: ./xctx discover <domain>::<subdomain> <action>
domain_affordance: ./xctx discover <domain>::<affordance>
observe: ./xctx observe <domain>::<subdomain> <id>
```

## Refusals

```yaml
must_fail:
  - ./xctx discover --name Apple
  - ./xctx discover search_filing_family annual
  - ./xctx discover market_data_gateway
  - ./xctx discover file:README.txt
  - ./xctx observe form:10-K --bars 5
error_shape:
  record_type: error
  error: actual_error
  next_moves: structured_guidance_when_known
```

## Audit Exception

```yaml
root_audit_may_include:
  - framework_checks
  - config_fingerprint
  - availability_findings
  - normalized_live_adapter_checks
root_audit_must_not:
  - advertise_domain_actions_as_root_commands
  - leak_unredacted_connector_errors
```
