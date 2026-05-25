# Stock Intelligence Hub Adapters

```yaml
scope: stock_intelligence_hub
framework_core: false
entrypoint_owner: scoped_yaml_connector_target_entrypoint
called_by: connector_supervisor.py
adapters:
  - adapters/market_data_gateway.py
  - adapters/equity_filings.py
generic_runtime_must_not_import: true
```
