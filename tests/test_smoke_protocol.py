"""Pytest-collected smoke checks for the broad protocol script."""

from __future__ import annotations

import pytest

from framework_helpers import load_script_module


smoke = load_script_module("smoke_protocol")
pytestmark = [pytest.mark.integration, pytest.mark.release, pytest.mark.timeout(180)]


def test_smoke_modular_layout() -> None:
    smoke.assert_modular_layout()


def test_smoke_protocol_is_config_driven() -> None:
    smoke.assert_protocol_is_config_driven()


def test_smoke_root_domain_subdomain_discovery() -> None:
    smoke.assert_root_domain_subdomain_discovery()


def test_smoke_scoped_filing_affordance_routing() -> None:
    smoke.assert_scoped_filing_affordance_routing()


def test_smoke_scoped_market_affordance_routing() -> None:
    smoke.assert_scoped_market_affordance_routing()


def test_smoke_connector_supervisor_middleware() -> None:
    smoke.assert_connector_supervisor_middleware()


def test_smoke_market_observe_range() -> None:
    smoke.assert_market_observe_range()


def test_smoke_filing_and_file_observe() -> None:
    smoke.assert_filing_and_file_observe()


def test_smoke_audit_repair() -> None:
    smoke.assert_audit_repair()


def test_smoke_plan_execute_other_and_output() -> None:
    smoke.assert_plan_execute_other_and_output()
