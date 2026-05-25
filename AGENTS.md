# AGENTS.md

## Workspace

```yaml
root: /data/EdgarToolsWorkFlow/xctx_v4_2
scope: self_contained_local_workspace
experiments_dir: experiments_tmp/<random_32_char_hex_string>
```

Modify main code when the user request authorizes it. Otherwise, keep experiments in the experiments directory.

## Development Posture

```yaml
status: live_local_development
public_compatibility_target: false
backward_compatibility_burden: false
default_change_policy:
  - prefer_current_protocol
  - delete_obsolete_paths
  - rename_confusing_old_terms
  - reject_old_aliases
  - test_current_contract_not_history
  - treat_stale_docs_and_hints_as_bugs
```

## xctx Contract

```yaml
visible_root_commands:
  - discover
  - observe
  - plan
  - execute
  - audit
  - repair
hidden_extension_lane:
  - other
removed_root_commands:
  - status
  - identify
  - doctor
  - write
  - discovery
implicit_domain_selector: forbidden
generic_runtime_domain_semantics: forbidden
domain_semantics_location:
  - scoped_yaml
  - adapter_code
```

If a future change appears to require compatibility with old behavior, make that requirement explicit before adding a shim.
