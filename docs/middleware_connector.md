# Middleware Connector Contract

`xctx` stays generic: it reads YAML, routes to a scoped entrypoint, receives one
JSON object, and envelopes that object. Middleware connectors live on the adapter
side of that boundary.

## Shape Guarantee

Connector metadata includes a `shape_guarantee` when middleware returns a
connector object:

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

The guarantee means the adapter boundary normalizes both success and failure.
Legacy commands may return arbitrary stdout/stderr, but xctx receives a shaped
object. Raw legacy output is not passed through as protocol payload.

For xctx-native pass-through adapters, successful calls preserve the target
adapter payload. Normalized pass-through failures return connector metadata with:

```json
{
  "contract": "pass_through_json_object",
  "xctx_receives": "single_json_object_for_live_data",
  "success_shape": "target_adapter_object",
  "failure_shape": "xctx_native_passthrough_error"
}
```

## File Manager Demo

The file-manager demo uses:

```text
file_manager::home_directory
```

Discovery lists observable objects or classifies a concrete object:

```bash
./xctx discover file_manager::home_directory list_files --limit 2
./xctx discover file_manager::home_directory file:README.txt
```

Observation materializes the selected object:

```bash
./xctx observe file_manager::home_directory file:README.txt
./xctx observe directory:docs
```

Compact discovery omits low-value diagnostics such as argv arrays and trivial
one-item pagination. `--shape full` keeps those diagnostics for inspection.

## Boundary

Do not implement connector profiles in `libs/xctx` or generic connector
middleware. Add legacy behavior under
`libs/xctx_connectors/domains/<domain>/subdomains/<subdomain>/legacy_adapter.py`,
declare only the connector kind/options in scoped YAML, and prove with tests
that generic code contains no domain or legacy-command semantics.
