# xctx YAML Templates

These are copy-start templates. Replace ids and descriptions with the user's domain language. Do not ship placeholder semantics.

Core discovery rule:

```text
You discover what you can observe.
```

Discovery should find lawful next affordances and observable object identities,
such as `<object>:<id>`. Observation should materialize that object's full
state or raw/final data. Explicit `--shape full` discovery indexes are
acceptable for now when they are bounded, intentionally requested, and still
serve as discovery/index records rather than raw observed payloads.

Discovery of a concrete observable id may return classification and selection
metadata for that object, such as type, size, modified time, coverage, counts,
schema, or an observe command. It must not return raw contents or final
materialized state. For example, a filesystem domain may discover
`file:README.txt` as `type: ASCII text`, `size: 237`, and an observe command;
the text of the file belongs in `observe`.

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
    desc: Discover modes, observable object shapes, concrete object metadata, and next discovery commands.
    discovery_shapes:
      default_shape: compact
      shapes:
        - compact
        - full
    argument_shapes:
      - "[<object>:<id>]"
      - "[--shape compact|full]"
    examples:
      - query: compact subdomain discovery
        run_cmd: ./xctx discover <domain_id>::<subdomain_id>
      - query: full subdomain discovery
        run_cmd: ./xctx discover <domain_id>::<subdomain_id> --shape full
    run_cmd: ./xctx discover <domain_id>::<subdomain_id> [<object>:<id>] [--shape compact|full]
```

Compact subdomain discovery should show the next things an agent can discover:
discoverable modes, query shapes, observable object id shapes, observe target
shapes, bounded stats, and a full-shape next move. Full subdomain discovery may
include richer mode metadata, examples, samples, schema notes, or bounded
full-index rows, but it still must not return raw observed data.

Compact list/discovery payloads should hide mechanical adapter diagnostics that
do not help choose the next move. For example, omit external command argv arrays
in compact and omit pagination when the complete result is one item
(`total_count == returned_count == 1` with no cursor/next cursor). `--shape full`
should include diagnostic command details and pagination metadata even when
redundant.

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

When the subdomain should route through middleware first, keep the middleware as
the declared entrypoint and put the application or external-command target under
`connector`. For xctx-native adapters this is pass-through:

```yaml
entrypoint:
  file: connector_supervisor.py
  protocol: json_stdout
  compact_flag: --compact
  timeout_seconds: 30
connector:
  kind: xctx_native_passthrough
  target_entrypoint: <domain_adapter.py>
  timeout_seconds: 30
```

`target_entrypoint` must be workspace-relative and must resolve to a file inside
the repository workspace.

For an external command adapter, declare bounded connector controls in the scoped
subdomain YAML and implement reusable domain behavior under
`libs/xctx_connectors/domains/<domain_id>/external_command_adapter.py` or truly
subdomain-specific behavior under
`libs/xctx_connectors/domains/<domain_id>/subdomains/<subdomain_id>/external_command_adapter.py`,
not in `libs/xctx` or generic connector middleware:

```yaml
entrypoint:
  file: connector_supervisor.py
  protocol: json_stdout
  compact_flag: --compact
  timeout_seconds: 10
connector:
  kind: external_command
  adapter_scope: domain  # optional; default is subdomain
  timeout_seconds: 5
  max_output_bytes: 20000
```

Do not declare arbitrary Python module paths or flat connector profiles in YAML.
The middleware derives the adapter module from the already-resolved
`<domain_id>::<subdomain_id>` scope plus optional bounded `adapter_scope`.

The connector should always emit one JSON object for xctx to envelope, including
structured failures. Discovery actions still discover observable object
identities and lawful next moves; observation actions still materialize the
selected object.

Connector metadata returned by adapter-side middleware should include a
`shape_guarantee` object so agents can see the contract being enforced:

```json
{
  "connector": {
    "version": "xctx_connector.v1",
    "kind": "external_command",
    "adapter_ref": "<domain_id>::<subdomain_id>",
    "shape_guarantee": {
      "contract": "always_json_object",
      "xctx_receives": "single_json_object_for_live_data",
      "success_shape": "domain_object",
      "failure_shape": "xctx_connector_error",
      "raw_external_output": "never_returned_unparsed",
      "stdout_stderr": "summarized_in_command_status_when_useful"
    }
  }
}
```

For xctx-native pass-through connectors, successful calls may preserve the
target adapter's native payload unchanged. Normalized pass-through failures
should still include connector metadata with `contract:
pass_through_json_object` and `failure_shape:
xctx_native_passthrough_error`.

## New subdomain action

```yaml
actions:
  <action_id>:
    priority: 20
    entrypoint_command: <adapter-command>
    query_required: true
    desc: Discover <object> records by <query shape>; use observe for materialized <object> data.
    run_cmd: ./xctx discover <domain_id>::<subdomain_id> <action_id> <query-shape>
```

Add interface metadata when the action should teach its own grammar:

```yaml
actions:
  <action_id>:
    priority: 20
    entrypoint_command: <adapter-command>
    query_required: true
    mode_kind: search
    desc: <one precise sentence.>
    argument_shapes:
      - "<exact code>"
      - "<descriptive text>"
    examples:
      - query: <example intent>
        run_cmd: ./xctx discover <domain_id>::<subdomain_id> <action_id> <example-query>
    related_commands:
      - ./xctx discover <domain_id>::<subdomain_id> list_<objects>
    returns: <adapter_object_type>
    run_cmd: ./xctx discover <domain_id>::<subdomain_id> <action_id> <query-shape>
```

This should make both forms useful:

```bash
./xctx discover <domain_id>::<subdomain_id>::<action_id>
./xctx discover <domain_id>::<subdomain_id> <action_id>
```

## New list mode

Use list modes for explicit enumeration so mode names are not interpreted as
free-text searches:

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
      default_shape: compact
      item_shapes:
        - compact
        - full
    argument_shapes:
      - "[--limit N]"
      - "[--cursor CURSOR]"
      - "[--shape compact|full]"
    examples:
      - query: list compact discovery records
        run_cmd: ./xctx discover <domain_id>::<subdomain_id> list_<objects>
      - query: list full discovery records explicitly
        run_cmd: ./xctx discover <domain_id>::<subdomain_id> list_<objects> --shape full
    related_commands:
      - ./xctx discover <domain_id>::<subdomain_id>::<search_action>
      - ./xctx observe <domain_id>::<subdomain_id> <object>:<id>
    returns: <adapter_list_object_type>
    run_cmd: ./xctx discover <domain_id>::<subdomain_id> list_<objects> [--limit N] [--cursor CURSOR] [--shape compact|full]
```

For full list shapes, keep the payload bounded and index-like. Full rows may
include richer discovery metadata, descriptions, examples, and observe commands
when that is useful for black-box exploration. Put raw documents, raw price
series, bodies, line items, CSV exports, or final materialized object state
behind `observe`.

Compact list shape may omit a `pagination` object only when it is genuinely
trivial: one total item, one returned item, no cursor, no next cursor, and no
additional page. Full list shape should always return pagination when the action
is declared as a collection.

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

Do not define universe-level identity fields. Identity semantics belong inside
scoped domain adapters.
