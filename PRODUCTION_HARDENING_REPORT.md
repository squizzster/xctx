# xctx 4.2.3 production hardening report

This package keeps the public protocol identity at **xctx v4.2** and hardens the implementation into a cleaner release-oriented Python workspace. The visible command surface remains exactly:

1. `discover`
2. `observe`
3. `plan`
4. `execute`
5. `audit`
6. `repair`

The YAML-defined `other` lane remains accepted as the hidden extension path. It is intentionally not advertised by help, version, root discovery, or normal guidance.

## Executive summary

The main hardening pass moved xctx from “working modular demo” toward a stricter protocol core:

- The command surface now has a single fail-closed policy module.
- Plan and execute now share a typed argument contract instead of handler-local shape assumptions.
- Plans now bind to a deterministic snapshot of the loaded protocol/config surface.
- Execute now rejects stale plans, ambiguous short receipts, missing commits, and multi-token execution requests.
- The plan ledger now validates record shape before write and after read.
- Repair now validates that audit finding IDs still match the target’s current state.
- Loaded YAML now receives structural validation instead of relying on later incidental failures.
- CLI option declarations now normalize numeric bounds and typed choices safely.
- Root audit now exposes a deterministic config fingerprint for evidence and stale-plan debugging.
- Tests now cover the added enforcement points and avoid brittle fixture byte-size constants.

## Code-quality restructuring performed

### New reusable core modules

`libs/xctx/domain/execution_contract.py`

Owns generic xctx plan/execute shape parsing:

- `PlanRequest`
- `ExecuteRequest`
- `parse_plan_request()`
- `parse_execute_request()`
- usage strings for protocol guidance

This keeps the rehearsal/commit boundary out of command handlers and makes future execution backends easier to add without duplicating argument rules.

`libs/xctx/store/fingerprints.py`

Owns deterministic fingerprints for the loaded operating surface:

- config file snapshots
- protocol version binding
- canonical sha256 payloads
- lightweight `config_fingerprint()` helper

This is what lets execute prove that a recorded plan was created against the same loaded xctx surface being used now.

`libs/xctx/config/validation.py`

Owns structural validation for loaded YAML:

- duplicate domain IDs
- domain/subdomain ID alignment
- known availability states
- mapping/list shape checks
- online action-map invariants

This makes bad config fail near the loader instead of much later in routing, discovery, audit, or adapter calls.

### Core modules hardened

`libs/xctx/domain/planning.py`

- Plans now record `operation_token`, `target`, `planner_context`, `receipt_sha256`, `receipt_sha5`, and canonical `plan_id`.
- Receipts are deterministic over the planned operation and the current protocol/config fingerprint.
- Execute now accepts exactly one plan token.
- Execute now requires explicit `--commit`.
- Execute now refuses stale plans when the loaded config fingerprint differs from the recorded plan context.
- Execute still performs no domain mutation in this read-only bundled workspace; it validates the boundary and emits evidence.

`libs/xctx/store/plans.py`

- Added canonical `plan:sha256:<digest>` ID handling.
- Added ledger record validation for required keys and digest consistency.
- Validates 64-character lowercase hex receipts.
- Preserves short 5-character receipt support only when the prefix resolves uniquely.
- Returns safe refusal states for invalid, missing, unknown, ambiguous, and corrupt records.

`libs/xctx/protocol/command_policy.py`

- Centralized the visible/hidden command contract.
- Fails closed on leaked relic commands in YAML command groups or command maps.
- Detects duplicate main/extension command entries.
- Keeps `other` hidden but accepted.
- Keeps command guidance limited to visible core commands.

`libs/xctx/domain/repair.py`

- Repair finding IDs now include and validate their status prefix.
- A stale finding such as `offline:domain::subdomain` is refused when the target is now `down_for_maintenance`.
- Repair payloads preserve `finding_id` when invoked from an audit finding.
- Domain vs subdomain repair levels remain explicit.

`libs/xctx/config/loader.py`

- Resolves workspace paths with containment checks.
- Prevents YAML include paths from escaping the workspace root.
- Validates universe shape before loading included packs.
- Validates the fully loaded store before use.

`libs/xctx/protocol/option_specs.py`

- CLI option bounds are normalized and validated at option-declaration time.
- Integer and float choices are coerced to their typed values, so argparse comparisons do not silently mismatch.
- Invalid numeric bounds now surface as xctx guidance instead of raw Python exceptions.

`libs/xctx/protocol/option_encoding.py`

- Target-scoped option validation now uses normalized numeric bounds safely.
- Unsupported target options still fail only after a concrete target/action is known.

`libs/xctx/domain/routing.py`

- Malformed observe routes without both `agent_domain` and `agent_subdomain` are ignored rather than producing accidental stringified `None` routes.

`libs/xctx/domain/audit.py`

- Root/domain/subdomain audit now includes `audit:xctx:config_fingerprint`.
- The fingerprint check provides evidence for plan binding and release diagnostics.

## Relic and release-polish cleanup

- Removed unused internal helpers discovered during the scan:
  - `_group_names()` in command policy.
  - `_collection_shapes()` in action utilities.
  - `_row_dict()` in filings demo helpers.
- Reworded remaining demo/reference text away from “proof-of-concept” language.
- Reworded the file-manager fixture away from “legacy connector” language.
- Updated package metadata to `4.2.3` while preserving protocol identity `v4.2`.
- Removed brittle test assumptions around fixture byte length by deriving expected size from the fixture itself.

## Test coverage added or strengthened

New or strengthened tests cover:

- execute refuses multiple plan identifiers;
- execute refuses stale config-bound plans;
- repair refuses stale audit-finding prefixes;
- command-surface audit detects duplicate command entries;
- root audit emits a deterministic config fingerprint;
- config validation rejects domain/subdomain ID mismatches;
- option config audit rejects invalid numeric bounds;
- integer CLI choices are parsed as integers rather than strings;
- integration tests derive fixture sizes from the file on disk rather than hardcoding byte counts.

The default release-safe suite now reports:

```text
36 passed, 1 skipped, 41 deselected
```

The focused integration suites validated in this package report:

```text
tests/test_observe_discover_boundary.py: 4 passed
tests/test_protocol_connector_supervisor.py: 14 passed
tests/test_smoke_protocol.py: 10 passed
tests/test_protocol_pressure_pro.py: 13 passed
tests/test_framework_release_gate.py::test_package_install_entrypoint_smoke: 1 passed
```

## Production readiness status

### Must remain enforced

These are now treated as hard protocol rules:

- No visible commands beyond `discover`, `observe`, `plan`, `execute`, `audit`, and `repair`.
- `other` is hidden extension only.
- No stale root commands such as `status`, `identify`, `doctor`, `write`, or `discovery`.
- No execute without a recorded plan token.
- No execute with multiple plan tokens.
- No execute without `--commit`.
- No execute of a plan recorded against a different loaded config fingerprint.
- No repair based on a stale finding prefix.
- No config include paths outside the workspace.
- No loaded domain/subdomain ID drift.
- No malformed numeric option bounds.

### Should be next before a public release announcement

These are intentionally not faked in the reference package but are the next professional release steps:

- Add CI jobs for Python 3.10 through the newest supported Python.
- Add ruff/pyright or ruff/mypy gates once style/type policy is finalized.
- Add golden transcript snapshots for the six core command flows.
- Add fuzz/property tests around target parsing, receipt prefixes, and option declarations.
- Add a formal JSON Schema or Pydantic model for YAML pack authoring if third-party packs are expected.
- Keep tests that fail if removed import facades such as `xctx.domain.agent_domains` or `xctx.protocol.options` reappear.
- Add signed release artifacts if the plan ledger becomes a trust boundary across machines.
- Add independent evidence reconciliation for any future mutation-capable adapters.

### Can stay as reference/demo scope

These do not block the xctx framework release:

- The bundled market-data and filings adapters remain read-only reference adapters.
- The file-manager connector remains a middleware demonstration.
- The `other` extension lane remains hidden and intentionally generic.
- The execute path remains read-only/no-op until a real mutation-capable domain pack is added.

## Release thesis

The core framework is now easier to extend because xctx-specific concerns have clearer homes:

- command admission lives in command policy;
- argument shape lives in execution contracts;
- loaded YAML integrity lives in config validation;
- plan binding lives in the plan ledger plus fingerprints;
- repair validity lives in repair target resolution;
- scoped option parsing lives in option specs/encoding;
- domain semantics stay in YAML packs and adapters.

That separation is the main production improvement. The framework is no longer asking handlers, tests, or adapter code to remember the protocol. The protocol is executable in the structure of the code.
