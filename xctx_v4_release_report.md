# xctx v4.2 Boundary-Hardened Release Report

## Why this correction exists

The prior v4 artifact leaked stock-domain range options (`--bars` and
`--calendar-days`) through the root/universe `./xctx` command surface. That was a
real protocol-boundary failure: root should expose the generic xctx bootloader and
agent-domain map only, not command details from a specific stock adapter.

This v4.2 correction treats that as a release blocker and fixes the boundary at
source instead of hiding it in formatting.

## Boundary rule now enforced

```text
Root/universe/help/version expose the generic xctx protocol only.
Domain-specific affordances and options appear only after an explicit domain or
subdomain is in scope.
```

Clean root/universe commands:

```bash
./xctx --json
./xctx --json help
./xctx --json --version
./xctx --json discover
```

Forbidden on those surfaces:

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

Validation result:

```text
./xctx --json: clean
./xctx --json help: clean
./xctx --json --version: clean
./xctx --json discover: clean
```

The scoped market-data surface still advertises the stock-only range options:

```bash
./xctx --json discover stock_intelligence_hub::market_data_gateway
```

```text
configured_options.observe:
  --bars
  --calendar-days
```

## What changed from the prior artifact

### Removed root leakage

- `universe_discovery_payload()` no longer publishes parser-level option inventory.
- `build_help_payload()` no longer publishes configured option inventory.
- `root_discovery_payload()` no longer publishes domain affordances or parser options.
- `./xctx`, `help`, `--version`, and `discover` are guarded with negative tests.

### Removed obsolete root shortcut machinery from the generic core

- Removed generic-core support paths for universe-level root affordances.
- Removed universe-level command shortcuts from the active configuration model.
- Removed the advertised `--name NAME` root command shape.
- `./xctx discover --name Apple` now returns an explicit refusal and tells the
  caller to use a scoped discovery action.

### Rehomed domain affordances

Domain-level conveniences are now opt-in subdomain actions:

```yaml
actions:
  latest_price:
    domain_affordance: true
    entrypoint_command: latest-price
```

For public domain names that differ from adapter-local action names:

```yaml
actions:
  search_forms:
    domain_affordance: true
    domain_action_name: search_filing_form
    entrypoint_command: search-forms
```

This remains valid:

```bash
./xctx discover stock_intelligence_hub::search_filing_form 10-K
```

This is refused:

```bash
./xctx discover search_filing_family annual
```

### Kept stock improvements scoped

The stock proof slice still includes:

- ticker, instrument id, issuer CIK, bare CIK, company-name, legal-name, alias,
  and former-symbol resolution.
- `FB -> META` lifecycle alias resolution.
- `latest_price` discovers the latest available bundled price point; observe
  returns the price data.
- ranged OHLCV observations with `price_summary`.
- explicit `is_live_quote: false` bundled-data boundary.

Those semantics remain in stock YAML and stock adapters, not in the generic xctx
root surface.

## Validation performed

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 tests/smoke_protocol.py
python3 tests/protocol_pressure_pro.py
python3 -m compileall -q libs market_data_gateway.py equity_filings.py equity_instruments.py tests
```

Result:

```text
check_xctx_yaml_surface.py: ok=true, error_count=0, warning_count=0
smoke_protocol.py: hardened xctx protocol smoke checks passed
protocol_pressure_pro.py: PRO xctx protocol pressure checks passed
compileall: ok
```

The checker also reports parser option inventory separately from scoped published
option surfaces:

```text
parser_option_counts.observe: 2
scoped_configured_options.stock_intelligence_hub::market_data_gateway.observe:
  --bars
  --calendar-days
```

## Core grep checks

Generic core is free of stock command/data literals:

```text
--bars
--calendar-days
search_entity_instrument
latest_price
latest-price
ticker
symbol
issuer:cik
```

Generic core is also free of the removed universe shortcut/root-affordance keys:

```text
root_affordance
root_affordances
command_shortcuts
```

`--name` is deliberately not advertised anywhere on root/universe/help/version.
The parser still accepts it only so the protocol can return a shaped refusal
instead of a raw argparse failure.

## Representative proof commands

```bash
./xctx --json discover stock_intelligence_hub::search_entity_instrument FB
./xctx --json discover stock_intelligence_hub::market_data_gateway latest_price AAPL
./xctx --json observe stock_intelligence_hub::market_data_gateway instrument:aapl --bars 5
./xctx --json observe stock_intelligence_hub::market_data_gateway AAPL --calendar-days 50
./xctx --json discover stock_intelligence_hub::search_filing_form 10-K
```

Representative refusals:

```bash
./xctx --json discover search_filing_family annual
./xctx --json discover --name Apple
./xctx --json observe form:10-K --bars 5
./xctx --json observe stock_intelligence_hub::market_data_gateway market_series:aapl:daily --bars 3 --calendar-days 7
```

## Honest remaining boundary

This is still a proof-of-concept. `latest_price` discovers the latest available
bundled price point; observe returns the price data. It is not a live quote feed.
That boundary is explicitly present in the latest/range payloads.

## Middleware Addendum

The current workspace also includes an enterprise middleware demonstration for:

```bash
./xctx discover file_manager::home_directory
```

The implementation keeps middleware outside the generic xctx runtime. Scoped
YAML routes to `legacy_connector.py`, which delegates to adapter-side connector
code under `libs/xctx_connectors/`. Generic `libs/xctx` still does not know file
manager semantics, scoped legacy adapter code, path policies, or transform rules.

Connector metadata now exposes `shape_guarantee` when middleware returns a
connector object. The key proof is:

```text
xctx_receives = single_json_object_for_live_data
raw_legacy_output = never_returned_unparsed
```

This is adapter-side contract evidence. It does not change the root protocol
surface; it makes the middleware boundary inspectable for agents and operators.
