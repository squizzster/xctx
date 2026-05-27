# xctx YAML Validation Matrix

## Always

```bash
python3 .agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py
python3 -m compileall -q bin connector_supervisor.py examples libs tests
python3 -m pytest -q --durations=30
```

Expected:

```text
102 passed
```

## Probe Matrix

```yaml
root_boundary:
  probes:
    - ./xctx --json
    - ./xctx --json help
    - ./xctx --json --version
    - ./xctx --json discover
  assert_absent:
    - --bars
    - --calendar-days
    - --name
    - configured_options
    - root_affordances
domain_add:
  probes:
    - ./xctx --json discover <domain_id>
    - ./xctx --json discover <domain_id>::
    - ./xctx --json audit <domain_id>
subdomain_add:
  probes:
    - ./xctx --json discover <domain_id>::<subdomain_id>
    - ./xctx --json audit <domain_id>::<subdomain_id>
domain_affordance_add:
  probes:
    - ./xctx --json discover <domain_id>::<affordance> <query>
    - ./xctx --json discover <affordance> <query> || true
  assert:
    - scoped_succeeds
    - unscoped_fails
    - no_collision_with_subdomain_id
action_add:
  probes:
    - ./xctx --json discover <domain_id>::<subdomain_id>::<action>
    - ./xctx --json discover <domain_id>::<subdomain_id> <action>
    - ./xctx --json discover <domain_id>::<subdomain_id> <action> <query>
list_add:
  probes:
    - ./xctx --json discover <domain_id>::<subdomain_id> list_<objects>
    - ./xctx --json discover <domain_id>::<subdomain_id> list_<objects> --limit 2
    - ./xctx --json discover <domain_id>::<subdomain_id> list_<objects> --projection full
option_add:
  probes:
    - ./xctx --json discover <domain_id>::<owning_subdomain>
    - ./xctx --json <command> <owning_target> --<flag> <value>
    - ./xctx --json <command> <wrong_target> --<flag> <value> || true
    - ./xctx --json <command> <owning_target> --<flag> <bad_value> || true
middleware_add:
  probes:
    - ./xctx --json discover <domain_id>::<subdomain_id>
    - ./xctx --json observe <trusted_prefix>:<known_id>
    - ./xctx --json observe <trusted_prefix>:<invalid_id> || true
  assert:
    - one_json_object
    - structured_failure
    - payload_contract_present_when_connector_metadata_present
removal:
  probes:
    - rg '<removed_id_or_flag>' yaml_dynamic_config docs tests README.md || true
    - ./xctx --json discover <old_projection> || true
  assert:
    - stale_refs_removed
    - old_projection_refused
```
