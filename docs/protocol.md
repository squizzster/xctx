# xctx v4.2 Protocol Notes

`xctx` is an executable context protocol for agents. It makes a local software
universe discoverable without assuming the agent already knows the domain.

## Core command set

1. `xctx discover`
2. `xctx observe <thing>`
3. `xctx plan <operation>`
4. `xctx execute <plan> --commit`
5. `xctx audit <scope>`
6. `xctx repair <finding>`
7. `xctx other` as an extension lane

The protocol file accepts `discovery` as a compatibility alias for `discover`.
The single-letter `d` alias is intentionally refused. No `identify`, `write`,
`doctor`, or `status` command is advertised or accepted in the core surface; use
the explicit `other` lane for extension topics.

## Protocol path

The required path is:

```text
ROOT -> AGENT DOMAIN -> AGENT SUBDOMAIN -> SCOPED AFFORDANCE / OBSERVATION
```

Examples:

```bash
./xctx discover
./xctx discover stock_intelligence_hub
./xctx discover stock_intelligence_hub::
./xctx discover stock_intelligence_hub::equity_filing
./xctx discover stock_intelligence_hub::equity_filing::search_forms
./xctx discover stock_intelligence_hub::search_filing_family annual
./xctx discover stock_intelligence_hub::equity_filing search_forms 10-K
./xctx discover stock_intelligence_hub::equity_filing list_forms
```

Bare root discovery targets are valid only when the target is a configured
agent domain. Bare subdomains, action names, instruments, filing codes, and file
ids are refused:

```bash
./xctx discover GOOG
./xctx discover market_data_gateway
./xctx discover file:README.txt
./xctx discover search_filing_family annual
```

The returned error points to the next valid move when a scoped equivalent is
known.

## Record envelope

Responses are emitted as one protocol-shaped record by default:

```yaml
version_xctx: v4.2
cmdline_arg: discover
record_type: discovery
ok: true
domain_level: root
results: {}
```

The active record types are `discovery`, `result`, `observation`, `plan`,
`execution_result`, `audit`, `repair_result`, `extension`, and `error`.

## Domain levels

- `universe`: what xctx is, the generic command surface, and which agent domains exist.
- `root`: agent-domain overview and generic next moves.
- `agent_domain`: a configured domain such as `stock_intelligence_hub`; domain affordances may appear here.
- `agent_subdomain`: a configured subdomain such as `equity_filing`; subdomain actions and scoped options may appear here.

## Status semantics

- `online`: discoverable and callable.
- `offline`: discoverable but not callable; may expose `repair_path`.
- `down_for_maintenance`: terminal offline state; no repair path is exposed.

## Root boundary

These surfaces must remain free of domain-action command surfaces and domain
option names:

```bash
./xctx
./xctx help
./xctx --version
./xctx discover
./xctx audit root
```

They may expose configured agent domains and generic commands, but not scoped
stock affordances or range flags. Domain-specific affordances appear only after a
specific agent domain or subdomain is selected.

`audit root` is also generic. It reports xctx/config checks, configured option
shape, and availability findings for domains/subdomains. It does not call scoped
adapters or inline application checks such as fixture tickers, database row
counts, filing tables, or legacy command probes. Use a scoped audit for those:

```bash
./xctx audit stock_intelligence_hub::market_data_gateway
./xctx audit file_manager::home_directory
```

## AI Agent Boundary

Future agents should treat `xctx` as the protocol/interface layer, not as a
place for domain-pack implementation. Generic `xctx` code may parse configured
reference shapes, emit envelopes, validate option structure, route to declared
entrypoints, and enforce root/scoped boundaries. It must not learn what a scoped
mode means.

The meaning of a scoped operation belongs in two places:

- YAML under the owning domain/subdomain/action.
- Adapter-side code behind the connector supervisor.

If a change requires business vocabulary, exact-code ranking, list payload
shape, provider behavior, or domain-specific examples, put that logic outside
`libs/xctx`. Add `## Protocol boundary` comments when editing generic runtime
files so later agents do not collapse scoped behavior back into the core.

## Configured option surface

The protocol core can parse YAML-declared command options, but option names are
supplied by scoped domain YAML and are emitted only on scoped surfaces. In this
build, `--bars` and `--calendar-days` are declared by the stock market-data
`observe` action and are visible from:

```bash
./xctx discover stock_intelligence_hub::market_data_gateway
```

They are not visible from root/universe/help/version output. The core rejects a
configured option when it is used against a target whose resolved subdomain/action
does not declare that option.

This preserves the protocol invariant:

```text
option names are domain-pack semantics; option parsing, target validation, and
adapter argv encoding are framework semantics.
```

## Plan/execute boundary

`plan` returns a deterministic sha256 planner receipt and records the plan in
`.xctx_runtime/plans/`. `execute` requires `--commit` and accepts
`plan:sha256:<64-hex>`, the raw 64-character sha256, or the five-character
PoC/debug `receipt_sha5` only when that value resolves to a recorded plan. Shape
alone is not enough. This build performs no domain mutation and returns
`accepted_read_only_noop` with a `planner_binding` proof.

## Protocol/config split

`yaml_dynamic_config/` describes protocol, domains, subdomains, actions, and
routes. Live data access sits behind the configured connector supervisor, which
subprocesses adapter-side code and returns one JSON object for `xctx` to
envelope. This keeps `xctx` as the bootloader and avoids mixing business/domain
logic into the protocol runtime.

## Middleware Shape Guarantee

Legacy connector middleware sits behind scoped YAML entrypoints. Its job is to
call an application adapter or legacy command behind the supervisor boundary and
return one JSON-compatible object for xctx to envelope. When a connector returns
connector metadata, it declares a `shape_guarantee` such as:

```json
{
  "contract": "always_json_object",
  "xctx_receives": "single_json_object_for_live_data",
  "success_shape": "domain_object",
  "failure_shape": "legacy_connector_error",
  "raw_legacy_output": "never_returned_unparsed"
}
```

This is visible protocol evidence, not extra domain logic in `libs/xctx`. The
generic runtime still only routes to the configured entrypoint and envelopes the
returned object. The connector owns the guarantee that raw stdout/stderr and
legacy failures are transformed or summarized before xctx sees them.

## Action Discovery

Subdomain actions are discoverable without executing a query:

```bash
./xctx discover <agent_domain>::<agent_subdomain>::<action>
./xctx discover <agent_domain>::<agent_subdomain> <action>
```

If an action requires a query, the no-query form returns interface metadata from
YAML: argument shapes, examples, related commands, and return type. If an action
does not require a query, such as a list action, the action may execute directly.

Domain-specific grammar remains scoped. The generic runtime parses the
`domain::subdomain::action` shape but does not hardcode filing forms, tickers,
range flags, or other domain nouns.

Collection controls are optional scoped action metadata. If an action declares a
`collection` block, xctx may validate generic `--limit`, `--cursor`, and
`--shape` syntax before forwarding the request. Cursor values remain opaque and
adapter-owned. Default list payloads should be compact indexes; full bulk rows
require explicit `--shape full`, targeted search, or observe.
