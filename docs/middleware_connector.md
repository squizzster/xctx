# Middleware Connector Contract

## Boundary

```yaml
xctx_core:
  owns:
    - load_yaml
    - call_connector_supervisor
    - envelope_one_json_object
  forbids:
    - external_command_semantics
    - domain_adapter_imports
middleware:
  owns:
    - connector_metadata
    - pass_through_failure_normalization
    - external_command_adapter_dispatch
    - structured_failure_payloads
```

## Shape Guarantee

```yaml
external_command:
  contract: always_json_object
  xctx_receives: single_json_object_for_live_data
  success_shape: domain_object
  failure_shape: xctx_connector_error
  raw_external_output: never_returned_unparsed
  stdout_stderr: summarized_in_command_status_when_useful
xctx_native_passthrough:
  contract: pass_through_json_object
  xctx_receives: single_json_object_for_live_data
  success_shape: target_adapter_object
  failure_shape: xctx_native_passthrough_error
```

## Failure Rules

```yaml
missing_executable: structured_failure_object
empty_argv: structured_failure_object
timeout: structured_failure_object
unknown_exit_code: null_not_zero
redaction:
  helper: xctx.process.redaction
  applies_to:
    - command_status.error
    - requested_args
    - argv
    - target_payload
    - stdout_preview
    - stderr_preview
```

## Adapter Paths

```yaml
domain_adapter: libs/xctx_connectors/domains/<domain>/external_command_adapter.py
subdomain_adapter: libs/xctx_connectors/domains/<domain>/subdomains/<subdomain>/external_command_adapter.py
yaml_import_paths: forbidden
flat_profiles: forbidden
```
