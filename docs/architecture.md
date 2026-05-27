# Architecture Contract

## Layer Ownership

```yaml
libs/xctx:
  role: generic_protocol_runtime
  owns:
    - process_argv
    - command_policy
    - parser_contract
    - envelopes
    - generic_ref_parsing
    - option_syntax
    - audit_contract
    - plan_execute_receipts
    - repair_contract
  forbids:
    - domain_semantics
    - adapter_imports
    - provider_logic
yaml_dynamic_config:
  role: configured_domain_surface
  owns:
    - domains
    - subdomains
    - statuses
    - actions
    - scoped_options
    - observe_routes
connector_supervisor_and_adapters:
  role: live_data_boundary
  owns:
    - domain_payloads
    - external_command_transforms
    - provider_or_fixture_semantics
```

## Command Boundary

```yaml
visible_commands: [discover, observe, plan, execute, audit, repair]
hidden_commands: [other]
command_policy_owner: libs/xctx/protocol/command_policy.py
old_command_aliases: forbidden
```

## Key Modules

```yaml
process:
  runtime: top_level_dispatch_and_errors
  parser: argparse_contract_only
  capture: bounded_subprocess_capture
  redaction: shared_protocol_facing_secret_masking
domain:
  core: domain_subdomain_lookup
  routing: structural_ref_and_observe_route_selection
  actions: configured_action_resolution
  discovery: root_domain_subdomain_action_payloads
  observation: read_only_observe_routing
  audit: fail_closed_health_payloads
  repair: offline_and_maintenance_guidance
  planning: deterministic_plan_receipts
ports:
  external_command: connector_supervisor_invocation
connectors:
  middleware: adapter_side_supervisor_dispatch
  runtime: connector_payload_helpers
```

## Gate

```bash
make full-test
```
