# Validation Summary

This workspace is in live local development. It is not deployed as a public
compatibility target, so validation follows the current code, tests, and loaded
YAML contract rather than older release notes or stale skill guidance.

## Canonical Local Gate

`pytest` means the full collected suite by default:

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 -m pytest -q --durations=30
```

Expected current pytest result:

```text
97 passed, 1 skipped
```

`make test` runs the full pytest suite. `make release-test` runs the YAML
surface checker, compileall, and the same full pytest suite. Explicit marker or
file selections are subset/debug runs only.

## Root Boundary Guard

These commands must remain free of domain-specific command options, scoped stock
affordance names, and adapter vocabulary:

```bash
./xctx --json
./xctx --json help
./xctx --json --version
./xctx --json discover
```

Guarded forbidden tokens on those root/universe surfaces:

```text
--bars
--calendar-days
--name
configured_options
search_entity_instrument
search_market_series
latest_price
latest-price
```

The stock range options are still available, but only after selecting the
scoped market-data subdomain:

```bash
./xctx --json discover stock_intelligence_hub::market_data_gateway
```

That scoped surface advertises `configured_options.observe` with `--bars`,
`--calendar-days`, and explicit `--export`.

## Audit Contract

`./xctx audit root` is the broad protocol/config/live-adapter health gate. It
may include framework checks, config fingerprints, configured option checks,
availability findings, and framework-normalized live adapter checks for online
configured subdomains.

Live adapter failures and malformed live audit payloads become failing audit
checks instead of raw crashes. Protocol-facing error previews are redacted.
Malformed audit check entries make audit fail closed.

Use scoped audit to narrow that health view:

```bash
./xctx audit stock_intelligence_hub::market_data_gateway
./xctx audit file_manager::home_directory
```

## Representative Command Checks

```bash
./xctx discover
./xctx discover stock_intelligence_hub::
./xctx discover stock_intelligence_hub
./xctx discover stock_intelligence_hub::market_data_gateway
./xctx discover stock_intelligence_hub::equity_filing
./xctx discover stock_intelligence_hub::search_entity_instrument Apple
./xctx discover stock_intelligence_hub::search_entity_instrument FB
./xctx discover stock_intelligence_hub::search_entity_instrument issuer:cik:0000320193
./xctx discover stock_intelligence_hub::search_market_series AAPL
./xctx discover stock_intelligence_hub::market_data_gateway latest_price AAPL
./xctx observe stock_intelligence_hub::market_data_gateway instrument:aapl --bars 5
./xctx observe stock_intelligence_hub::market_data_gateway AAPL --calendar-days 50
./xctx observe stock_intelligence_hub::equity_filing form:10-K
./xctx discover file_manager::home_directory list_files --limit 2
./xctx discover file_manager::home_directory file:README.txt
./xctx observe file_manager::home_directory file:README.txt
./xctx observe file:README.txt
./xctx audit file_manager::home_directory
./xctx audit root
```

## Refusal Checks

```bash
./xctx discover search_filing_family annual
./xctx discover --name Apple
./xctx observe form:10-K --bars 5
./xctx observe stock_intelligence_hub::market_data_gateway market_series:aapl:daily --bars 3 --calendar-days 7
```

Expected behavior:

- unscoped domain affordance is refused with structured `next_moves`;
- `discover --name Apple` is refused; root no longer chooses a stock action;
- market-only range options are refused on a filing target;
- mutually exclusive range windows are refused before adapter call.

## Boundary Conclusions

- Root/universe/help/version expose only the generic xctx protocol surface.
- Domain affordances are declared under scoped subdomain actions with `domain_affordance: true`.
- Domain-specific CLI options are declared on the owning YAML action and published only after the target subdomain/action is in scope.
- Ticker, symbol, CIK, former-symbol, latest-price, and OHLCV semantics live in the stock adapter/configuration layer, not in the generic xctx command surface.
- Scoped connector adapters live outside `libs/xctx` under `libs/xctx_connectors/domains/<domain>` or a concrete subdomain package.
- Connector metadata exposes `shape_guarantee` so agents can verify xctx receives one shaped JSON object for success and failure.
