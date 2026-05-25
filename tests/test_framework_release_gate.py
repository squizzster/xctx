"""Release-gate mechanics that must stay fast and framework-only."""

from __future__ import annotations

import sys

import pytest

from framework_helpers import ROOT, assert_no_release_gate_runaways, run_checked


def test_yaml_surface_validator() -> None:
    run_checked([sys.executable, ".agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py"])


def test_compileall_release_paths() -> None:
    run_checked(
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "bin",
            "connector_supervisor.py",
            "libs/xctx",
            "libs/xctx_connectors/runtime.py",
            "libs/xctx_connectors/middleware.py",
            "tests/framework_helpers.py",
            "tests/test_framework_release_gate.py",
            "tests/test_command_contract.py",
            "tests/test_audit_and_options.py",
            "tests/test_connector_runtime.py",
        ]
    )


def test_release_gate_timeout_cleans_detached_children() -> None:
    child_code = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', "
        "\"import time; print('xctx_release_gate_detached_child', flush=True); time.sleep(60)\"], "
        "start_new_session=True); "
        "time.sleep(60)"
    )
    with pytest.raises(AssertionError, match="command timed out"):
        run_checked([sys.executable, "-c", child_code], timeout=1)
    assert_no_release_gate_runaways()


def test_package_version_matches_project_metadata() -> None:
    from framework_helpers import ensure_libs_path

    ensure_libs_path()
    import xctx  # noqa: PLC0415

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "4.2.0"' in pyproject
    assert xctx.__version__ == "4.2.0"
