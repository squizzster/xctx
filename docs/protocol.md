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
./xctx discover stock_intelligence_hub::
./xctx discover stock_intelligence_hub::equity_filing
./xctx discover stock_intelligence_hub::search_filing_family annual
./xctx discover stock_intelligence_hub::equity_filing search_forms 10-K
```

Unscoped affordances are refused:

```bash
./xctx discover search_filing_family annual
```

The returned error points to the scoped command.

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
```

They may expose configured agent domains and generic commands, but not scoped
stock affordances or range flags. Domain-specific affordances appear only after a
specific agent domain or subdomain is selected.

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
routes. Python entrypoints own read-only live data access. This keeps `xctx` as
the bootloader and avoids mixing business/domain logic into the protocol runtime.
