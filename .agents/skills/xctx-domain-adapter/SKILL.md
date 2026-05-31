---
name: xctx-domain-adapter
description: Build or extend xctx agent domains, subdomains, scoped adapters, planned-effect actions, live-data integrations, and domain test suites. Use when Codex is asked to add a new xctx domain/subdomain adapter, integrate an external service or local artifact system into xctx, add domain affordances, add planned acquisitions/commits, or harden an adapter while preserving the generic xctx framework boundary.
---

# xctx Domain Adapter

Use this skill for real domain/subdomain adapter work. Use `xctx-yaml-config` alongside it whenever editing YAML action surfaces, connector settings, scoped affordances, CLI options, statuses, or repair paths.

## Hard Stops

Pause before continuing and tell the user exactly `what`, `why`, and `where` if any of these become necessary:

- A change to `libs/xctx`, `bin/xctx`, `connector_supervisor.py`, generic connector middleware/runtime, parser code, command policy, projection/detail handling, plan/execute internals, or any other xctx framework file.
- A modification to an existing test, unless it is a purely mechanical rename caused by an approved current-contract rename. Explain the behavioral expectation being changed and wait for confirmation.
- A compatibility shim, alias, legacy fallback, or root-level convenience shortcut.
- A domain feature that would require domain nouns or provider behavior in generic xctx runtime code.

Do not "just make it work" by leaking domain semantics into the framework. Domain meaning belongs in scoped YAML and adapter/domain code.

## Boundary Model

Keep the layers separate:

- `libs/xctx`: generic protocol mechanics only: commands, scopes, parser shape, option syntax, envelopes, detail levels, plans, executes, audits, repairs, connector plumbing.
- Scoped YAML: domain/subdomain/action surface: names, priorities, command shapes, options, planned-effect contracts, connector settings, statuses, next commands.
- Adapter/domain code: provider behavior, domain nouns, storage, retries, rate limits, artifact formats, identity ranking, result payloads, live data semantics.

If a framework change is approved, make it generic, cover it with generic tests, and commit it separately from domain work.

## Workflow

1. Discover first. Inspect current `./xctx` surfaces, existing YAML, adapter examples, tests, and recent related commits. Do not edit until the boundary and target surface are clear.
2. Classify the change as domain-only, YAML-only, adapter-only, test-only, or framework-required. Stop on framework-required work.
3. Design the agent surface: discover/list/get-latest helpers, observe refs, planned effects, recommended next moves, lower-level precise controls, and failure next moves.
4. Implement domain semantics only in adapter-owned modules and scoped YAML. Use `examples/<domain>/adapters/...` for passthrough entrypoints and `libs/xctx_live/...` or scoped connector packages for reusable domain code.
5. Build tests as you go. Add focused unit tests for every new parsing, selection, retry, artifact, rate-limit, and payload behavior. Add black-box `./xctx` checks for what agents actually see.
6. Validate with YAML surface checks, compile checks, focused tests, full tests, and black-box probes. Include `--max` where detail-level behavior matters.
7. Split commits by ownership: generic framework first only if explicitly approved, then self-contained domain/subdomain work.

Read [references/domain_adapter_checklist.md](references/domain_adapter_checklist.md) before implementing a non-trivial adapter, planned-effect action, live external integration, artifact store, or domain test matrix.

## Adapter Rules

- Emit exactly one JSON object from adapters. Let xctx wrap it in the protocol envelope.
- Keep discovery bounded: identity, counts, examples, coverage, observable refs, planned effects, and next moves. Use observe for bounded materialization.
- Use planned effects for mutations or external acquisitions: preflight validates, execute commits, observe reads the result handle.
- Return compact, real heartbeats for long work: phase, current action, counts, elapsed time, retry/wait state. Avoid noisy logs and decorative text.
- Use atomic file writes for artifacts. For shared live services, add global rate limiting or locking when multiple agents may run concurrently.
- Respect provider retry signals. For HTTP-style live systems, handle `429`, retryable `5xx`, timeouts, `Retry-After`, exponential backoff, jitter, and a conservative default pace.
- Redact secrets and identities. Payloads may disclose whether an identity exists and which env var supplied it, but not the value.
- Make recommended helper paths obvious while preserving precise lower-level controls as discoverable actions.

## Validation

Minimum local gate for real domain work:

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 -m pytest -q
```

Also run black-box probes through `./xctx` for the exact surface changed. Probe root/domain/subdomain discovery, action discovery, plan preflight, execute/observe when safe, audit, failure next moves, and detail levels.
