# xctx v4.2.3

## Contract

```yaml
project: xctx
version_package: 4.2.3
version_protocol: v4.2
status: live_local_development
deployed_public_compatibility_surface: false
source_of_truth:
  - current_code
  - current_tests
  - loaded_yaml
derived_artifacts:
  - markdown_docs
  - local_skills
  - reports
backward_compatibility_burden: false
visible_commands:
  - discover
  - observe
  - plan
  - execute
  - audit
  - repair
hidden_commands:
  - other
removed_root_commands:
  - discovery
  - d
  - identify
  - status
  - doctor
  - write
generic_runtime: libs/xctx
domain_runtime:
  - yaml_dynamic_config
  - connector_supervisor.py
  - libs/xctx_connectors
  - libs/xctx_live
  - examples
```

## Rules

```yaml
root_surface:
  exposes:
    - configured_agent_domains
    - visible_core_commands
    - generic_next_moves
  forbids:
    - domain_action_names
    - domain_option_names
    - bare_subdomain_routing
    - implicit_domain_selection
    - old_command_aliases
scoped_surface:
  required_path: "<domain>::<subdomain>[::<action>]"
  domain_affordance_path: "<domain>::<domain_affordance>"
  owner: scoped_yaml_and_adapter
errors:
  error_field: actual_error_only
  next_moves: separate_structured_guidance
audit:
  root: framework_config_availability_and_normalized_live_adapter_health
  malformed_checks: fail_closed
  adapter_failures: failing_audit_checks
redaction:
  shared_helper: xctx.process.redaction
  applies_to:
    - protocol_errors
    - command_status
    - argv_previews
    - requested_args
    - target_payload_previews
```

## Commands

```bash
./xctx
./xctx help
./xctx discover
./xctx discover stock_intelligence_hub
./xctx discover stock_intelligence_hub::market_data_gateway
./xctx discover stock_intelligence_hub::equity_filing
./xctx observe stock_intelligence_hub::market_data_gateway instrument:aapl --bars 5
./xctx audit root
./xctx plan bring_online stock_intelligence_hub::market_data_gateway
./xctx execute <plan_id_or_receipt> --commit
```

## Refusals

```bash
./xctx discovery
./xctx discover --name Apple
./xctx discover search_filing_family annual
./xctx discover market_data_gateway
./xctx observe form:10-K --bars 5
```

## Validation

```bash
make full-test
```

Equivalent:

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 -m pytest -q --durations=30
```

Expected current pytest result:

```text
102 passed
```

`python3 -m pytest -q` means the full collected suite. Marker and file selections are subset/debug runs only.
