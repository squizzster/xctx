"""Shared helpers for framework-level pytest modules."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[1]
RELEASE_GATE_PATTERNS = (
    "connector_supervisor.py",
    "market_data_gateway.py",
    "equity_filings.py",
    "legacy_connector.py",
    "xctx_release_gate_detached_child",
)


class ProcessRow(NamedTuple):
    pid: int
    ppid: int
    pgid: int
    cmd: str


def process_rows() -> list[ProcessRow]:
    proc = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,pgid=,args="],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    rows: list[ProcessRow] = []
    for raw_line in proc.stdout.splitlines():
        parts = raw_line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        try:
            rows.append(ProcessRow(int(parts[0]), int(parts[1]), int(parts[2]), parts[3]))
        except ValueError:
            continue
    return rows


def descendant_rows(root_pid: int, rows: list[ProcessRow]) -> list[ProcessRow]:
    by_parent: dict[int, list[ProcessRow]] = {}
    for row in rows:
        by_parent.setdefault(row.ppid, []).append(row)
    descendants: list[ProcessRow] = []
    stack = list(by_parent.get(root_pid, []))
    while stack:
        row = stack.pop()
        descendants.append(row)
        stack.extend(by_parent.get(row.pid, []))
    return descendants


def release_gate_process_rows(rows: list[ProcessRow] | None = None) -> list[ProcessRow]:
    rows = rows or process_rows()
    current_pid = os.getpid()
    return [
        row
        for row in rows
        if row.pid != current_pid
        and row.ppid != current_pid
        and any(pattern in row.cmd for pattern in RELEASE_GATE_PATTERNS)
    ]


def kill_process_rows(rows: list[ProcessRow]) -> None:
    current_pid = os.getpid()
    current_pgid = os.getpgrp() if hasattr(os, "getpgrp") else None
    for pgid in sorted({row.pgid for row in rows if row.pgid > 1}, reverse=True):
        if current_pgid is not None and pgid == current_pgid:
            continue
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    for row in rows:
        if row.pid in {0, 1, current_pid}:
            continue
        try:
            os.kill(row.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass


def assert_no_release_gate_runaways() -> None:
    runaways = release_gate_process_rows()
    assert not runaways, "release gate left subprocesses running:\n" + "\n".join(
        f"pid={row.pid} ppid={row.ppid} pgid={row.pgid} cmd={row.cmd}" for row in runaways
    )


def run_checked(args: list[str], timeout: int = 120) -> None:
    with tempfile.TemporaryDirectory(prefix="xctx_release_gate_") as runtime_dir:
        env = {**os.environ, "XCTX_RUNTIME_DIR": runtime_dir}
        stdout_path = Path(runtime_dir) / "stdout.txt"
        stderr_path = Path(runtime_dir) / "stderr.txt"
        with stdout_path.open("w+", encoding="utf-8") as stdout_file, stderr_path.open(
            "w+",
            encoding="utf-8",
        ) as stderr_file:
            proc = subprocess.Popen(
                args,
                cwd=ROOT,
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                env=env,
            )
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                rows = process_rows()
                kill_process_rows([row for row in rows if row.pid == proc.pid] + descendant_rows(proc.pid, rows))
                kill_process_rows(release_gate_process_rows(process_rows()))
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read()
                stderr = stderr_file.read()
                raise AssertionError(
                    f"command timed out after {timeout}s: {' '.join(args)}\nSTDOUT={stdout}\nSTDERR={stderr}"
                ) from exc
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read()
            stderr = stderr_file.read()

    assert proc.returncode == 0, (
        f"command failed: {' '.join(args)}\n"
        f"returncode={proc.returncode}\nSTDOUT={stdout}\nSTDERR={stderr}"
    )
    assert_no_release_gate_runaways()


def ensure_libs_path() -> None:
    libs = str(ROOT / "libs")
    if libs not in sys.path:
        sys.path.insert(0, libs)


def load_script_module(script_name: str):
    module_name = f"_xctx_test_script_{script_name}"
    script_path = ROOT / "tests" / f"{script_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load test script {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_runtime_json(args: list[str]) -> tuple[int, dict]:
    ensure_libs_path()
    from xctx.process import runtime  # noqa: PLC0415

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = runtime.main(["--json", *args], root=ROOT)
    assert err.getvalue() == ""
    return rc, json.loads(out.getvalue())
