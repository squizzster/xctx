# xctx v4.2 Development Boundary Report

## Status

```yaml
workspace: live_local_development
public_compatibility_surface: false
source_of_truth: [code, tests, loaded_yaml]
expected_pytest_result: "102 passed"
```

## Boundary

```yaml
root_surfaces:
  commands:
    - ./xctx --json
    - ./xctx --json help
    - ./xctx --json --version
    - ./xctx --json discover
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
scoped_surfaces:
  may_expose:
    - scoped_domain_affordances
    - scoped_cli_options
    - adapter_owned_object_shapes
```

## Corrections

```yaml
removed_from_root:
  - parser_option_inventory
  - root_affordances
  - command_shortcuts
  - discover_name_shortcut
  - universe_identity_resolution
kept_scoped:
  - stock_identity_resolution
  - filing_taxonomy_search
  - latest_available_bundled_price_discovery
  - market_series_observation_options
  - file_manager_external_command_demo
```

## Audit

```yaml
root_audit:
  includes_live_adapter_checks: true
  normalizes_malformed_live_payloads: true
  converts_adapter_failures_to_checks: true
  redacts_protocol_facing_errors: true
```

## Validation

```bash
make full-test
```
