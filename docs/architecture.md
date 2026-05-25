# xctx Production Architecture

This workspace is organized around one rule: `libs/xctx` owns the executable-context protocol, while domain packs own domain meaning.

## Public command contract

The visible command set is intentionally small and fail-closed:

1. `discover`
2. `observe`
3. `plan`
4. `execute`
5. `audit`
6. `repair`

The YAML-defined `other` command remains as a hidden extension lane. It is accepted by the parser only when explicitly invoked, but it is not advertised by help, version, root discovery, or the normal command surface.

`libs/xctx/protocol/command_policy.py` is the single authority for this boundary. It resolves the configured YAML surface into visible and hidden commands, rejects leaked relic commands, and contributes `audit:xctx:command_surface` to root audit.

## Layer responsibilities

### `libs/xctx/process`

Process-facing mechanics only: argv normalization, parser construction, runtime dispatch, signal handling, subprocess capture, and Python-subprocess helpers. This layer must not learn domain vocabulary such as tickers, filing forms, filesystem object types, or stock range semantics.

### `libs/xctx/commands`

Thin command handlers. These modules turn parsed arguments into domain/protocol calls and emit envelopes. They should stay boring: no business logic and no YAML traversal beyond what the domain/protocol libraries expose.

### `libs/xctx/domain`

Protocol-domain composition. The former large `agent_domains.py` module is now split into focused modules:

- `core.py`: domain/subdomain lookup and status helpers.
- `routing.py`: structured reference parsing and route selection.
- `actions.py`: configured action lookup and adapter argument construction.
- `interfaces.py`: action-interface payloads when an affordance requires more input.
- `discovery.py`: root/domain/subdomain/action discovery payloads.
- `observation.py`: read-only observation routing.
- `audit.py`: root/scoped audit payloads and findings.
- `repair.py`: repair guidance for offline/maintenance states.
- `planning.py`: plan and execute receipt behavior.

The old aggregate `agent_domains.py` import facade is intentionally absent. New code imports the focused module it needs.

### `libs/xctx/ports`

Protocol ports into live connector entrypoints. `external_command.py` validates connector supervisor boundaries, constructs sanitized environments, invokes Python entrypoints, and validates that adapters return one JSON object.

### `libs/xctx_connectors`

Connector middleware and demo domain adapters. This is where file-manager and passthrough adapter details belong. Generic xctx code should not absorb this logic.

## Subprocess contract

`libs/xctx/process/capture.py` centralizes subprocess capture. It captures stdout/stderr through temporary files, applies timeouts and process-group cleanup, and returns a `CapturedProcess` value. This avoids duplicated selector loops and avoids reader-thread accumulation in long connector test runs.

`libs/xctx/process/python_subprocess.py` builds fast Python entrypoint argv (`python -S`) and supplies an isolated `PYTHONPATH` that still exposes installed dependencies such as PyYAML. This keeps adapter startup from paying unrelated ambient sitecustomize costs.

## Extension rules

A new domain capability should normally be added in YAML plus an adapter behind `connector_supervisor.py`.

Add generic xctx code only when the concept is protocol-wide, such as command admission, envelope shape, option validation, reference parsing, receipts, audit shape, or repair shape. Domain nouns and provider behavior belong outside `libs/xctx`.

## Release gate checklist

Before release, run:

```bash
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
pytest -q tests/test_command_contract.py tests/test_audit_and_options.py tests/test_protocol_surface_hardening.py tests/test_connector_runtime.py
python3 tests/protocol_observe_discover_boundary.py
pytest -q tests/test_observe_discover_boundary.py
```

The broad smoke/pressure suites are intentionally split into callable cases so expensive connector subprocess paths can be isolated when a CI/runtime environment is sensitive to long in-process subprocess matrices.
