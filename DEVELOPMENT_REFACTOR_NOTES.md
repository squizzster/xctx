# xctx v4.2 Pro Refactor Notes

This development drop keeps the v4.2 protocol identity while hardening the implementation for extension.

This workspace is still live local protocol development, not a deployed public
compatibility surface. Current code, tests, and loaded YAML take precedence over
stale local skills or reports.

## Highlights

- Split the large agent-domain module into focused discovery, observation, audit, repair, planning, routing, action, and core modules.
- Removed the old `xctx.domain.agent_domains` import facade; use the focused domain modules directly.
- Added a fail-closed command-surface policy: six visible commands plus the hidden `other` extension lane.
- Added a root audit check for command-surface drift and YAML leakage.
- Removed the old `discover --name` parser relic instead of preserving a stock-specific root shortcut.
- Strengthened `discover --id` and `observe --id` conflict validation before routing.
- Centralized subprocess capture and Python subprocess startup helpers.
- Reduced connector startup overhead by using isolated `python -S` entrypoints for supervised adapters.
- Added typed package markers and package-data metadata.
- Added protocol-surface hardening tests and updated local-gate expectations.
- Kept `error` as the actual error text and moved runnable recovery commands to structured `next_moves`.
- Centralized protocol-facing redaction and made audit/live-adapter failures fail closed.

## Development posture

`libs/xctx` is now easier to read as a protocol engine. Domain-pack semantics remain in YAML and adapters. The command surface is audited, parser relics are refused, and process/connector behavior is reusable instead of copied across modules.

## Validation in this workspace

The current default validation path is full-suite by default:

```bash
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 -m pytest -q --durations=30
```

Targeted pytest marker/file runs remain useful for debugging a failing area, but
they are not a substitute for the full default suite.
