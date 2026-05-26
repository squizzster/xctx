# Development Hardening Contract

## State

```yaml
workspace_status: live_local_development
public_compatibility_surface: false
source_of_truth:
  - code
  - tests
  - loaded_yaml
visible_commands: [discover, observe, plan, execute, audit, repair]
hidden_commands: [other]
expected_pytest_result: "full collected suite passes; package install smoke may skip offline when build deps are unavailable"
online_package_smoke: "make package-install-smoke"
```

## Hardened Rules

```yaml
command_surface:
  owner: libs/xctx/protocol/command_policy.py
  visible_exact: [discover, observe, plan, execute, audit, repair]
  hidden_exact: [other]
  aliases: forbidden
  leaked_old_commands: audit_fail
planning:
  plan_id: plan:sha256:<sha256>
  receipt_sha5: accepted_only_if_unique_recorded_prefix
  execute_requires:
    - exactly_one_plan_token
    - --commit
    - matching_config_fingerprint
  mutation_in_reference_workspace: false
audit:
  root_includes:
    - config_loaded
    - agent_domains_loaded
    - config_fingerprint
    - command_surface
    - domain_affordances
    - cli_options
    - normalized_live_adapter_checks
  malformed_check: fail
  adapter_failure: failing_check
redaction:
  helper: libs/xctx/process/redaction.py
  redacts:
    - secret_like_strings
    - secret_like_dict_keys
    - connector_errors
    - command_status
```

## Current Files Of Interest

```yaml
framework:
  - libs/xctx/process/runtime.py
  - libs/xctx/process/parser.py
  - libs/xctx/process/redaction.py
  - libs/xctx/protocol/command_policy.py
  - libs/xctx/domain/actions.py
  - libs/xctx/domain/audit.py
  - libs/xctx/domain/discovery.py
  - libs/xctx/domain/observation.py
connector_boundary:
  - libs/xctx/ports/external_command.py
  - libs/xctx_connectors/runtime.py
  - libs/xctx_connectors/middleware.py
validation:
  - .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
  - tests/test_framework_local_gate.py
  - tests/test_framework_hardening_review.py
  - tests/test_audit_and_options.py
```

## Full Gate

```bash
make full-test
```
