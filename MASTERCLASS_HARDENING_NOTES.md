# xctx 4.2.3 masterclass hardening notes

This drop hardens the xctx framework surface around the six visible core commands:
`discover`, `observe`, `plan`, `execute`, `audit`, and `repair`. The `other` extension lane remains accepted by the parser but hidden from the visible agent-domain command surface.

This workspace is still live local protocol development, not a deployed public
compatibility surface. Stale docs, skills, aliases, and compatibility remnants
should be corrected against the current code, tests, and YAML.


## 4.2.3 hardening additions

- Added deterministic loaded-config fingerprints and exposed them through root audit.
- Bound plan receipts to the current protocol/config fingerprint and refused stale plans at execute time.
- Centralized plan/execute shape validation in `xctx.domain.execution_contract`.
- Strengthened the plan ledger with canonical IDs and record validation on write/read.
- Made repair finding IDs state-aware so stale audit findings are refused.
- Added loader-level config validation for domain/subdomain identity and availability state invariants.
- Hardened configured CLI options by normalizing typed choices and validating numeric bounds.
- Removed unused internal helper relics and cleaned remaining stale wording.
- Added development contract tests for stale plans, stale findings, config fingerprints, option bounds, and config ID validation.

## Framework changes

- Split the large protocol option module into focused layers:
  - `xctx.protocol.option_specs` for YAML option declaration parsing and command/target matching.
  - `xctx.protocol.option_encoding` for target-scoped validation and adapter argv encoding.
  - `xctx.protocol.option_surface` for serializable option surfaces and audit checks.
  - The old `xctx.protocol.options` import facade is intentionally removed.
- Added shared subprocess boundary modules:
  - `xctx.process.env` centralizes sanitized child-process environments.
  - `xctx.process.limits` centralizes timeout and output-capture validation.
- Hardened external command and connector runtime paths to reuse the shared env/limit contract.
- Strengthened plan ledger integrity: receipt shape validation, atomic writes, clean short/full receipt resolution, and safer corrupted-ledger handling.
- Reworked repair target resolution into a typed repair target boundary, with precise `agent_domain` vs `agent_subdomain` domain levels.
- Made protocol command-template formatting tolerant: known placeholders render, unknown placeholders remain visible instead of crashing discovery/observation.
- Shell-quoted recorded command lines with `shlex.join`, so evidence remains faithful when arguments contain spaces.
- Tightened process-capture semantics so missing return codes are never treated as successful execution.
- Removed visible prototype wording from the protocol/docs/reference pack in favor of hardened reference-implementation language.
- Kept protocol errors cleanly separated from structured `next_moves`.
- Centralized protocol-facing redaction in `xctx.process.redaction`.
- Made live audit payload normalization fail closed and adapter failures become audit checks.

## Test/local-gate changes

- Added `tests/test_masterclass_regressions.py` covering the refactor contract, repair domain level, safe formatting, plan receipt validation, output limit validation, process-capture correctness, and command-line evidence quoting.
- Removed default pytest marker filtering. `python3 -m pytest -q` now means the full collected test suite; targeted marker/file runs are for debugging subsets.
- Kept the package-install smoke available behind `XCTX_RUN_PACKAGE_INSTALL_SMOKE=1` because repeated pip/venv subprocesses are sandbox-sensitive.
- Hardened local-gate process cleanup to avoid killing the current pytest/container command group when test command lines contain gate sentinel strings.
