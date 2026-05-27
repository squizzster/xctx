# xctx detail-level refactor notes

Implemented protocol-wide `detail_level: basic|more|max` as an envelope-owned concept.

## Core contract

- Every emitted record receives top-level `detail_level`.
- Naked/orientation surfaces default to `more`:
  - `./xctx`
  - `./xctx discover`
  - help/version surfaces
- Scoped/named operational commands default to `basic`.
- `--basic`, `--more`, `--max`, and `--detail-level basic|more|max` are global prefix controls.
- Public `--detail` is rejected.
- Public verbosity use of `--shape compact|full` is rejected and replaced by `--projection compact|full` for domain row density.

## Central leakage boundary

`libs/xctx/protocol/projection.py` is the final framework-owned output projection boundary. Domain modules and adapters may build rich internal payloads, but stdout goes through the centralized projector and final envelope pass before redaction/emission.

Below `max`, the central projector strips diagnostics such as connector metadata, command status, external command strings, argv, planner internals, fingerprints, config file details, and loaded config files. Across all levels, absolute workspace paths are replaced with `<workspace_root>`.

## Separation of concepts

- `detail_level` controls protocol verbosity, guidance, and diagnostics.
- `projection` controls domain result density inside `live_data`.
- Pagination, output format, permissions, and commit boundaries remain separate.

## Validation contract

- `python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py`
- `python3 -m compileall -q bin connector_supervisor.py examples libs tests`
- `python3 -m pytest -q --durations=30`
- `make package-install-smoke` for the explicit online package install path.
