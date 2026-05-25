"""Release-gate mechanics that must stay fast and framework-only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from framework_helpers import ROOT, assert_no_release_gate_runaways, run_checked


pytestmark = [pytest.mark.release, pytest.mark.timeout(180)]


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
            "examples",
            "libs/xctx",
            "libs/xctx_live",
            "libs/xctx_connectors/runtime.py",
            "libs/xctx_connectors/middleware.py",
            "tests",
        ]
    )


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _target_entrypoint(install_dir: Path) -> Path:
    if os.name == "nt":
        return install_dir / "Scripts" / "xctx.exe"
    return install_dir / "bin" / "xctx"


def _assert_installed_json_smoke(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    expected_record_type: str,
    expected_cmdline_arg: str,
) -> dict:
    proc = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, (
        "installed xctx smoke failed\n"
        f"args={args}\nreturncode={proc.returncode}\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
    records = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert records
    assert records[0]["ok"] is True
    assert records[0]["record_type"] == expected_record_type
    assert records[0]["cmdline_arg"] == expected_cmdline_arg
    return records[0]


def _runtime_snapshot(runtime_dir: Path) -> list[Path]:
    if not runtime_dir.exists():
        return []
    return sorted(path.relative_to(runtime_dir) for path in runtime_dir.rglob("*"))


def test_package_install_entrypoint_smoke(tmp_path: Path) -> None:
    venv_dir = tmp_path / "venv"
    install_dir = tmp_path / "installed"
    runtime_dir = tmp_path / "runtime"
    source_runtime = ROOT / ".xctx_runtime"
    source_runtime_before = _runtime_snapshot(source_runtime)
    run_checked([sys.executable, "-m", "venv", str(venv_dir)], timeout=60)
    package_python = _venv_python(venv_dir)
    run_checked(
        [
            str(package_python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(install_dir),
            str(ROOT),
        ],
        timeout=180,
    )

    entrypoint = _target_entrypoint(install_dir)
    assert entrypoint.exists(), f"installed xctx entrypoint missing: {entrypoint}"
    env = {**os.environ, "PYTHONPATH": str(install_dir), "XCTX_RUNTIME_DIR": str(runtime_dir)}
    _assert_installed_json_smoke(
        [sys.executable, str(entrypoint), "--json", "discover"],
        cwd=tmp_path,
        env=env,
        expected_record_type="discovery",
        expected_cmdline_arg="--json discover",
    )
    _assert_installed_json_smoke(
        [sys.executable, "-m", "xctx", "--json", "discover"],
        cwd=tmp_path,
        env=env,
        expected_record_type="discovery",
        expected_cmdline_arg="--json discover",
    )
    market_observation = _assert_installed_json_smoke(
        [
            sys.executable,
            str(entrypoint),
            "--json",
            "observe",
            "stock_intelligence_hub::market_data_gateway",
            "AAPL",
            "--bars",
            "1",
        ],
        cwd=tmp_path,
        env=env,
        expected_record_type="observation",
        expected_cmdline_arg="--json observe stock_intelligence_hub::market_data_gateway AAPL --bars 1",
    )
    assert (
        market_observation["results"]["live_data"]["object_type"]
        == "market_data_gateway_market_series_range_observation"
    )
    source_runtime_after = _runtime_snapshot(source_runtime)
    assert source_runtime_after == source_runtime_before
    assert not (tmp_path / ".xctx_runtime").exists()
    assert_no_release_gate_runaways()


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
