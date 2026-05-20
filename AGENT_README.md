# xctx v4.2 Agent-Domain Protocol PoC

This workspace is a hardened proof-of-concept for an agent-facing `xctx`
protocol surface. The goal is not a broad feature surface; it is a correct,
pressure-tested protocol path from:

```text
ROOT -> AGENT DOMAIN -> AGENT SUBDOMAIN -> SCOPED AFFORDANCE / OBSERVATION
```

The protocol/configuration layer is separated from live read-only data adapters:

- `./xctx` is the protocol bootloader.
- `yaml_dynamic_config/` describes the universe, agent domains, subdomains,
  statuses, commands, routing, and lawful next moves.
- `legacy_connector.py` and `libs/xctx_connectors/` provide adapter-side
  middleware for xctx-native pass-through and legacy command transforms.
- `market_data_gateway.py` / `equity_instruments.py` are read-only market-data
  adapter entrypoints.
- `equity_filings.py` is the read-only EDGAR filing taxonomy adapter.

Boundary for future agents: keep `xctx`, `bin/xctx`, and `libs/xctx` as the
generic interface/protocol layer. Domain/subdomain/mode meaning belongs in
scoped YAML and adapter code. Generic runtime comments use `## Protocol
boundary` markers to make that separation explicit.

The active online agent domain is `stock_intelligence_hub`. Its online
subdomains are:

- `stock_intelligence_hub::market_data_gateway`
- `stock_intelligence_hub::equity_filing`
- `file_manager::home_directory` as a legacy middleware demonstration domain

Other domains/subdomains are deliberately offline or down for maintenance so an
agent can test audit and repair behavior without guessing.

## Core command set

The exposed command set is deliberately small:

```bash
./xctx discover
./xctx observe <thing>
./xctx plan <operation>
./xctx execute <plan-or-receipt> --commit
./xctx audit <scope>
./xctx repair <finding>
./xctx other --topic <topic>
```

`discovery` remains a compatibility alias for `discover`, but the advertised command is
`discover`. The single-letter `d` alias is intentionally not accepted; this PoC keeps the protocol surface narrow.

## Quick start

```bash
./xctx
./xctx help
./xctx discover
./xctx discover stock_intelligence_hub::
./xctx discover stock_intelligence_hub
./xctx discover stock_intelligence_hub::market_data_gateway
./xctx discover stock_intelligence_hub::equity_filing
```

`./xctx` discovers the xctx universe. `./xctx discover` discovers the root
agent-domain surface.

## Scoped affordances

Root discovery is domain-only. These are valid bare discovery targets because
they are configured agent domains:

```bash
./xctx discover file_manager
./xctx discover stock_intelligence_hub
./xctx discover macro_intelligence_hub
./xctx discover crypto_intelligence_hub
./xctx discover options_intelligence_hub
```

Bare subdomains, action names, instruments, filing codes, and file ids are
intentionally refused. These are invalid:

```bash
./xctx discover GOOG
./xctx discover market_data_gateway
./xctx discover file:README.txt
./xctx discover search_filing_family annual
```

Use a scoped domain affordance instead:

```bash
./xctx discover stock_intelligence_hub::search_filing_family annual
./xctx discover stock_intelligence_hub::search_priority_bucket critical
./xctx discover stock_intelligence_hub::search_entity_instrument Apple
./xctx discover stock_intelligence_hub::latest_price AAPL
```

A safe shorthand is also supported when the first token is already a scoped xctx
reference:

```bash
./xctx stock_intelligence_hub::search_priority_bucket critical
```

Full subdomain action form also works:

```bash
./xctx discover stock_intelligence_hub::market_data_gateway::search_entity_instrument
./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument Apple
./xctx discover stock_intelligence_hub::market_data_gateway list_instruments --limit 25 --cursor 25
./xctx discover stock_intelligence_hub::market_data_gateway list_instruments --shape full
./xctx discover stock_intelligence_hub::equity_filing::search_forms
./xctx discover stock_intelligence_hub::equity_filing search_forms 10-K
./xctx discover stock_intelligence_hub::equity_filing list_forms --limit 25 --cursor 25
./xctx discover stock_intelligence_hub::equity_filing list_forms --shape full
```

## Working read-only data paths

Instrument identity:

```bash
./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument Apple
./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument Apple, Inc.
./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument issuer:cik:0000320193
./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument FB
./xctx discover stock_intelligence_hub::market_data_gateway search_entity_instrument A
./xctx observe stock_intelligence_hub::market_data_gateway instrument:aapl
```

The resolver is ticker/CIK/alias/name aware: exact tickers and CIKs rank first,
former-symbol aliases such as `FB` can resolve to curated canonical records such as
`META`, and punctuation-normalized legal names such as `Apple, Inc.` resolve to
`AAPL`. Instrument search does not inline market-series payloads; it emits next
moves so the agent explicitly discovers latest price or market series when needed.

Bundled OHLCV market series:

```bash
./xctx discover stock_intelligence_hub::market_data_gateway search_market_series AAPL
./xctx discover stock_intelligence_hub::market_data_gateway search_market_series issuer:cik:0000320193
./xctx discover stock_intelligence_hub::latest_price AAPL
./xctx observe stock_intelligence_hub::market_data_gateway market_series:aapl:daily
./xctx observe stock_intelligence_hub::market_data_gateway AAPL --calendar-days 50
./xctx observe stock_intelligence_hub::market_data_gateway instrument:aapl --bars 5
```

`latest_price` discovers the latest available bundled price point; observe returns
the price data. Range observations include a `price_summary`
(first/last close, change, percent change, highest high, and lowest low) plus a
CSV export path for local inspection.

Those range options are not hardcoded in the generic parser. They are declared on
the market-data `observe` action in YAML under `cli_options`, advertised only
after the market-data subdomain is in scope (`./xctx discover
stock_intelligence_hub::market_data_gateway`), validated after target routing,
and then passed through to the market adapter. Unsupported target/option
combinations, such as `form:10-K --bars 5`, are refused by the protocol layer
before the filing adapter is called.

Filing taxonomy:

```bash
./xctx discover stock_intelligence_hub::equity_filing
./xctx discover stock_intelligence_hub::equity_filing::search_forms
./xctx discover stock_intelligence_hub::equity_filing list_forms
./xctx discover stock_intelligence_hub::equity_filing list_families
./xctx discover stock_intelligence_hub::equity_filing list_priority_buckets
./xctx discover stock_intelligence_hub::search_filing_form 10-K
./xctx discover stock_intelligence_hub::search_filing_family annual
./xctx discover stock_intelligence_hub::search_priority_bucket critical
./xctx observe stock_intelligence_hub::equity_filing form:10-K
./xctx observe stock_intelligence_hub::equity_filing instrument:aapl
```

`equity_filing` base discovery advertises its modes directly. `search_forms`,
`search_families`, and `search_priority_buckets` with no query return interface
metadata; with a query they execute the search. Exact code queries such as
`10-K`, `8-K`, `ANNUAL_REPORT`, or `critical_always` are resolved exactly before
broad descriptive text search is used.

List modes return compact index rows by default. Use `--shape full` only when
bulk detail is needed; use `observe` for one full object. Cursor support is
declared per scoped list action and cursor values are adapter-owned.

Legacy middleware demo:

```bash
./xctx discover file_manager::
./xctx discover file_manager::home_directory
./xctx discover file_manager::home_directory list_files --limit 2
./xctx discover file_manager::home_directory file:README.txt
./xctx observe file_manager::home_directory file:README.txt
./xctx audit file_manager::home_directory
```

The file-manager connector demonstrates the enterprise middleware contract:
legacy command output is transformed into a stable object before xctx envelopes
it. Connector metadata exposes a `shape_guarantee` declaring that xctx receives
`single_json_object_for_live_data`, with legacy success as a domain object and
legacy failure as `legacy_connector_error`.

## What is real in this PoC

The filing adapter reads `data/edgar_form_reference_taxonomy.sqlite`, which
contains 412 EDGAR form lookup records, 41 canonical families, 12 priority
buckets, 51 category labels, and 176 amendment forms.

The market adapter reads:

- `yaml_dynamic_config/agent_domains/stock_intelligence_hub/subdomains/market_data_gateway/instruments.yaml`
  for curated canonical cross-subdomain instrument seed records.
- `data/mini_stocks.sqlite` for a read-only market fixture with 100 reference
  universe rows, 100 OHLCV series, and 122,828 bars.

The adapter deduplicates these into 106 canonical instrument identities for
search/observe/audit, including the bundled market fixture and curated YAML-only
handoff records such as `META` for former-symbol alias testing.

## Audit and repair protocol

```bash
./xctx audit root
./xctx repair offline:macro_intelligence_hub
./xctx repair down_for_maintenance:stock_intelligence_hub::fundamentals_gateway
```

Root audit stays at the protocol/config/domain-availability layer. It does not
call scoped adapters or bubble fixture checks such as ticker probes, database
counts, filing table checks, or filesystem legacy-command probes. Use scoped
audit for adapter health:

```bash
./xctx audit stock_intelligence_hub::market_data_gateway
./xctx audit file_manager::home_directory
```

Offline targets expose a repair path. Down-for-maintenance targets are terminal:
`repair_path: null`, `final: true`, and the response cites that the target is
`down for maintenance`.

## Plan and execute receipts

This build does not mutate domain state, but it does produce deterministic plan
receipts and writes them to a local runtime ledger under `.xctx_runtime/plans/`.
`execute` accepts only receipts that resolve to a recorded plan, so a random
five-character hex string is not enough:

```bash
PLAN_ID=$(./xctx plan bring_online stock_intelligence_hub::market_data_gateway \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["results"]["plan_id"])')
./xctx execute "$PLAN_ID" --commit
```

Plans return:

- `planner_id`: full sha256 hex
- `plan_id`: `plan:sha256:<sha256>`
- `receipt_sha5`: short PoC/debug token accepted only when it resolves uniquely to a recorded plan

`execute` returns a `planner_binding` object proving which recorded plan was accepted, plus `accepted_read_only_noop` and `mutations_applied: 0`.

## Output formats

Machine default is JSONL:

```bash
./xctx discover
```

YAML is explicit or selected automatically for a TTY:

```bash
./xctx --yaml discover
./xctx --json discover
```

## Smoke test

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 tests/smoke_protocol.py
python3 tests/protocol_pressure_pro.py
python3 tests/protocol_legacy_connector.py
```

The YAML guard validates root-boundary cleanliness, scoped domain affordances,
domain/subdomain references, online entrypoint paths, action aliases, observe
routes, identity fields, and configured option parseability. The smoke and
pressure tests then validate the modular layout, config-driven routing, ROOT /
DOMAIN / SUBDOMAIN discovery, scoped affordance routing, refusal of unscoped
actions, read-only filing and market lookups, observe flows, offline/maintenance
repair flows, and plan/execute receipts.

## PRO hardening notes

This build intentionally tightens several edges that were easy to get almost right:

- Unscoped affordance names are refused; scoped ROOT → DOMAIN → SUBDOMAIN paths are required.
- Domain-specific command options are declared in YAML `cli_options`; the core parser does not name market-series flags.
- `discover --name` is intentionally refused; root no longer chooses a stock action from a bare name.
- Unknown command names are refused with a pointer to `./xctx other --topic ...`; they are not silently treated as protocol commands.
- `receipt_sha5` is compatibility sugar, not authority. It must bind to a recorded plan in `.xctx_runtime/plans/`.
- Instrument search emits minimal identity results and next moves; latest_price discovers the latest available bundled price point, and observe returns the price data.
- List actions emit compact index rows by default; full bulk rows require `--shape full`, and cursor support is scoped/optional.
- latest_price is not a live quote; it discovers the latest available bundled price point before observe materializes the data.
