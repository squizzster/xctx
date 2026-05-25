# xctx v4.2 Pro Refactor Notes

This release keeps the v4.2 protocol identity while hardening the implementation for release-quality extension.

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
- Added protocol-surface hardening tests and updated release-gate expectations.

## Production posture

`libs/xctx` is now easier to read as a protocol engine. Domain-pack semantics remain in YAML and adapters. The command surface is audited, parser relics are refused, and process/connector behavior is reusable instead of copied across modules.

## Validation in this package

Validated locally in this artifact:

```bash
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
pytest -q tests/test_command_contract.py tests/test_audit_and_options.py tests/test_protocol_surface_hardening.py tests/test_connector_runtime.py
python3 tests/protocol_observe_discover_boundary.py
pytest -q tests/test_observe_discover_boundary.py
```

The broad smoke and pressure matrices are present, but they exercise many nested subprocesses and may need to be run case-by-case or under CI process isolation in constrained sandbox runtimes.
