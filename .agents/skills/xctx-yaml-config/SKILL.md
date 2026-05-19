---
name: xctx-yaml-config
description: Safely create, modify, or remove xctx YAML domains, subdomains, scoped domain affordances, actions, command options, routing, statuses, and repair paths while preserving the generic root protocol boundary.
---

# xctx YAML Configuration Skill

Use this skill when changing the `xctx` protocol surface through YAML: domains,
subdomains, scoped domain affordances, action aliases, command arguments,
observe routes, identity search fields, statuses, audit/repair paths, or
entrypoint declarations.

The central rule is strict:

```text
Root/universe/help/version are generic xctx protocol surfaces.
Domain-specific affordances and options appear only after a domain or subdomain
is explicitly in scope.
```

## Boundary rules

1. Do not add domain/action flags to the root command surface.
2. Do not add universe-level shortcuts that make root infer a domain from a bare
   business noun such as a company name.
3. Do not add ticker, symbol, CIK, receipt, filing, price, or other domain nouns
   to `libs/xctx` generic code.
4. Put domain shortcuts on subdomain actions with `domain_affordance: true`.
5. Put CLI options on the most specific owning action with `cli_options`.
6. Make stale or unscoped commands fail with a useful `next valid move`.
7. Keep read-only, plan, execute, audit, repair, and data-boundary claims honest.

## Change map

| Change | YAML location | Required proof |
|---|---|---|
| Add/remove domain | `universe.yaml` `agent_domains`; `agent_domains/<id>/domain.yaml` | Root lists domain; scoped domain discovery works |
| Add/remove subdomain | domain `agent_subdomains`; subdomain `subdomain.yaml` | Scoped subdomain discovery works or truthful offline/maintenance repair appears |
| Add domain affordance | subdomain `actions.<id>.domain_affordance: true` | `./xctx discover <domain>::<affordance>` works; unscoped equivalent is refused |
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
plan/execute, or core protocol behavior:

```bash
python3 tests/protocol_pressure_pro.py
```

Finish with a root leak check for any new domain-specific literal:

```bash
grep -RIn --exclude-dir='__pycache__' '<new-domain-specific-literal>' libs/xctx || true
```
