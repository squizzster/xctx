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
Bare root targets are legal only for configured agent domains. Do not configure
`agent_routing.discovery_fallback`, and do not rely on the active domain to
resolve bare subdomain/action/object tokens such as `market_data_gateway`,
`GOOG`, `10-K`, or `file:README.txt`.

Root audit is generic too. `./xctx audit root` must not call subdomain adapters
or bubble application-specific health probes. Adapter checks such as fixture
tickers, database counts, filing tables, scoped connector adapters, or legacy
command availability belong behind explicit scoped audits such as
`./xctx audit <domain_id>::<subdomain_id>`.

## Entrypoints

Subdomains declare the connector supervisor entrypoint that xctx calls. Online
live execution routes through this middleware first, then passes through to an
xctx-native application adapter or legacy adapter:

```yaml
entrypoint:
  file: legacy_connector.py
  protocol: json_stdout
connector:
  kind: xctx_native_passthrough
  target_entrypoint: market_data_gateway.py
```

and:

```yaml
entrypoint:
  file: legacy_connector.py
  protocol: json_stdout
connector:
  kind: xctx_native_passthrough
  target_entrypoint: equity_filings.py
```

The protocol runtime loads YAML declarations and subprocesses the connector
supervisor only when an online action requires live bundled data. Direct adapter
entrypoints are not valid scoped YAML entrypoints. The xctx core therefore knows
how to route a declared domain, subdomain, and action, but it does not need to
know what a ticker, CIK, latest price, filing form, bar, or calendar day means.
Pass-through `target_entrypoint` values are workspace-relative executable files;
absolute paths and paths that resolve outside the workspace are rejected.

Legacy integrations use the same xctx surface. The subdomain still declares a
single JSON entrypoint, but the generic connector middleware derives a
deterministic adapter from the resolved scope and normalizes success and failure
into one object for xctx to envelope. The default adapter scope is the concrete
subdomain; domains that own reusable semantics can opt a subdomain into a
domain-owned adapter without declaring an arbitrary Python import path:

```yaml
entrypoint:
  file: legacy_connector.py
  protocol: json_stdout
connector:
  kind: legacy_command
  adapter_scope: domain
  safe_root: data/file_manager_home
```

The file-manager demo proves this with ordinary filesystem commands. Discovery
returns `file:<relative_path>` and `directory:<relative_path>` identities;
observation inspects the selected object. The generic `libs/xctx` runtime still
contains no file-manager, stock, or filing semantics. The file-manager legacy
behavior lives under
`libs/xctx_connectors/domains/file_manager/legacy_adapter.py`; the
`home_directory` subdomain only configures one bounded safe-root scope.

Middleware payloads that return connector metadata also declare a
`shape_guarantee`. This is not parsed by `libs/xctx`; it is an adapter-side
contract made visible in the live data object:

```json
{
  "connector": {
    "version": "legacy_connector.v1",
    "kind": "legacy_command",
    "adapter_ref": "file_manager::home_directory",
    "shape_guarantee": {
      "contract": "always_json_object",
      "xctx_receives": "single_json_object_for_live_data",
      "success_shape": "domain_object",
      "failure_shape": "legacy_connector_error",
      "raw_legacy_output": "never_returned_unparsed",
      "stdout_stderr": "summarized_in_command_status_when_useful"
    }
  }
}
```

The guarantee means the legacy command may fail, time out, or emit terminal
text, but xctx still receives one JSON object to envelope. Successful
xctx-native pass-through calls can preserve the target adapter payload
unchanged; normalized pass-through failures use
`failure_shape: xctx_native_passthrough_error`.

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
