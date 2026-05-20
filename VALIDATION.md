# Validation Summary

Validated on the packaged workspace with:

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 tests/smoke_protocol.py
python3 tests/protocol_pressure_pro.py
python3 tests/protocol_legacy_connector.py
python3 -m compileall -q libs market_data_gateway.py equity_filings.py equity_instruments.py tests
```

Result:

```text
check_xctx_yaml_surface.py: ok=true, error_count=0, warning_count=0
smoke_protocol.py: hardened xctx protocol smoke checks passed
protocol_pressure_pro.py: PRO xctx protocol pressure checks passed
protocol_legacy_connector.py: legacy connector middleware checks passed
compileall: ok
```

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

That scoped surface advertises `configured_options.observe` with `--bars` and
`--calendar-days`.

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
./xctx discover stock_intelligence_hub::latest_price AAPL
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
- Middleware connector profiles live outside `libs/xctx`; connector metadata exposes `shape_guarantee` so agents can verify xctx receives one shaped JSON object for success and failure.
