"""Pytest-collected smoke checks for the broad protocol script."""

from __future__ import annotations

import pytest

from framework_helpers import load_script_module


smoke = load_script_module("smoke_protocol")
pytestmark = [pytest.mark.integration, pytest.mark.local_gate, pytest.mark.timeout(180)]


def test_smoke_modular_layout() -> None:
    smoke.run_smoke_case("modular_layout")


def test_smoke_protocol_is_config_driven() -> None:
    smoke.run_smoke_case("protocol_is_config_driven")


def test_smoke_root_domain_subdomain_discovery() -> None:
    smoke.run_smoke_case("root_domain_subdomain_discovery")


def test_smoke_scoped_filing_affordance_routing() -> None:
    smoke.run_smoke_case("scoped_filing_affordance_routing")


def test_smoke_scoped_market_affordance_routing() -> None:
    smoke.run_smoke_case("scoped_market_affordance_routing")


def test_smoke_connector_supervisor_middleware() -> None:
    smoke.run_smoke_case("connector_supervisor_middleware")


def test_smoke_market_observe_range() -> None:
    smoke.run_smoke_case("market_observe_range")


def test_smoke_filing_and_file_observe() -> None:
    smoke.run_smoke_case("filing_and_file_observe")


def test_smoke_audit_repair() -> None:
    smoke.run_smoke_case("audit_repair")


def test_smoke_plan_execute_other_and_output() -> None:
    smoke.run_smoke_case("plan_execute_other_and_output")
