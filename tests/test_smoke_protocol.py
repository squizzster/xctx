"""Pytest-collected smoke checks for the broad protocol script."""

from __future__ import annotations

from framework_helpers import load_script_module


smoke = load_script_module("smoke_protocol")


def test_smoke_modular_layout() -> None:
    smoke.assert_modular_layout()


def test_smoke_protocol_is_config_driven() -> None:
    smoke.assert_protocol_is_config_driven()


def test_smoke_root_domain_subdomain_discovery() -> None:
    smoke.assert_root_domain_subdomain_discovery()


def test_smoke_scoped_affordance_routing() -> None:
    smoke.assert_scoped_affordance_routing()


def test_smoke_connector_supervisor_middleware() -> None:
    smoke.assert_connector_supervisor_middleware()


def test_smoke_observe_audit_repair() -> None:
    smoke.assert_observe_audit_repair()


def test_smoke_plan_execute_other_and_output() -> None:
    smoke.assert_plan_execute_other_and_output()
