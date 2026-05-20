# xctx YAML Validation Matrix

Use this matrix to choose probes after a YAML surface change.

## Always run

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
./xctx --json discover >/tmp/xctx-discover-root.json
./xctx --json audit root >/tmp/xctx-audit-root.json
python3 tests/smoke_protocol.py
```

Expected proof:

- root discovery exposes configured agent domains only.
- root audit exposes protocol/config/availability checks only.
- root audit does not bubble scoped adapter health checks such as fixture
  tickers, database counts, filing tables, legacy command probes, or middleware
  profile details.

## Domain or subdomain additions

```bash
./xctx --json discover <domain_id>::
./xctx --json discover <domain_id>::<subdomain_id>
./xctx --json audit <domain_id>::<subdomain_id>
./xctx --json repair offline:<domain_id> || true
./xctx --json repair down_for_maintenance:<domain_id>::<subdomain_id> || true
```

Expected proof:

- online targets discover successfully.
- scoped audit returns adapter-owned checks when the subdomain declares an
  online entrypoint.
- offline targets advertise repair command.
- maintenance targets are terminal and do not fake repair.

## Scoped domain affordance additions

```bash
./xctx --json discover <domain_id>::<domain_action_id> <query>
./xctx --json discover <domain_action_id> <query> || true
```

Expected proof:

- scoped action works.
- unscoped action is refused with a next valid move.

## Mode/action discovery additions

```bash
./xctx --json discover <domain_id>::<subdomain_id>::<action_id>
./xctx --json discover <domain_id>::<subdomain_id> <action_id>
./xctx --json discover <domain_id>::<subdomain_id> <action_id> <query>
./xctx --json discover <domain_id>::<subdomain_id> <object>:<known_id>
```

Expected proof:

- no-query action discovery returns interface metadata when `query_required: true`.
- executable no-query actions return their declared list/discovery payload when `query_required: false`.
- query execution calls the declared adapter command.
- concrete object discovery returns classification/metadata and observe commands, not raw contents.
- action metadata is visible only after domain/subdomain scope is selected.

## List mode additions

```bash
./xctx --json discover <domain_id>::<subdomain_id> list_<objects>
./xctx --json discover <domain_id>::<subdomain_id> list_<objects> --limit 2
./xctx --json discover <domain_id>::<subdomain_id> list_<objects> --limit 1 --shape full
```

Expected proof:

- list mode returns a bounded list object.
- the literal list mode name is not treated as a free-text search query.
- bad list arguments fail with scoped guidance.
- compact omits low-value mechanical diagnostics where allowed.
- full preserves declared collection pagination and diagnostic command details.

## CLI option additions

```bash
./xctx --json >/tmp/xctx-universe.json
./xctx --json help >/tmp/xctx-help.json
./xctx --json --version >/tmp/xctx-version.json
./xctx --json discover >/tmp/xctx-root.json
./xctx --json discover <domain_id>::<owning_subdomain> | python3 -m json.tool | grep -A20 'configured_options'
./xctx --json <command> <owning-target> --<new-flag> <value>
./xctx --json <command> <wrong-target> --<new-flag> <value> || true
./xctx --json <command> <owning-target> --<new-flag> <bad-value> || true
```

If the option has a mutex group:

```bash
./xctx --json <command> <owning-target> --<new-flag> <value> --<conflicting-flag> <value> || true
```

Expected proof:

- configured option is absent from root/universe/help/version and advertised only on the owning scoped target surface.
- valid target succeeds.
- wrong target fails before adapter call.
- bounds/conflicts fail with useful `next valid move` messages.

## Routing changes

```bash
./xctx --json observe <new-prefixed-id>
./xctx --json observe <ambiguous-or-wrong-id> || true
```

Expected proof:

- trusted prefixes route to the intended subdomain.
- ambiguous or wrong identifiers do not silently produce unrelated facts.

## Middleware connector additions

```bash
./xctx --json discover <domain_id>::<subdomain_id>
./xctx --json discover <domain_id>::<subdomain_id> <list_mode> --limit 2
./xctx --json observe <trusted_prefix>:<known_id>
./xctx --json observe <trusted_prefix>:<invalid_or_blocked_id>
python3 tests/protocol_legacy_connector.py
```

Expected proof:

- xctx routes through the configured middleware entrypoint with no generic core changes.
- xctx-native pass-through targets retain their existing payload shapes.
- legacy failures return a JSON object with `found: false` or equivalent status instead of raw stderr/stdout.
- discovery returns object identities and observe commands, not raw observed data.
- connector metadata includes `shape_guarantee` when middleware returns connector metadata.
- `shape_guarantee.xctx_receives` is `single_json_object_for_live_data`.
- legacy connectors declare `contract: always_json_object`; normalized pass-through failures declare `contract: pass_through_json_object`.
- core leak checks find no connector profile terms or legacy command semantics in `libs/xctx`.

## Removal changes

```bash
grep -RIn '<removed_id_or_flag>' yaml_dynamic_config docs tests README.md || true
./xctx --json discover <old-command-shape> || true
```

Expected proof:

- no stale YAML/docs/tests references unless intentionally retained for compatibility.
- old command shape fails with guidance.

## Core leak check

```bash
grep -RIn --exclude-dir='__pycache__' '<new-domain-specific-literal>' libs/xctx || true
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
```

Expected proof:

- no matches in generic core for product-specific words, flags, route prefixes, adapter commands, or identity fields.
- the bundled checker reports `error_count: 0`; it also checks known scoped-token leakage in selected core files.
```
