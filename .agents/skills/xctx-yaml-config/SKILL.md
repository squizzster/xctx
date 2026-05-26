---
name: xctx-yaml-config
description: Modify xctx YAML domains, subdomains, actions, scoped affordances, command options, routing, statuses, connectors, and repair paths while preserving the generic root protocol boundary.
---

# xctx YAML Config Skill

## Authority

```yaml
workspace_status: live_local_development
public_compatibility_surface: false
skill_is_source_of_truth: false
source_of_truth:
  - current_code
  - current_tests
  - loaded_yaml
compatibility_policy:
  default: clean_current_contract
  preserve_old_behavior_only_if: explicit_release_or_migration_requirement
```

If this skill conflicts with current code/tests/YAML, inspect the implementation and update the stale side. Do not add aliases, shims, wrappers, or layered checks for obsolete behavior unless the user explicitly creates a migration requirement.

## Root Contract

```yaml
visible_commands: [discover, observe, plan, execute, audit, repair]
hidden_commands: [other]
root_surfaces:
  - ./xctx
  - ./xctx help
  - ./xctx --version
  - ./xctx discover
root_may_show:
  - generic_commands
  - configured_agent_domains
  - generic_next_moves
root_must_not_show:
  - scoped_action_names
  - scoped_option_names
  - domain_identity_semantics
  - adapter_vocabulary
  - implicit_domain_selection
```

## Boundary Contract

```yaml
libs/xctx:
  owns:
    - command_policy
    - argv_parser_shape
    - record_envelopes
    - generic_ref_shapes
    - option_syntax
    - audit_shape
    - plan_execute_receipts
    - repair_shape
  forbids:
    - ticker_semantics
    - filing_semantics
    - filesystem_semantics
    - provider_logic
    - arbitrary_adapter_imports
scoped_yaml_and_adapters:
  own:
    - domain_nouns
    - action_meaning
    - list_payload_shape
    - identity_ranking
    - data_source_behavior
    - observe_materialization
```

## Pressure Questions

Apply to every YAML, adapter, framework, and docs change:

```yaml
checks:
  - id: source_truth
    question: Does this match current code, tests, and loaded YAML?
  - id: root_surface
    question: Are root/help/version/discover still generic?
  - id: explicit_scope
    question: Does each domain operation require domain or subdomain scope?
  - id: core_purity
    question: Did all domain nouns stay out of libs/xctx generic runtime?
  - id: action_ownership
    question: Is each affordance declared on the subdomain action that owns it?
  - id: error_shape
    question: Is actual failure text in error and recovery guidance in next_moves?
  - id: audit_fail_closed
    question: Do malformed audit data and adapter failures become failing checks?
  - id: redaction
    question: Are protocol-facing secrets redacted in strings and dict values?
  - id: full_validation
    question: Did make full-test or its exact commands pass?
```

## YAML Rules

```yaml
forbidden_universe_keys:
  - active_agent_domain
  - active_system
  - systems
  - identity_resolution
  - root_affordances
  - command_shortcuts
forbidden_routing:
  - agent_routing.discovery_fallback
  - agent_routing.default_observe_route
domain_affordance:
  location: subdomain.actions.<action>
  required: domain_affordance: true
  optional_name: domain_action_name
  constraints:
    - unique_within_domain
    - must_not_collide_with_subdomain_id
    - unscoped_equivalent_refused
cli_options:
  location: owning_action.cli_options
  supported_types: [str, int, float, bool]
  root_publication: forbidden
  wrong_target: fail_before_wrong_adapter
collection:
  optional_controls: [--limit, --cursor, --shape]
  cursor_semantics: adapter_owned
```

## Discover Observe Boundary

```yaml
discover:
  returns:
    - object_identity
    - classification
    - coverage
    - counts
    - examples
    - observe_commands
    - next_moves
  forbids:
    - raw_documents
    - raw_price_series
    - full_materialized_object_state
    - CSV_payloads
observe:
  returns:
    - materialized_selected_object
    - current_state_or_contents
```

## Connector Contract

```yaml
entrypoint_file: connector_supervisor.py
connector_kinds:
  - xctx_native_passthrough
  - external_command
paths:
  target_entrypoint: workspace_relative_file_inside_workspace
  safe_root: workspace_relative_path_inside_workspace
forbidden_connector_keys:
  - profile
  - module
  - adapter_module
  - python_module
  - import_path
adapter_paths:
  domain: libs/xctx_connectors/domains/<domain>/external_command_adapter.py
  subdomain: libs/xctx_connectors/domains/<domain>/subdomains/<subdomain>/external_command_adapter.py
shape_guarantee:
  xctx_receives: single_json_object_for_live_data
  raw_external_output: never_returned_unparsed
failure_shapes:
  - xctx_connector_error
  - xctx_native_passthrough_error
```

## Validation

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 -m pytest -q --durations=30
```

Expected current pytest result:

```text
full collected suite passes; package install smoke may skip offline when build deps are unavailable
run `make package-install-smoke` for the explicit online package smoke
```
