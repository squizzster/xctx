# Validation Summary

Validated on the packaged workspace with the canonical release gate.

```text
base commit: 29d16d0
working tree: release-engineering changes for packaging/install smoke
date_utc: 2026-05-25T02:46:56Z
python: Python 3.12.13
command: make release-test
pytest_collection: 57 tests
elapsed: 27.28s
exit_code: 0
```

```bash
make release-test
```

Result:

```text
python3 -m pytest -q -m release --durations=30
57 passed in 27.28s
```

The release gate now includes YAML validation, compileall, an installed-package
entrypoint smoke, child-process cleanup invariants, and the protocol
smoke/connector/boundary/pressure matrix.

## Release-blocker regression guard

The corrected bundle includes an explicit root-boundary guard. These commands must
remain free of domain-specific command options, scoped stock affordance names, and
adapter vocabulary:

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

Result:

```text
./xctx --json: clean
./xctx --json help: clean
./xctx --json --version: clean
./xctx --json discover: clean
```

The stock range options are still available, but only after selecting the scoped
market-data subdomain:

```bash
./xctx --json discover stock_intelligence_hub::market_data_gateway
```

That scoped surface advertises `configured_options.observe` with `--bars`,
`--calendar-days`, and explicit `--export`.

## Representative command checks

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

## Refusal checks

```bash
./xctx discover search_filing_family annual
./xctx discover --name Apple
./xctx observe form:10-K --bars 5
./xctx observe stock_intelligence_hub::market_data_gateway market_series:aapl:daily --bars 3 --calendar-days 7
```

Expected behavior:

- unscoped domain affordance is refused with a scoped next move.
- `discover --name Apple` is refused; root no longer chooses a stock action.
- market-only range options are refused on a filing target.
- mutually exclusive range windows are refused before adapter call.

## Boundary conclusions

- `./xctx`, `./xctx help`, `./xctx --version`, and `./xctx discover` expose only the generic xctx protocol surface.
- Domain affordances are declared under scoped subdomain actions with `domain_affordance: true`.
- Domain-specific CLI options are declared on the owning YAML action and published only after the target subdomain/action is in scope.
- Ticker, symbol, CIK, former-symbol, latest-price, and OHLCV semantics live in the stock adapter/configuration layer, not in the generic xctx command surface.
- Scoped connector adapters live outside `libs/xctx` under `libs/xctx_connectors/domains/<domain>` or a concrete subdomain package; connector metadata exposes `shape_guarantee` so agents can verify xctx receives one shaped JSON object for success and failure.
