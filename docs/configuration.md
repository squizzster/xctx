# Configuration Layout

The active protocol proof-of-concept is configured under `yaml_dynamic_config/`.

Important files:

- `universe.yaml`: root universe, active agent domain, generic identity fields,
  domain routing, and compatibility system list. It must not contain
  domain-action shortcuts or domain option names.
- `protocols/xctx_v4_2.yaml`: envelope keys, command groups, aliases, record
  types, and output policy.
- `shared/command_sets/core_commands.yaml`: the core xctx command surface.
- `agent_domains/*/domain.yaml`: agent-domain status and descriptions.
- `agent_domains/*/subdomains/*/subdomain.yaml`: subdomain actions,
  entrypoints, and scoped CLI options.

The root/universe protocol surface stays generic. Domain affordances are declared
inside subdomain YAML and can opt into an agent-domain shortcut with
`domain_affordance: true`.

## AI Agent Boundary

`xctx` is the interface contract. It answers: which commands exist, which
references are valid, which subdomain/action is in scope, which options are
syntactically valid, and which adapter should receive the request.

Scoped YAML and adapters answer: what the request means. Put domain nouns,
ranking rules, list payloads, exact-match policy, data-source behavior, and
examples here, not in `libs/xctx`.

When editing generic runtime files, keep comments generic and explicit:

```python
## Protocol boundary: this code routes configured refs only.
## Scoped domain-pack semantics belong in YAML and adapters.
```

Do not include concrete domain nouns in generic runtime comments; the guardrail
checker scans selected core files for known scoped tokens.

Example from the stock market-data subdomain:

```yaml
actions:
  latest_price:
    domain_affordance: true
    entrypoint_command: latest-price
    run_cmd: ./xctx discover stock_intelligence_hub::market_data_gateway latest_price <ticker|instrument_id|CIK|market_series:ticker:daily>
```

Example from the filing subdomain, where the subdomain-local action name differs
from the domain-level affordance name:

```yaml
actions:
  search_forms:
    domain_affordance: true
    domain_action_name: search_filing_form
    entrypoint_command: search-forms
    query_required: true
    argument_shapes:
      - "<form code>"
      - "<descriptive text>"
    examples:
      - run_cmd: ./xctx discover stock_intelligence_hub::equity_filing search_forms 10-K
    run_cmd: ./xctx discover stock_intelligence_hub::equity_filing search_forms <form code|name|family|priority|text>
  list_forms:
    entrypoint_command: list-forms
    query_required: false
    mode_kind: list
    collection:
      result_path: forms
      default_limit: 25
      max_limit: 100
      cursor: optional
      cursor_type: opaque
      default_shape: compact
      item_shapes: [compact, full]
    run_cmd: ./xctx discover stock_intelligence_hub::equity_filing list_forms [--limit N] [--cursor CURSOR] [--shape compact|full]
```

That means the following is scoped and legal:

```bash
./xctx discover stock_intelligence_hub::equity_filing::search_forms
./xctx discover stock_intelligence_hub::search_filing_form 10-K
./xctx discover stock_intelligence_hub::equity_filing list_forms
```

List modes are discovery indexes by default. Use compact rows for fast scanning,
declare optional cursor support in `collection`, and reserve full nested records
for `--shape full`, targeted search, or observe payloads.

But the root remains clean:

```bash
./xctx discover
```

returns agent domains and generic next moves only. It does not advertise
`latest_price`, `search_entity_instrument`, `--bars`, or `--calendar-days`.

## Entrypoints

The live stock subdomains have explicit external entrypoints:

```yaml
entrypoint:
  file: market_data_gateway.py
  protocol: json_stdout
```

and:

```yaml
entrypoint:
  file: equity_filings.py
  protocol: json_stdout
```

The protocol runtime loads YAML declarations and calls the entrypoint only when
an online action requires live bundled data. The xctx core therefore knows how to
route a declared domain, subdomain, and action, but it does not need to know what
a ticker, CIK, latest price, filing form, bar, or calendar day means.

## Scoped command options

Subdomain actions can expose command-specific CLI options through `cli_options`.
The generic parser may register these options so it can parse a command line,
but the public option surface is only emitted after a concrete subdomain/action
is in scope.

Example from `market_data_gateway`:

```yaml
actions:
  observe:
    run_cmd: ./xctx observe stock_intelligence_hub::market_data_gateway <id> [--bars N|--calendar-days N]
    cli_options:
      - flags: [--bars]
        dest: bars
        type: int
        min: 0
        adapter_arg: --bars
        mutex_group: market_series_range_window
        conflict_message: choose either --bars or --calendar-days
      - flags: [--calendar-days]
        dest: calendar_days
        type: int
        min: 0
        adapter_arg: --calendar-days
        mutex_group: market_series_range_window
        conflict_message: choose either --bars or --calendar-days
```

These options are visible at the scoped surface:

```bash
./xctx discover stock_intelligence_hub::market_data_gateway
```

They are not visible at:

```bash
./xctx
./xctx help
./xctx --version
./xctx discover
```

Unsupported target/option combinations, such as `form:10-K --bars 5`, are
refused after target resolution and before the filing adapter is called.

## Generic universe identity fields

Universe-level identity search stays generic:

```yaml
identity_resolution:
  query_fields: [name, id, aliases]
```

Ticker, symbol, issuer CIK, punctuation-normalized company names, aliases, and
former-symbol handling are stock-domain behavior implemented in
`market_data_gateway.py` and `libs/xctx_live/instruments.py`.
