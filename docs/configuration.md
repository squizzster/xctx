# YAML Configuration Contract

## Source Truth

```yaml
status: live_local_development
authoritative: loaded_yaml_plus_code_plus_tests
skill_docs_authoritative_when_stale: false
```

## Files

```yaml
universe: yaml_dynamic_config/universe.yaml
protocol: yaml_dynamic_config/protocols/xctx_v4_2.yaml
commands: yaml_dynamic_config/shared/command_sets/core_commands.yaml
domains: yaml_dynamic_config/agent_domains/*/domain.yaml
subdomains: yaml_dynamic_config/agent_domains/*/subdomains/*/subdomain.yaml
```

## Forbidden In Universe

```yaml
forbidden:
  - active_agent_domain
  - active_system
  - systems
  - identity_resolution
  - root_affordances
  - command_shortcuts
  - agent_routing.discovery_fallback
  - agent_routing.default_observe_route
```

## Domain Affordances

```yaml
declaration_location: subdomain.actions.<action_id>
required_flag: domain_affordance: true
optional_public_name: domain_action_name
constraints:
  - unique_within_domain
  - must_not_equal_subdomain_id
  - unscoped_equivalent_must_fail_or_guidance_to_scoped_command
```

## Actions

```yaml
action_required_fields:
  - run_cmd
  - desc
query_required_true:
  no_query_discovery: returns_interface_metadata
query_required_false:
  no_query_discovery: may_execute_bounded_discovery_or_list
collection_controls:
  optional:
    - --limit
    - --cursor
    - --projection
  owner: action.collection
  cursor_meaning: adapter_owned
```

## CLI Options

```yaml
location: owning_action.cli_options
supported_types: [str, int, float, bool]
root_publication: forbidden
scoped_publication: owning_subdomain_or_action_only
wrong_target: refused_before_wrong_adapter_call
```

## Connectors

```yaml
entrypoint_file: connector_supervisor.py
allowed_connector_kinds:
  - xctx_native_passthrough
  - external_command
path_rules:
  - workspace_relative
  - resolves_inside_workspace
forbidden_connector_keys:
  - profile
  - module
  - adapter_module
  - python_module
  - import_path
external_command_adapter_path:
  domain: libs/xctx_connectors/domains/<domain>/external_command_adapter.py
  subdomain: libs/xctx_connectors/domains/<domain>/subdomains/<subdomain>/external_command_adapter.py
```

## Gate

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
```


## Output Detail

```yaml
detail_level:
  owner: xctx_framework_envelope
  values: [basic, more, max]
  default:
    naked_orientation_surfaces: more
    scoped_and_named_surfaces: basic
  controls:
    - protocol_guidance
    - framework_diagnostics
    - provenance
  never_controls:
    - domain_row_projection
    - pagination
    - output_format
    - permission
    - commit_boundary
projection:
  owner: scoped_domain_action
  values: domain_declared
  example: --projection compact|full
```
