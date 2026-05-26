# Validation Contract

## Truth

```yaml
status: live_local_development
pytest_default: full_collected_suite
subset_runs:
  allowed_for: debugging
  allowed_as_full_validation: false
expected_pytest_result: "full collected suite passes; package install smoke may skip offline when build deps are unavailable"
online_package_smoke: "make package-install-smoke"
```

## Full Gate

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 -m pytest -q --durations=30
```

Make target:

```bash
make full-test
```

## Required Probe Classes

```yaml
root_boundary:
  commands:
    - ./xctx --json
    - ./xctx --json help
    - ./xctx --json --version
    - ./xctx --json discover
  forbidden_tokens:
    - --bars
    - --calendar-days
    - --name
    - configured_options
    - search_entity_instrument
    - search_market_series
    - latest_price
    - latest-price
audit:
  commands:
    - ./xctx --json audit root
    - ./xctx --json audit stock_intelligence_hub::market_data_gateway
    - ./xctx --json audit file_manager::home_directory
  must:
    - include_config_fingerprint
    - normalize_live_adapter_checks
    - fail_closed_on_malformed_checks
    - redact_protocol_facing_error_text
refusals:
  commands:
    - ./xctx --json discovery
    - ./xctx --json discover --name Apple
    - ./xctx --json discover search_filing_family annual
    - ./xctx --json discover market_data_gateway
    - ./xctx --json observe form:10-K --bars 5
  must:
    - return_record_type_error
    - keep_error_actual
    - use_next_moves_for_recovery_guidance
```
