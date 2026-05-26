"""Local development gate mechanics for framework validation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from framework_helpers import (
    ROOT,
    TEST_OWNER_PID_ENV,
    TEST_RUN_ID_ENV,
    ProcessRow,
    assert_no_local_gate_runaways,
    kill_process_rows,
    local_gate_process_rows,
    run_checked,
)


pytestmark = [pytest.mark.local_gate, pytest.mark.timeout(180)]


def test_local_gate_process_detection_is_scoped_to_current_pytest_run(monkeypatch) -> None:
    monkeypatch.setenv(TEST_RUN_ID_ENV, "run-a")
    monkeypatch.setenv(TEST_OWNER_PID_ENV, "100")
    rows = [
        ProcessRow(200, 1, 200, "python connector_supervisor.py observe AAPL"),
        ProcessRow(201, 1, 201, "python connector_supervisor.py observe MSFT"),
        ProcessRow(202, 1, 202, "python unrelated.py"),
    ]
    env_by_pid = {
        200: {TEST_RUN_ID_ENV: "run-a", TEST_OWNER_PID_ENV: "100"},
        201: {TEST_RUN_ID_ENV: "run-b", TEST_OWNER_PID_ENV: "999"},
    }
    monkeypatch.setattr("framework_helpers.process_environ", lambda pid: env_by_pid.get(pid, {}))

    assert local_gate_process_rows(rows) == [rows[0]]


def test_local_gate_cleanup_can_kill_owned_same_group_process(monkeypatch) -> None:
    killed_groups: list[int] = []
    killed_pids: list[int] = []
    monkeypatch.setattr("framework_helpers.os.getpid", lambda: 100)
    monkeypatch.setattr("framework_helpers.os.getpgrp", lambda: 50)
    monkeypatch.setattr("framework_helpers.os.killpg", lambda pgid, _signal: killed_groups.append(pgid))
    monkeypatch.setattr("framework_helpers.os.kill", lambda pid, _signal: killed_pids.append(pid))

    kill_process_rows(
        [
            ProcessRow(200, 100, 50, "python connector_supervisor.py observe AAPL"),
            ProcessRow(201, 100, 201, "python connector_supervisor.py observe MSFT"),
        ]
    )

    assert killed_groups == [201]
    assert killed_pids == [200, 201]


def test_yaml_surface_validator() -> None:
    run_checked([sys.executable, ".agents/skills/xctx-yaml-config/scripts/check_xctx_yaml_surface.py"])


def test_compileall_local_gate_paths() -> None:
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


def _assert_or_prepare_build_dependencies(package_python: Path, source_dir: Path) -> None:
    probe = subprocess.run(
        [
            str(package_python),
            "-c",
            "import setuptools, wheel, yaml",
        ],
        cwd=source_dir,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if probe.returncode == 0:
        return
    if os.environ.get("XCTX_PACKAGE_SMOKE_ALLOW_NETWORK") != "1":
        pytest.skip(
            "package smoke build dependencies are not locally available; "
            "set XCTX_PACKAGE_SMOKE_ALLOW_NETWORK=1 to run the online dependency install path"
        )

    build_deps_proc = subprocess.run(
        [str(package_python), "-m", "pip", "install", "setuptools>=68", "wheel", "PyYAML>=6.0"],
        cwd=source_dir,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert build_deps_proc.returncode == 0, (
        "package smoke build dependency install failed\n"
        f"returncode={build_deps_proc.returncode}\nSTDOUT={build_deps_proc.stdout}\nSTDERR={build_deps_proc.stderr}"
    )


def _assert_installed_json_smoke(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    expected_record_type: str,
    expected_cmdline_arg: str,
) -> dict:
    try:
        captured = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        raise AssertionError(
            "installed xctx smoke timed out\n"
            f"args={args}\nSTDOUT={stdout}\nSTDERR={stderr}"
        ) from exc
    assert captured.returncode == 0, (
        "installed xctx smoke failed\n"
        f"args={args}\nreturncode={captured.returncode}\nSTDOUT={captured.stdout}\nSTDERR={captured.stderr}"
    )
    records = [json.loads(line) for line in captured.stdout.splitlines() if line.strip()]
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
    source_dir = tmp_path / "source"
    shutil.copytree(
        ROOT,
        source_dir,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            ".xctx_runtime",
            "__pycache__",
            "*.pyc",
            "build",
            "*.egg-info",
        ),
    )
    venv_dir = tmp_path / "venv"
    venv_proc = subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)],
        cwd=source_dir,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert venv_proc.returncode == 0, (
        "test venv creation failed\n"
        f"returncode={venv_proc.returncode}\nSTDOUT={venv_proc.stdout}\nSTDERR={venv_proc.stderr}"
    )
    package_python = _venv_python(venv_dir)
    _assert_or_prepare_build_dependencies(package_python, source_dir)
    install_dir = tmp_path / "installed"
    runtime_dir = tmp_path / "runtime"
    source_runtime = ROOT / ".xctx_runtime"
    source_runtime_before = _runtime_snapshot(source_runtime)
    install_proc = subprocess.run(
        [
            str(package_python),
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            "--no-deps",
            "--target",
            str(install_dir),
            str(source_dir),
        ],
        cwd=source_dir,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert install_proc.returncode == 0, (
        "package install failed\n"
        f"returncode={install_proc.returncode}\nSTDOUT={install_proc.stdout}\nSTDERR={install_proc.stderr}"
    )

    entrypoint = _target_entrypoint(install_dir)
    assert entrypoint.exists(), f"installed xctx entrypoint missing: {entrypoint}"
    env = {**os.environ, "PYTHONPATH": str(install_dir), "XCTX_RUNTIME_DIR": str(runtime_dir)}
    _assert_installed_json_smoke(
        [str(package_python), str(entrypoint), "--json", "discover"],
        cwd=tmp_path,
        env=env,
        expected_record_type="discovery",
        expected_cmdline_arg="--json discover",
    )
    _assert_installed_json_smoke(
        [str(package_python), "-m", "xctx", "--json", "discover"],
        cwd=tmp_path,
        env=env,
        expected_record_type="discovery",
        expected_cmdline_arg="--json discover",
    )
    market_observation = _assert_installed_json_smoke(
        [
            str(package_python),
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
    assert_no_local_gate_runaways()


def test_package_smoke_dependency_probe_skips_offline_when_build_deps_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append([str(item) for item in args])
        return subprocess.CompletedProcess(args, 1, "", "missing build dependency")

    monkeypatch.delenv("XCTX_PACKAGE_SMOKE_ALLOW_NETWORK", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(pytest.skip.Exception):
        _assert_or_prepare_build_dependencies(Path("/tmp/fake-python"), tmp_path)

    assert len(calls) == 1
    assert calls[0][1] == "-c"


def test_package_smoke_dependency_probe_installs_only_when_network_is_explicitly_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        call = [str(item) for item in args]
        calls.append(call)
        returncode = 1 if call[1] == "-c" else 0
        return subprocess.CompletedProcess(args, returncode, "", "missing build dependency" if returncode else "")

    monkeypatch.setenv("XCTX_PACKAGE_SMOKE_ALLOW_NETWORK", "1")
    monkeypatch.setattr(subprocess, "run", fake_run)

    _assert_or_prepare_build_dependencies(Path("/tmp/fake-python"), tmp_path)

    assert len(calls) == 2
    assert calls[1][1:4] == ["-m", "pip", "install"]


def test_local_gate_timeout_cleans_detached_children() -> None:
    child_code = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', "
        "\"import time; print('xctx_local_gate_detached_child', flush=True); time.sleep(60)\"], "
        "start_new_session=True); "
        "time.sleep(60)"
    )
    with pytest.raises(AssertionError, match="command timed out"):
        run_checked([sys.executable, "-c", child_code], timeout=1)
    assert_no_local_gate_runaways()


def test_package_version_matches_project_metadata() -> None:
    from framework_helpers import ensure_libs_path

    ensure_libs_path()
    import xctx  # noqa: PLC0415

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert xctx.__version__ == pyproject["project"]["version"]
