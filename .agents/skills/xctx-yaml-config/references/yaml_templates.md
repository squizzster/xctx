# xctx YAML Templates

## Domain

```yaml
id: <domain_id>
kind: agent_domain
status: offline
health: unavailable_until_adapter_is_bound
basic_description: <one sentence>
full_description: <truthful capability and limitation statement>
agent_subdomains: {}
repair_path:
  run_cmd: ./xctx repair offline:<domain_id>
  desc: Bring this domain online by adding subdomains, adapters, data paths, and validation.
```

Register:

```yaml
agent_domains:
  - id: <domain_id>
    path: agent_domains/<domain_id>/domain.yaml
```

## Subdomain

```yaml
id: <subdomain_id>
kind: agent_subdomain
status: offline
basic_description: <one sentence>
full_description: <truthful capability and limitation statement>
data_description: <truthful data source and freshness statement>
repair_path:
  run_cmd: ./xctx repair offline:<domain_id>::<subdomain_id>
  desc: Add or enable adapter and validation proof.
actions:
  discover:
    priority: 10
    entrypoint_command: discover
    query_required: false
    desc: Discover modes, observable object patterns, concrete object metadata, and next commands.
    projections:
      default: compact
      allowed: [compact, full]
    argument_patterns:
      - "[<object>:<id>]"
      - "[--projection compact|full]"
    run_cmd: ./xctx discover <domain_id>::<subdomain_id> [<object>:<id>] [--projection compact|full]
```

Parent registration:

```yaml
agent_subdomains:
  <subdomain_id>:
    path: subdomains/<subdomain_id>/subdomain.yaml
    priority: 30
```

## Connector

```yaml
entrypoint:
  file: connector_supervisor.py
  protocol: json_stdout
  timeout_seconds: 30
connector:
  kind: xctx_native_passthrough
  target_entrypoint: <workspace_relative_adapter.py>
  timeout_seconds: 30
```

External command:

```yaml
entrypoint:
  file: connector_supervisor.py
  protocol: json_stdout
  timeout_seconds: 10
connector:
  kind: external_command
  adapter_scope: domain
  timeout_seconds: 5
  max_output_bytes: 20000
  safe_root: <workspace_relative_safe_root>
```

## Action

```yaml
actions:
  <action_id>:
    priority: 20
    entrypoint_command: <adapter-command>
    query_required: true
    mode_kind: search
    desc: Discover <object> records by <query>; use observe for materialized data.
    argument_patterns:
      - "<exact id>"
      - "<descriptive text>"
    examples:
      - query: <example intent>
        run_cmd: ./xctx discover <domain_id>::<subdomain_id> <action_id> <query>
    returns: <adapter_object_type>
    run_cmd: ./xctx discover <domain_id>::<subdomain_id> <action_id> <query>
```

## Domain Affordance

```yaml
actions:
  <action_id>:
    priority: 20
    domain_affordance: true
    domain_action_name: <public_affordance_name>
    entrypoint_command: <adapter-command>
    query_required: true
    desc: <one precise sentence>
    run_cmd: ./xctx discover <domain_id>::<public_affordance_name> <query>
```

Constraints:

```yaml
must_be_unique_within_domain: true
must_not_equal_any_subdomain_id: true
unscoped_equivalent_must_fail: true
```

## List Mode

```yaml
actions:
  list_<objects>:
    priority: 30
    entrypoint_command: list-<objects>
    query_required: false
    mode_kind: list
    desc: List a bounded <objects> discovery index.
    collection:
      result_path: <objects>
      default_limit: 25
      max_limit: 100
      cursor: optional
      cursor_type: opaque
      default: compact
      item_projections: [compact, full]
    argument_patterns:
      - "[--limit N]"
      - "[--cursor CURSOR]"
      - "[--projection compact|full]"
    run_cmd: ./xctx discover <domain_id>::<subdomain_id> list_<objects> [--limit N] [--cursor CURSOR] [--projection compact|full]
```

## CLI Option

```yaml
cli_options:
  - flags: [--<flag-name>]
    dest: <flag_name>
    type: int
    min: 1
    max: 1000
    adapter_arg: --<flag-name>
    mutex_group: <optional_group>
    conflict_message: choose either --<flag-name> or --<other-flag>
    desc: <meaning for this action only>
```

Boolean:

```yaml
cli_options:
  - flags: [--include-archived]
    dest: include_archived
    type: bool
    action: store_true
    adapter_arg: --include-archived
    desc: Include archived records for this action only.
```

## Observe Route

```yaml
agent_routing:
  observe_routes:
    - id: <route_id>
      agent_domain: <domain_id>
      agent_subdomain: <subdomain_id>
      prefixes:
        - "<trusted_prefix>:"
      unprefixed_exact:
        - <OPTIONAL_EXACT_TOKEN>
```
