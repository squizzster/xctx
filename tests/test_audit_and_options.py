"""Framework audit-scope and CLI option validation tests."""

from __future__ import annotations

import copy

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.release, pytest.mark.timeout(60)]


def test_audit_scope_validation_fails_closed() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.audit import audit_domain_level, audit_payload  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    store = load_store(root=ROOT)
    domain_id = next(
        domain_id
        for domain_id, domain in sorted(store["agent_domains"].items())
        if domain.get("_subdomains")
    )
    subdomain_id = sorted(store["agent_domains"][domain_id]["_subdomains"])[0]

    assert audit_domain_level(store, "root") == "root"
    assert audit_domain_level(store, domain_id) == "agent_domain"
    assert audit_domain_level(store, f"{domain_id}::{subdomain_id}") == "agent_subdomain"

    with pytest.raises(XctxError, match="known audit scope"):
        audit_payload(store, "not_a_real_domain")
    with pytest.raises(XctxError, match="known audit scope"):
        audit_payload(store, f"{domain_id}::not_a_real_subdomain")

    rc, payload = run_runtime_json(["audit", "not_a_real_domain"])
    assert rc == 1
    assert payload["ok"] is False
    assert "known audit scope" in payload["error"]


def test_option_audit_detects_duplicates_before_dedupe() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.option_surface import option_config_checks  # noqa: PLC0415

    store = copy.deepcopy(load_store(root=ROOT))
    domain = next(iter(store["agent_domains"].values()))
    subdomain = next(iter(domain["_subdomains"].values()))
    subdomain["cli_options"] = [
        {"flags": ["--xctx-duplicate-flag"], "dest": "first_duplicate", "commands": ["observe"]},
        {"flags": ["--xctx-duplicate-flag"], "dest": "second_duplicate", "commands": ["observe"]},
        {"flags": ["--xctx-dest-one"], "dest": "shared_duplicate_dest", "commands": ["observe"]},
        {"flags": ["--xctx-dest-two"], "dest": "shared_duplicate_dest", "commands": ["observe"]},
    ]

    checks = option_config_checks(store)
    observe_check = next(check for check in checks if check["id"] == "audit:xctx:cli_options:observe")
    assert observe_check["status"] == "fail"
    assert "--xctx-duplicate-flag" in observe_check["duplicate_flags"]
    assert "shared_duplicate_dest" in observe_check["duplicate_dests"]
