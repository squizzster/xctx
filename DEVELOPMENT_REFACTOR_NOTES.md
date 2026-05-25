# Development Refactor Notes

## Contract

```yaml
status: live_local_development
compatibility_burden: false
source_of_truth: [code, tests, loaded_yaml]
goal: smaller_fail_closed_protocol_core
```

## Refactor Map

```yaml
removed_facades:
  - xctx.domain.agent_domains
  - xctx.protocol.options
split_modules:
  domain:
    - core
    - routing
    - actions
    - interfaces
    - discovery
    - observation
    - audit
    - repair
    - planning
  protocol_options:
    - option_specs
    - option_encoding
    - option_surface
added_boundaries:
  - command_policy
  - config_validation
  - process_capture
  - process_redaction
  - execution_contract
```

## Required Proof

```bash
make full-test
```

Expected:

```text
102 passed
```
