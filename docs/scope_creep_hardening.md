# Scope-Creep Hardening: Boundary-Clean Protocol Surface

This pass fixes the release-blocking mistake where root/universe/help output
advertised stock-specific range options. The rule is now explicit and tested:

```text
Root/universe/help/version surfaces expose the generic xctx protocol only.
Domain-specific affordances and option names appear only inside a scoped domain
or subdomain surface.
```

## Root surfaces that must stay clean

The following commands are guarded by negative tests and the YAML surface checker:

```bash
./xctx
./xctx help
./xctx --version
./xctx discover
```

They must not expose:

```text
--bars
--calendar-days
--name
configured_options
root_affordances
search_entity_instrument
search_market_series
latest_price
latest-price
```

Root discovery now returns only configured agent domains and generic next moves:

```text
./xctx discover stock_intelligence_hub::
./xctx audit root
```

Bare root discovery targets are valid only for configured agent domains, such as
`./xctx discover stock_intelligence_hub` or `./xctx discover file_manager`.
Subdomains, actions, tickers, form codes, and file ids must be scoped first:

```bash
./xctx discover GOOG
./xctx discover market_data_gateway
./xctx discover file:README.txt
```

Those examples must fail rather than route through a configured fallback.

Root audit follows the same no-bubbling rule. `./xctx audit root` may summarize
configuration health and availability findings, but it must not inline scoped
adapter checks such as ticker sentinels, filing-table counts, filesystem
legacy-command probes, or middleware profile diagnostics. Use scoped audit for
those:

```bash
./xctx audit stock_intelligence_hub::market_data_gateway
./xctx audit file_manager::home_directory
```

## What moved out of root

### 1. Domain affordances

The former universe-level `root_affordances` block was removed. Domain shortcuts
are now opt-in subdomain actions:

```yaml
actions:
  latest_price:
    domain_affordance: true
    entrypoint_command: latest-price
```

For a subdomain-local action that should have a clearer domain-level name:

```yaml
actions:
  search_forms:
    domain_affordance: true
    domain_action_name: search_filing_form
    entrypoint_command: search-forms
```

That keeps this scoped command legal:

```bash
./xctx discover stock_intelligence_hub::search_filing_form 10-K
```

while refusing this unscoped command:

```bash
./xctx discover search_filing_family annual
```

### 2. Ranged observe options

The generic parser still loads YAML-declared options so command lines can be
parsed, but root/universe/help no longer publishes parser-level option inventory.
Options are shown only after the market-data subdomain is selected:

```bash
./xctx discover stock_intelligence_hub::market_data_gateway
```

The scoped surface advertises:

```yaml
configured_options:
  observe:
    - flags: [--bars]
    - flags: [--calendar-days]
```

The protocol core knows only this generic pattern:

```text
configured option -> argparse value -> resolved target validation -> adapter argv
```

It does not know what a bar or calendar day is.

### 3. `discover --name` routing

The old domain-specific `discover --name Apple` shortcut was removed from
`universe.yaml`. Root no longer encodes the stock action that should receive a
name. Agents should enter a scoped domain/action explicitly:

```bash
./xctx discover stock_intelligence_hub::search_entity_instrument Apple
```

### 4. Universe identity fields

Universe-level identity fields are generic again:

```yaml
identity_resolution:
  query_fields:
    - name
    - id
    - aliases
```

Ticker, symbol, issuer CIK, former-symbol aliases, and punctuation-normalized
company matching remain in the stock adapter layer.

## Stock behavior retained inside the scoped domain

Instrument identity remains strong:

```bash
./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument Apple
./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument Apple, Inc.
./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument issuer:cik:0000320193
./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument FB
./xctx observe stock_intelligence_hub::market_data_gateway instrument:aapl
```

Bundled OHLCV and latest available price remain scoped:

```bash
./xctx discover stock_intelligence_hub::search_market_series AAPL
./xctx discover stock_intelligence_hub::latest_price AAPL
./xctx observe stock_intelligence_hub::market_data_gateway AAPL --calendar-days 50
./xctx observe stock_intelligence_hub::market_data_gateway instrument:aapl --bars 5
```

Unsupported target/option combinations are still refused before adapter calls:

```bash
./xctx observe form:10-K --bars 5
```

returns guidance to remove the unsupported option for the resolved filing target.

## Guardrails added

- Negative root-surface tests in `tests/smoke_protocol.py`.
- Negative root-surface tests in `tests/protocol_pressure_pro.py`.
- YAML checker failure if `universe.yaml` contains `root_affordances` or
  domain-specific command shortcuts.
- YAML checker failure if universe identity fields include `ticker` or `symbol`.
- YAML checker output now distinguishes parser option counts from scoped option
  surfaces, so a parser inventory is not mistaken for root protocol surface.

## Core literal guard

The generic core remains free of stock command/data literals:

```text
--bars
--calendar-days
search_entity_instrument
latest_price
latest-price
ticker
symbol
```

Those stock-domain tokens live in stock YAML, stock adapters, docs, and tests only.

`--name` is separately guarded as a root-surface publication leak: the parser can
accept it to return an explicit protocol refusal, but root/help/version/discover
must not advertise it as an available root move.

## Middleware Boundary

Enterprise middleware belongs outside `libs/xctx`. The generic runtime may route
to a configured entrypoint and envelope one returned JSON object, but connector
profiles, legacy command names, path policies, and transform rules remain in
adapter-side packages such as `libs/xctx_connectors`.

The file-manager demo is therefore configured through scoped YAML and an
adapter-side connector. It exposes `connector.shape_guarantee` in live payloads
so agents can see that the middleware promises:

```text
xctx_receives = single_json_object_for_live_data
raw_legacy_output = never_returned_unparsed
```

These guarantee names must not become generic runtime semantics. They are
contract evidence emitted by the adapter boundary.
