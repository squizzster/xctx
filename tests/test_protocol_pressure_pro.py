"""Pytest-collected protocol pressure sections."""

from __future__ import annotations

import pytest

from framework_helpers import load_script_module


pressure = load_script_module("protocol_pressure_pro")
pytestmark = [pytest.mark.integration, pytest.mark.local_gate, pytest.mark.slow, pytest.mark.timeout(240)]


def test_pressure_root_universe_command_surface() -> None:
    pressure.assert_root_universe_command_surface()


def test_pressure_domain_subdomain_discovery() -> None:
    pressure.assert_domain_subdomain_discovery()


def test_pressure_scoped_filing_affordance_routing() -> None:
    pressure.assert_scoped_filing_affordance_routing()


def test_pressure_scoped_market_list_affordance() -> None:
    pressure.assert_scoped_market_list_affordance()


def test_pressure_scoped_file_affordance_routing() -> None:
    pressure.assert_scoped_file_affordance_routing()


def test_pressure_market_identity_search() -> None:
    pressure.assert_market_identity_search()


def test_pressure_market_observe_range_semantics() -> None:
    pressure.assert_market_observe_range_semantics()


def test_pressure_observe_error_and_cross_domain_routes() -> None:
    pressure.assert_observe_error_and_cross_domain_routes()


def test_pressure_audit_scope_results() -> None:
    pressure.assert_audit_scope_results()


def test_pressure_repair_results() -> None:
    pressure.assert_repair_results()


def test_pressure_plan_execute_binding() -> None:
    pressure.assert_plan_execute_binding()


def test_pressure_extension_lane_discipline() -> None:
    pressure.assert_extension_lane_discipline()


def test_pressure_real_cli_launcher_and_ledger_probe() -> None:
    pressure.assert_real_cli_launcher_and_ledger_probe()
