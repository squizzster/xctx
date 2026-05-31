---
name: xctx-yaml-config
description: Modify xctx YAML domains, subdomains, actions, scoped affordances, command options, routing, statuses, connectors, and repair paths while preserving the generic root protocol boundary. Use for scoped YAML/config edits; use xctx-domain-adapter first for full adapter or live external integration work.
---

# xctx YAML Config

Use this for YAML/config surface changes. Current code, tests, and loaded YAML are source of truth. Do not add legacy aliases, compatibility shims, or root shortcuts unless the user explicitly approves a migration.

For full domain/subdomain adapter creation, use `xctx-domain-adapter` first and this skill for the YAML portion.

## Root Contract

- Visible root commands: `discover`, `observe`, `plan`, `execute`, `audit`, `repair`.
- Hidden extension lane: `other`.
- Removed/refused root commands include `help`, `--help`, `-h`, `status`, `identify`, `doctor`, `write`, and `discovery`.
- Root/version/discover may show generic commands, configured domains, and generic next moves.
- Root surfaces must not show scoped action names, scoped option names, domain identity semantics, adapter vocabulary, or implicit domain selection.

## Boundary Rules

- `libs/xctx` owns generic command policy, parser shape, envelopes, ref shapes, option syntax, audit shape, plan/execute receipts, and repair shape.
- Scoped YAML and adapters own domain nouns, action meaning, list payloads, identity ranking, provider behavior, storage, and observation materialization.
- Domain semantics must not enter generic runtime files.
- Domain affordances live under `subdomain.actions.<action>` with `domain_affordance: true`; public names must be unique within the domain and must not collide with subdomain ids.
- CLI options live under the owning action and use supported primitive types: `str`, `int`, `float`, `bool`.
- Connector config must not use import escape hatches such as `profile`, `module`, `adapter_module`, `python_module`, or `import_path`.
- Connector paths must stay workspace-relative and inside the workspace.

## Edit Checklist

Ask these before every YAML/config change:

- Does this match current code, tests, and loaded YAML?
- Does every domain operation require explicit domain or subdomain scope?
- Is each affordance declared on the action that owns it?
- Are actual errors in `error`, and recovery guidance in `next_moves`?
- Do adapter/audit failures fail closed?
- Are secrets and identities redacted?
- Are stale docs, examples, and hints removed or updated?

Detailed templates live in [references/yaml_templates.md](references/yaml_templates.md). Probe guidance lives in [references/validation_matrix.md](references/validation_matrix.md).

## Validation

Run at minimum:

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 -m pytest -q
```

Also run targeted `./xctx` black-box probes for the changed root/domain/subdomain/action surface, including failure paths and `--max` when detail behavior matters.
