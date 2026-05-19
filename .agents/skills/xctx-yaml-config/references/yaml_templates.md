# xctx YAML Templates

These are copy-start templates. Replace ids and descriptions with the user's domain language. Do not ship placeholder semantics.

## New domain

```yaml
id: <domain_id>
kind: agent_domain
status: offline
health: unavailable_until_adapter_is_bound
basic_description: <one sentence>
full_description: >-
  <truthful longer explanation of what exists, what does not exist, and why an agent should enter this domain.>
canonical_identity_policy:
  trusted_id_scope: <domain_id>
  <object>_id_format: <prefix>:<shape>
agent_subdomains: {}
repair_path:
  run_cmd: ./xctx repair offline:<domain_id>
  desc: Bring the domain online by adding subdomain YAML, adapter entrypoints, data paths, and validation probes.
```

Then add to `yaml_dynamic_config/universe.yaml`:

```yaml
agent_domains:
  - id: <domain_id>
    path: agent_domains/<domain_id>/domain.yaml
```

## New subdomain

Parent domain entry:

```yaml
agent_subdomains:
  <subdomain_id>:
    path: subdomains/<subdomain_id>/subdomain.yaml
    priority: 30
```

Subdomain file:

```yaml
id: <subdomain_id>
kind: agent_subdomain
aliases: []
status: offline
basic_description: <one sentence>
full_description: >-
  <truthful capability and limitation statement.>
data_description: >-
  <where the data comes from and whether it is live/read-only/bundled.>
repair_path:
  run_cmd: ./xctx repair offline:<domain_id>::<subdomain_id>
  desc: Add or enable the adapter and validation proof for this subdomain.
actions:
  discover:
    priority: 10
    entrypoint_command: discover
    desc: Explain the subdomain surface and constraints.
    run_cmd: ./xctx discover <domain_id>::<subdomain_id>
```

When there is a real adapter:

```yaml
entrypoint:
  file: <adapter_file.py>
  protocol: json_stdout
  compact_flag: --compact
  timeout_seconds: 30
data:
  storage_engine: <yaml|sqlite|mixed_yaml_sqlite|external>
  path: <relative/path/if/applicable>
  read_only: true
```

## New subdomain action

```yaml
actions:
  <action_id>:
    priority: 20
    entrypoint_command: <adapter-command>
    aliases:
      - <safe_alias>
    query_required: true
    desc: <one sentence explaining the search/observation affordance.>
    run_cmd: ./xctx discover <domain_id>::<subdomain_id> <action_id> <query-shape>
```

## New scoped domain affordance

Use this when a subdomain action should also be callable as
`./xctx discover <domain_id>::<domain_action_name> <query>`:

```yaml
actions:
  <action_id>:
    priority: 20
    domain_affordance: true
    domain_action_name: <optional_public_domain_action_name>
    entrypoint_command: <adapter-command>
    aliases:
      - <optional_alias>
    query_required: true
    desc: <one precise sentence.>
    run_cmd: ./xctx discover <domain_id>::<domain_action_name> <argument-shape>
```

## New CLI option

```yaml
cli_options:
  - flags: [--<flag-name>]
    dest: <flag_name>
    type: int
    min: 1
    max: 1000
    adapter_arg: --<flag-name>
    mutex_group: <optional_mutex_group>
    conflict_message: choose either --<flag-name> or --<other-flag>
    desc: <what the option means for this action only.>
```

For boolean options:

```yaml
cli_options:
  - flags: [--include-archived]
    dest: include_archived
    type: bool
    action: store_true
    adapter_arg: --include-archived
    desc: Include archived records in this action's result set.
```

## New observe route

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

## Identity fields

```yaml
identity_resolution:
  query_fields:
    - name
    - id
    - aliases
```
