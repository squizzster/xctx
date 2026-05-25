"""Pytest-collected full protocol pressure matrix."""

from __future__ import annotations

from framework_helpers import load_script_module


pressure = load_script_module("protocol_pressure_pro")


def test_protocol_pressure_full_matrix() -> None:
    assert pressure.main() == 0
