---
name: xctx-yaml-config
description: Safely create, modify, or remove xctx YAML domains, subdomains, scoped domain affordances, actions, command options, routing, statuses, and repair paths while preserving the generic root protocol boundary.
---

# xctx YAML Configuration Skill

Use this skill when changing the `xctx` protocol surface through YAML: domains,
subdomains, scoped domain affordances, action aliases, command arguments,
mode/action discovery, list modes, observe routes, identity search fields,
statuses, audit/repair paths, or entrypoint declarations.

The central rule is strict:

```text
Root/universe/help/version are generic xctx protocol surfaces.
Domain-specific affordances and options appear only after a domain or subdomain
is explicitly in scope.
```

Also strict:

```text
xctx is the clean interface/protocol layer. It defines what can be done and how
configured references are routed. Domain::subdomain::mode specifics define what
those operations mean, and belong in scoped YAML plus adapter code.
```

## Boundary rules

1. Do not add domain/action flags to the root command surface.
2. Do not add universe-level shortcuts that make root infer a domain from a bare
   business noun such as a company name.
3. Do not add ticker, symbol, CIK, receipt, filing, price, or other domain nouns
   to `libs/xctx` generic code.
4. Generic `libs/xctx` code may parse reference shape, such as
   `<domain>::<subdomain>::<mode>`, but it must not interpret mode semantics.
5. Put domain shortcuts on subdomain actions with `domain_affordance: true`.
6. Put CLI options on the most specific owning action with `cli_options`.
7. Put list/discovery/search semantics in scoped subdomain YAML and adapters.
8. Make stale or unscoped commands fail with a useful `next valid move`.
9. Keep read-only, plan, execute, audit, repair, and data-boundary claims honest.
10. If touching generic runtime files, add/keep `## Protocol boundary` comments
    that say the core routes configured refs only; do not include domain nouns
    in those comments.

## Discover/observe data boundary

`discover` finds observable data objects and returns enough identity, scope,
coverage, shape, and next-move metadata to choose what to observe. `observe`
returns the materialized contents or state of a selected object.

A discovered thing may itself be a data object, such as `order:400`,
`form:10-K`, or `market_series:<ticker>:daily`. The discovery payload should
still be an index or pointer to that object, not the raw/final observed data.

Discovery may return identifiers, labels, normalized refs, compact summaries,
coverage ranges, counts, capabilities, schemas, examples, and `observe` command
pointers. Discovery must not return final/raw observed data such as latest
prices, OHLCV bars, filing bodies, full observed records, raw documents, CSV
payloads, or bulk observation datasets.

Domain-specific meaning belongs in scoped YAML and adapter code. Generic
`libs/xctx` code may present and route configured surfaces, but it must not know
what application tokens such as tickers, form codes, order ids, prices, or
filing concepts mean.

Before adding or changing a discovery action:

1. Ask whether the payload is an index/pointer to observable data, or the
   materialized data itself.
2. If it is materialized data, route it through `observe`.
3. Keep compatibility discovery aliases only when they return pointers and next
   moves, not observed data.
4. Add or update tests proving discovery payloads do not leak observation
   fields for that domain pack.

## Change map

| Change | YAML location | Required proof |
|---|---|---|
| Add/remove domain | `universe.yaml` `agent_domains`; `agent_domains/<id>/domain.yaml` | Root lists domain; scoped domain discovery works |
| Add/remove subdomain | domain `agent_subdomains`; subdomain `subdomain.yaml` | Scoped subdomain discovery works or truthful offline/maintenance repair appears |
| Add domain affordance | subdomain `actions.<id>.domain_affordance: true` | `./xctx discover <domain>::<affordance>` works; unscoped equivalent is refused |
| Add mode discovery | subdomain `actions.<id>` metadata such as `argument_shapes`, `examples`, `related_commands`, `returns` | `./xctx discover <domain>::<subdomain>::<action>` and no-query action discovery explain the mode |
| Add subdomain discovery shapes | subdomain `actions.discover.discovery_shapes` and adapter discover handling | Default subdomain discovery is compact; `--shape full` returns richer surface |
| Add list mode | subdomain `actions.<id>.query_required: false`; adapter `entrypoint_command`; optional `collection` contract | list command returns a compact bounded payload instead of being treated as free-text search |
| Add command option | owning action `cli_options` | Option appears only on scoped target surface; wrong target/refusal paths work |
| Change routing | `universe.yaml` `agent_routing` | trusted IDs route correctly; ambiguous IDs do not guess |
| Change identity fields | `universe.yaml` `identity_resolution.query_fields` | generic fields only, typically `name`, `id`, `aliases` |
| Remove anything | all referenced YAML/docs/tests | no stale run_cmd, alias, route, status, doc, or test expectation remains |

## Domain affordance contract

A domain-level convenience command is declared on the real subdomain action that
owns the behavior:

```yaml
actions:
  <action_id>:
    priority: 20
    domain_affordance: true
    domain_action_name: <optional_clearer_domain_name>
    entrypoint_command: <adapter-command>
    aliases: []
    query_required: true
    desc: One precise sentence explaining what this affords.
    run_cmd: ./xctx discover <domain_id>::<domain_action_name> <argument-shape>
```

This makes the scoped command legal:

```bash
./xctx discover <domain_id>::<domain_action_name> <query>
```

and keeps the unscoped command illegal:

```bash
./xctx discover <domain_action_name> <query>
```

## Mode discovery contract

Every callable subdomain action should be discoverable without guessing:

```bash
./xctx discover <domain_id>::<subdomain_id>::<action_id>
./xctx discover <domain_id>::<subdomain_id> <action_id>
```

For `query_required: true`, no-query discovery must return interface metadata,
not call the adapter with an empty query. Include these YAML fields when useful:

```yaml
actions:
  <action_id>:
    query_required: true
    mode_kind: search
    desc: One precise sentence.
    argument_shapes:
      - "<exact code>"
      - "<descriptive text>"
    examples:
      - query: exact code lookup
        run_cmd: ./xctx discover <domain_id>::<subdomain_id> <action_id> <code>
    related_commands:
      - ./xctx discover <domain_id>::<subdomain_id> <related_action>
    returns: <adapter_object_type>
```

For list/enumeration modes, use an explicit action instead of relying on a
free-text fallback. Lists are discovery surfaces, so default rows should be
compact indexes. Full bulk detail requires an explicit shape/observe transition:

```yaml
actions:
  list_<objects>:
    entrypoint_command: list-<objects>
    query_required: false
    mode_kind: list
    collection:
      result_path: <objects>
      default_limit: 25
      max_limit: 100
      cursor: none|optional
      cursor_type: opaque
      default_shape: compact
      item_shapes: [compact, full]
    run_cmd: ./xctx discover <domain_id>::<subdomain_id> list_<objects> [--limit N] [--cursor CURSOR] [--shape compact|full]
```

The adapter must implement the declared `entrypoint_command` and return a
bounded list payload. Do not let mode names become search terms. Do not put
large nested records, per-row run commands, or detailed descriptions into the
default compact list shape; put those in `--shape full`, targeted search, or
observe payloads.

Cursor support is an optional protocol convention, not a root command. xctx may
validate declared `--limit`, `--cursor`, and `--shape` syntax from the action's
`collection` block, but cursor values remain opaque and adapter-owned. Do not
make root-level cursor flags or teach generic xctx code what a cursor means.

## Subdomain discovery shape contract

Dense subdomain discovery should default to a compact directory of what can be
discovered next. Use `actions.discover.discovery_shapes` when a subdomain has a
large surface:

```yaml
actions:
  discover:
    entrypoint_command: discover
    desc: Discover modes, observable object shapes, and next discovery commands.
    discovery_shapes:
      default_shape: compact
      shapes: [compact, full]
    argument_shapes:
      - "[--shape compact|full]"
    examples:
      - query: compact subdomain discovery
        run_cmd: ./xctx discover <domain_id>::<subdomain_id>
      - query: full subdomain discovery
        run_cmd: ./xctx discover <domain_id>::<subdomain_id> --shape full
    run_cmd: ./xctx discover <domain_id>::<subdomain_id> [--shape compact|full]
```

The generic xctx layer may validate the declared shape and switch its own
presentation between a compact action index and full configured actions. The
adapter still owns the meaning of `compact` and `full` for its live discovery
payload.

Compact subdomain discovery should return:

1. Subdomain identity and a short description.
2. Observable object shapes and observe target shapes.
3. Discoverable modes with query shapes and run commands.
4. Bounded stats or coverage summaries.
5. A `--shape full` next move when richer interface detail is available.

Full subdomain discovery may include richer mode metadata, examples, samples,
schema notes, or adapter-owned guidance. It still must obey the discover/observe
data boundary.

## CLI option contract

Add command arguments through `cli_options` on the specific action that owns them:

```yaml
actions:
  observe:
    run_cmd: ./xctx observe <domain_id>::<subdomain_id> <target> [--example-window N]
    cli_options:
      - flags: [--example-window]
        dest: example_window
        type: int
        min: 1
        max: 500
        adapter_arg: --example-window
        mutex_group: optional_group_name
        conflict_message: choose either --example-window or --other-window
        desc: Explain exactly what this option means for this target.
```

Supported `type` values are `str`, `int`, `float`, and `bool`. Use
`adapter_arg` when the adapter argv spelling differs from the public flag or
when you want the adapter boundary explicit.

For every new option, prove all of these paths:

```bash
./xctx --json >/tmp/xctx-universe.json
./xctx --json help >/tmp/xctx-help.json
./xctx --json --version >/tmp/xctx-version.json
./xctx --json discover >/tmp/xctx-root.json
./xctx --json discover <domain_id>::<owning_subdomain> >/tmp/xctx-scoped-surface.json
./xctx --json <command> <valid-target> --new-option <value> >/tmp/xctx-valid.json
./xctx --json <command> <wrong-target> --new-option <value> >/tmp/xctx-wrong-target.json || true
./xctx --json audit root >/tmp/xctx-audit.json
```

The option must be absent from root/universe/help/version output and present only
when the owning subdomain/action is in scope. The wrong-target path should fail
before the wrong adapter is called.

## Routing contract

Observe routing belongs in `universe.yaml`:

```yaml
agent_routing:
  observe_routes:
    - id: <route_id>
      agent_domain: <domain_id>
      agent_subdomain: <subdomain_id>
      prefixes:
        - "<prefix>:"
      unprefixed_exact:
        - OPTIONAL_EXACT_TOKEN
  default_observe_route:
    agent_domain: <domain_id>
    agent_subdomain: <subdomain_id>
```

Use route prefixes for trusted ID families. Use `unprefixed_exact` sparingly for
stable canonical tokens. If an identifier is ambiguous, prefer a discovery flow
over guessing.

## Identity contract

Universe identity fields should stay generic:

```yaml
identity_resolution:
  query_fields: [name, id, aliases]
```

Domain-specific identity semantics belong in the adapter or scoped domain data.

## Add/change/remove workflows

### Add a domain

1. Add `agent_domains/<domain_id>/domain.yaml`.
2. Add a reference under `universe.yaml` `agent_domains`.
3. Choose a truthful `status`.
4. If online, add at least one discoverable subdomain and live proof path.
5. Run validation.

### Add a subdomain

1. Add `agent_domains/<domain_id>/subdomains/<subdomain_id>/subdomain.yaml`.
2. Register it in the parent domain's `agent_subdomains` with a priority.
3. Add aliases only when safe and unambiguous.
4. Add `entrypoint` only when a real adapter exists.
5. Add actions with scoped `run_cmd` strings.
6. Add `domain_affordance: true` only for actions that should be callable from
   `./xctx discover <domain>::<affordance>`.
7. Run discovery and audit probes.

### Add an argument

1. Identify the owning command/action/subdomain.
2. Add `cli_options` to the most specific owner, usually `actions.<action>.cli_options`.
3. Declare `flags`, `dest`, `type`, constraints, `adapter_arg`, and `desc`.
4. Add `mutex_group` and `conflict_message` for mutually exclusive arguments.
5. Confirm the adapter receives the encoded argv and returns JSON.
6. Prove positive, wrong-target, bad-value, and conflict paths.
7. Grep `libs/xctx` for the new public flag and domain-specific nouns. They should not be there.

### Add a mode/action

1. Add the action under the owning subdomain YAML.
2. Decide whether it is interface-only with `query_required: true`, executable
   without a query with `query_required: false`, or a domain affordance.
3. Add `mode_kind`, `argument_shapes`, `examples`, `related_commands`, and
   `returns` when the mode is not self-evident.
4. For list modes, add a `collection` contract and keep the default adapter
   projection compact; use explicit `--shape full` or observe for detailed rows.
5. For dense subdomain discovery, declare `actions.discover.discovery_shapes`
   and implement adapter-owned compact/full discovery payloads.
6. If it executes, implement the adapter command named by `entrypoint_command`.
7. Prove `./xctx discover <domain>::<subdomain>::<action>` works.
8. Prove `./xctx discover <domain>::<subdomain> <action>` works.
9. Prove stale/unscoped equivalents either route to the scoped command or fail
   with a useful `next valid move`.
10. If the mode searches exact codes and broad text, exact code matches should be
   resolved before broad descriptive matching so nearby concepts do not bleed in.

### Modify a surface

1. Preserve IDs unless the user explicitly asks for a breaking rename.
2. Update every `run_cmd`, alias, route, status check, doc, and test expectation.
3. Run before/after discovery to ensure the advertised surface changed as intended.
4. Add or update regression tests for changed refusal behavior.

### Remove a surface

1. Remove the primary YAML declaration.
2. Remove all references: aliases, routes, status checks, docs, and tests.
3. Ensure stale commands fail with a helpful `next valid move`.
4. Run `grep -R` for the removed id.

## Validation sequence

Use the bundled checker first:

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
```

Then run protocol probes from the repo root:

```bash
./xctx --json >/tmp/xctx-universe.json
./xctx --json help >/tmp/xctx-help.json
./xctx --json --version >/tmp/xctx-version.json
./xctx --json discover >/tmp/xctx-discover-root.json
./xctx --json audit root >/tmp/xctx-audit-root.json
python3 tests/smoke_protocol.py
```

Run the pressure suite when the change touches routing, options, identity,
mode discovery, plan/execute, or core protocol behavior:

```bash
python3 tests/protocol_pressure_pro.py
```

Finish with a root leak check for any new domain-specific literal:

```bash
grep -RIn --exclude-dir='__pycache__' '<new-domain-specific-literal>' libs/xctx || true
```

For any runtime/core edit, also run the bundled checker because it scans
selected `libs/xctx`, `xctx`, and `bin/xctx` files for known scoped-domain
tokens:

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
```
