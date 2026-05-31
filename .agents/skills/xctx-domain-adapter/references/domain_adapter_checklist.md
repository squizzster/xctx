# Domain Adapter Checklist

Use this reference after loading `xctx-domain-adapter` for substantial domain/subdomain adapter work.

## 1. Discovery Before Edits

Run enough discovery to understand the current contract:

```bash
git status --short --branch
./xctx discover
./xctx --max audit root
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
```

Also inspect:

- `yaml_dynamic_config/universe.yaml`
- target `yaml_dynamic_config/agent_domains/<domain>/domain.yaml`
- target or example `subdomain.yaml`
- matching adapters under `examples/<domain>/adapters/`
- reusable domain code under `libs/xctx_live/`
- connector packages under `libs/xctx_connectors/domains/`
- tests that already cover the target command surface

Summarize the boundary before editing. If framework files look necessary, stop and ask the user.

## 2. Ownership Split

Classify every touched file:

- Framework: `libs/xctx/**`, `bin/xctx`, `xctx`, `connector_supervisor.py`, generic `libs/xctx_connectors/middleware.py`, generic `libs/xctx_connectors/runtime.py`.
- Domain config: `yaml_dynamic_config/agent_domains/<domain>/**`.
- Domain adapter entrypoint: `examples/<domain>/adapters/*.py`.
- Domain library: `libs/xctx_live/<domain_or_subdomain>*.py`.
- Connector adapter package: `libs/xctx_connectors/domains/<domain>/**`.
- Tests: focused domain tests, generic framework tests, black-box protocol tests, live opt-in tests.

Framework files require user confirmation before integration continues. If approved, keep the change generic, test it with generic tests, and commit it separately.

## 3. Surface Design

A useful subdomain normally exposes:

- `discover`: current status, storage/data boundary, coverage, examples, observable patterns, planned effects, and next moves.
- List actions: bounded local/catalog inventories with `--limit`, `--cursor`, filters, and stable `observe_cmd` refs.
- Helper actions: `get_latest`, `super_pack`, `sync`, `import`, or similar domain-owned shortcuts when the domain is complex.
- Lower-level actions: precise controls for agents that need a specific object, form, artifact kind, provider, or mode.
- `observe`: status and bounded materialization by explicit refs, never implicit root routing.
- `audit`: checks that fail closed for adapter errors and expose warnings for missing optional capability.

For high-level helpers, make the recommended path first in `next_moves`, but keep lower-level controls visible in `planned_effects`, `discoverable_modes`, `related_commands`, or action lists.

## 4. YAML Rules

Use `xctx-yaml-config` for YAML edits. Confirm:

- Domain and subdomain ids are explicit and import-safe.
- Online subdomains have real entrypoints.
- `xctx_native_passthrough` uses `target_entrypoint`; `external_command` uses the scoped connector package layout.
- No connector config uses forbidden import escape hatches such as `module`, `adapter_module`, `python_module`, or `profile`.
- Domain affordances live under `subdomain.actions.<action>` with `domain_affordance: true`.
- Public affordance names do not collide with subdomain ids and are not exposed at root.
- CLI options live under the owning action, have supported primitive types, and target only the relevant command.
- Planned effects declare preflight and commit commands, heartbeats, write/reversal/repair semantics, and useful descriptions.
- `timeout_seconds` and `max_output_bytes` fit the real adapter workload without hiding hangs.

## 5. Adapter Entrypoint Pattern

For `xctx_native_passthrough` adapters:

- Locate workspace root safely.
- Add `libs` to `sys.path`.
- Parse only the scoped commands declared in YAML.
- Dispatch to domain library functions.
- Convert usage errors to JSON with `usage_error`.
- Emit one JSON object with `emit_json`.
- Keep comments minimal but mark the domain-pack boundary.

Adapter entrypoints should be thin. Put real behavior in reusable domain-owned modules.

## 6. Planned Effects

Use planned effects for anything that writes local state, downloads external data, or creates artifacts.

Preflight should:

- Parse and validate required options.
- Validate local fixture/source roots.
- Check required dependencies and identities.
- Refuse before ledger mutation when the operation cannot run.
- Return structured `next_moves` on failure.

Commit should:

- Read `--xctx-plan-id`, `--xctx-commit-id`, and `--xctx-result-id`.
- Write artifacts under runtime-local domain paths.
- Update domain-owned registries atomically.
- Return `result_id`, object type, status, summaries, artifact/list commands, and follow-up observe/list commands.

Never execute a planned effect directly through a hidden shortcut.

## 7. State, Artifacts, and External Systems

For runtime state:

- Respect `XCTX_RUNTIME_DIR`; otherwise use `.xctx_runtime`.
- Keep state under a domain/subdomain-specific path.
- Use SQLite for shared local registries when multiple agents may read/write.
- Use file locks or SQLite-backed locks for global external-provider pacing.
- Write files atomically via temp file plus replace.
- Store metadata sufficient for discovery and observation: created time, checked time, source, artifact path, size, checksum, local state.

For external services:

- Set conservative defaults.
- Respect provider identities and redaction.
- Handle retryable failures with bounded exponential backoff and jitter.
- Honor `Retry-After` when available.
- Treat timeouts as retryable only within a bounded policy.
- Emit compact heartbeat events showing wait/retry state and progress counts.

## 8. Testing Expectations

Add tests as the implementation grows:

- Unit tests for parsing and validation.
- Unit tests for selection/ranking logic.
- Unit tests for artifact generation and section/extraction behavior.
- Unit tests for atomic writes and registry indexing.
- Unit tests for rate limit locking and retry delay behavior.
- Fixture-backed planned-effect tests for plan, execute, observe, and list flows.
- Black-box `./xctx` tests for public discovery, action discoverability, next moves, `--max`, errors, and scoped affordances.
- Opt-in live matrix tests for real provider variability; keep them skipped unless explicitly enabled.

If an existing test must change, pause. Tell the user which test, what behavior it asserts today, why it must change, and what new contract would replace it.

## 9. Black-Box Probe Matrix

Use fresh runtime dirs where possible:

```bash
runtime_dir="$(mktemp -d)"
XCTX_RUNTIME_DIR="$runtime_dir" ./xctx discover <domain>::
XCTX_RUNTIME_DIR="$runtime_dir" ./xctx discover <domain>::<subdomain>
XCTX_RUNTIME_DIR="$runtime_dir" ./xctx --max discover <domain>::<subdomain>
XCTX_RUNTIME_DIR="$runtime_dir" ./xctx discover <domain>::<subdomain>::<action> <args>
XCTX_RUNTIME_DIR="$runtime_dir" ./xctx plan <domain>::<subdomain>::<planned_action> <args>
XCTX_RUNTIME_DIR="$runtime_dir" ./xctx audit <domain>::<subdomain>
```

Assert:

- The command succeeds or fails for the expected reason.
- Payload object types are stable.
- Recommended next moves are coherent.
- Lower-level controls remain discoverable.
- `--max` adds detail without changing domain semantics.
- Wrong scopes and bare root affordances fail closed.
- Errors include concrete failure text and recovery next moves.

## 10. Commit Discipline

Before committing:

```bash
git diff --check
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 -m pytest -q
```

Split commits:

- Generic framework commit only after user approval, with generic tests and no domain semantics.
- Domain/subdomain commit for YAML, adapters, domain libraries, fixtures, and domain tests.
- Avoid mixing formatting churn, unrelated cleanup, and stale docs rewrites.

In final reporting, include the commit split, validation commands, black-box probes, and any skipped live tests.
