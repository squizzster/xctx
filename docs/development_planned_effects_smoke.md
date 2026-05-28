# Development Planned Effects Smoke

This branch introduces a fast development smoke for planned write effects.
Backward compatibility with the previous read-only-only planning behavior is not
a target for this local development workspace.

The professional boundary is upstream:

- root commands remain `discover`, `observe`, `plan`, `execute`, `audit`, `repair`
- scoped YAML declares planned effects
- `plan` records the master plan JSON, IDs, and commit command
- `discover master_plan:<sha256>` retrieves the written master plan artifact
- `execute --commit` is the only path that invokes the scoped adapter
- a plan can be committed only once; create a new plan for another attempt
- `observe result:<sha256>` reads a protocol-local result handle with heartbeat,
  ready, failed, or expired status

The downstream `guess_the_number_game` adapter is intentionally loose smoke
code. It proves the lifecycle with JSON files under `XCTX_RUNTIME_DIR` or
`.xctx_runtime`, and can be replaced later without changing the upstream hook
points.
