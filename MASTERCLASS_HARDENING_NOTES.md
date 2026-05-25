# Hardening Notes

## Current Contract

```yaml
status: live_local_development
visible_commands: [discover, observe, plan, execute, audit, repair]
hidden_commands: [other]
old_aliases: forbidden
source_of_truth: [code, tests, loaded_yaml]
```

## Additions

```yaml
config_fingerprint:
  exposed_by: audit_root
  used_by: execute_stale_plan_refusal
plan_execute:
  parser: xctx.domain.execution_contract
  ledger_validation: fail_closed
  short_receipt: unique_recorded_prefix_only
repair:
  finding_prefix_must_match_current_status: true
cli_options:
  typed_choices: normalized
  numeric_bounds: validated
process:
  capture: tempfile_backed
  missing_returncode_success: forbidden
redaction:
  centralized: xctx.process.redaction
audit:
  malformed_live_checks: fail_closed
  adapter_failures: audit_checks
tests:
  default_pytest: full_collected_suite
  package_install_smoke: included
```

## Gate

```bash
make full-test
```
