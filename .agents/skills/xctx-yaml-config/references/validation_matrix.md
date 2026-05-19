# xctx YAML Validation Matrix

Use this matrix to choose probes after a YAML surface change.

## Always run

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
./xctx --json discover >/tmp/xctx-discover-root.json
./xctx --json audit root >/tmp/xctx-audit-root.json
python3 tests/smoke_protocol.py
```

## Domain or subdomain additions

```bash
./xctx --json discover <domain_id>::
./xctx --json discover <domain_id>::<subdomain_id>
./xctx --json repair offline:<domain_id> || true
./xctx --json repair down_for_maintenance:<domain_id>::<subdomain_id> || true
```

Expected proof:

- online targets discover successfully.
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
```

Expected proof:

- no matches in generic core for product-specific words, flags, route prefixes, adapter commands, or identity fields.
```
