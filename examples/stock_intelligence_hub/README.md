# Stock Intelligence Hub Example Adapters

This directory contains bundled example/domain adapter entrypoints for the
`stock_intelligence_hub` YAML domain.

These files are not the generic xctx framework. The framework routes to
`connector_supervisor.py`, and the supervisor invokes these adapters only after
a scoped YAML subdomain selects them with `connector.target_entrypoint`.
