# Agent Contract

## Source Truth

```yaml
status: live_local_development
public_compatibility_target: false
authoritative:
  - current_code
  - current_tests
  - loaded_yaml
non_authoritative_when_stale:
  - markdown_docs
  - local_skills
  - reports
compatibility_policy:
  default: remove_obsolete_paths
  preserve_old_behavior_only_if: explicit_release_or_migration_requirement
```

## Command Surface

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
  - discovery
  - d
  - identify
  - status
  - doctor
  - write
```

## Scope Rule

```yaml
root:
  may_show:
    - agent_domains
    - generic_commands
    - generic_next_moves
  must_not_show:
    - scoped_action_names
    - scoped_option_names
    - adapter_vocabulary
    - implicit_domain_selector
domain:
  path: "<domain>"
subdomain:
  path: "<domain>::<subdomain>"
action:
  path: "<domain>::<subdomain>::<action>"
domain_affordance:
  path: "<domain>::<affordance>"
  declared_by: subdomain_action_domain_affordance_true
  duplicate_behavior:
    status: fail_closed
    next_moves: fully_qualified_domain_subdomain_action_commands
  response_must_disclose:
    - agent_domain
    - agent_subdomain
    - implemented_by
    - implemented_by_run_cmd
```

## Framework Boundary

```yaml
libs/xctx:
  owns:
    - argv_parsing
    - command_admission
    - envelopes
    - generic_reference_patterns
    - option_syntax
    - audit_contract
    - plan_receipts
    - repair_contract
  forbids:
    - provider_semantics
    - ticker_semantics
    - filing_semantics
    - filesystem_semantics
    - adapter_imports
yaml_and_adapters:
  own:
    - domain_nouns
    - action_meaning
    - result_ranking
    - data_source_behavior
    - observe_payload_materialization
```

## Pressure Questions

Ask these before accepting any framework, YAML, adapter, or docs change:

```yaml
checks:
  - id: source_truth
    question: Does this match current code, tests, and loaded YAML?
  - id: root_surface
    question: Does root/version/discover stay generic and help aliases fail closed?
  - id: explicit_scope
    question: Does every domain operation require explicit domain or subdomain scope?
  - id: core_purity
    question: Did domain vocabulary avoid libs/xctx generic runtime?
  - id: error_contract
    question: Is error text in error and recovery guidance in next_moves?
  - id: audit_fail_closed
    question: Do malformed checks and adapter failures become failing audit checks?
  - id: redaction
    question: Are protocol-facing errors, argv, args, and payload previews redacted?
  - id: no_compat_shim
    question: Did we remove obsolete paths instead of preserving old behavior?
  - id: full_tests
    question: Did validation run the full collected pytest suite, not a subset?
```

## Local Gate

```bash
make full-test
```

Expected:

```text
102 passed
```
