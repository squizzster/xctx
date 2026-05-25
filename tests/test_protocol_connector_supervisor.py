"""Pytest-collected connector supervisor protocol checks."""

from __future__ import annotations

import json
import subprocess

import pytest

from framework_helpers import load_script_module


connector = load_script_module("protocol_connector_supervisor")
pytestmark = [pytest.mark.integration, pytest.mark.release, pytest.mark.timeout(120)]


def test_middleware_returns_json_without_xctx_env() -> None:
    connector.test_middleware_returns_json_without_xctx_env()


def test_safe_path_blocks_escape() -> None:
    connector.test_safe_path_blocks_escape()


def test_domain_adapter_import_path_exists() -> None:
    connector.test_domain_adapter_import_path_exists()


def test_xctx_invokes_connector_supervisor_out_of_process() -> None:
    connector.test_xctx_invokes_connector_supervisor_out_of_process()


def test_live_entrypoint_must_use_connector_supervisor() -> None:
    connector.test_live_entrypoint_must_use_connector_supervisor()


def test_passthrough_target_entrypoint_stays_inside_workspace() -> None:
    connector.test_passthrough_target_entrypoint_stays_inside_workspace()


def test_generic_connector_runtime_has_no_file_manager_implementation() -> None:
    connector.test_generic_connector_runtime_has_no_file_manager_implementation()


def test_root_audit_does_not_import_scoped_external_command_adapter() -> None:
    connector.test_root_audit_does_not_import_scoped_external_command_adapter()


def test_xctx_native_passthrough_stays_transparent() -> None:
    connector.test_xctx_native_passthrough_stays_transparent()


def test_xctx_native_passthrough_failure_has_shape_guarantee() -> None:
    connector.test_xctx_native_passthrough_failure_has_shape_guarantee()


def test_xctx_native_passthrough_failure_hides_argv_until_full_shape() -> None:
    connector.test_xctx_native_passthrough_failure_hides_argv_until_full_shape()


def test_external_command_filesystem_discovery_and_observation() -> None:
    connector.test_external_command_filesystem_discovery_and_observation()


def test_external_command_filesystem_always_shapes_failures() -> None:
    connector.test_external_command_filesystem_always_shapes_failures()


def test_connector_supervisor_cli_directory_list() -> None:
    cli = subprocess.run(
        [
            str(connector.XCTX),
            "--json",
            "discover",
            "file_manager::home_directory",
            "list_directories",
        ],
        cwd=connector.ROOT,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr + cli.stdout
    assert cli.stderr == "", cli.stderr
    assert json.loads(cli.stdout)["results"]["live_data"]["object_type"] == "external_command_filesystem_directory_list"
