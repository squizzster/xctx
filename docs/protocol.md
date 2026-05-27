# Protocol Contract

## Status

```yaml
protocol_version: v4.2
workspace: live_local_development
public_compatibility_surface: false
source_of_truth: [code, tests, loaded_yaml]
```

## Commands

```yaml
visible:
  - discover
  - observe
  - plan
  - execute
  - audit
  - repair
hidden:
  - other
removed:
  - help
  - --help
  - -h
  - discovery
  - d
  - identify
  - write
  - doctor
  - status
```

## Envelope

```yaml
required_keys:
  - version_xctx
  - cmdline_arg
  - record_type
  - ok
  - results
error_record:
  error: actual_error_text
  next_moves: optional_structured_command_hints
record_types:
  - version
  - discovery
  - result
  - observation
  - plan
  - execution_result
  - audit
  - repair_result
  - extension
  - error
domain_levels:
  - universe
  - root
  - agent_domain
  - agent_subdomain
```

## Scope

```yaml
root:
  valid_bare_targets: configured_agent_domains_only
  invalid_bare_targets:
    - subdomain_ids
    - action_ids
    - instruments
    - filing_codes
    - file_ids
domain_affordance:
  syntax: "<domain>::<affordance>"
  source: subdomain_action_domain_affordance_true
  duplicate_behavior:
    status: fail_closed
    next_moves: fully_qualified_domain_subdomain_action_commands
  response_contract:
    action: public_affordance_name
    agent_domain: explicit_configured_domain
    agent_subdomain: concrete_implementing_subdomain
    implemented_by: "<domain>::<subdomain>::<action>"
    implemented_by_run_cmd: "./xctx discover <domain>::<subdomain>::<action>"
subdomain_action:
  syntax:
    - "<domain>::<subdomain>::<action>"
  response_contract_when_domain_affordance_exists:
    domain_action_name: public_affordance_name
    domain_affordance_run_cmd: "./xctx discover <domain>::<affordance>"
```

## Audit

```yaml
root_audit:
  purpose: broad_framework_config_availability_live_adapter_health
  may_include_domain_check_ids: true
  must_not_advertise_root_domain_commands: true
malformed_checks: fail_closed
adapter_failures: failing_audit_checks
redaction: required
```

## Plan Execute

```yaml
plan_id: plan:sha256:<sha256>
receipt_sha5: debug_prefix_only_not_executable
execute_requires:
  - one_plan_token
  - --commit
  - matching_config_fingerprint
reference_workspace_mutates_domain_state: false
```
