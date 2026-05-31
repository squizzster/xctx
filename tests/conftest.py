"""Pytest fixtures shared by all xctx tests."""

from __future__ import annotations

import os
import shutil
import signal
import tempfile

import pytest

from framework_helpers import ensure_test_process_scope, kill_process_rows, local_gate_process_rows


@pytest.fixture(autouse=True)
def isolate_xctx_runtime_dir(monkeypatch):
    runtime_dir = tempfile.mkdtemp(prefix="xctx_pytest_runtime_")
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(runtime_dir))
    try:
        yield runtime_dir
    finally:
        shutil.rmtree(runtime_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def assert_no_xctx_child_process_leaks():
    yield
    runaways = local_gate_process_rows()
    if not runaways:
        return
    kill_process_rows(runaways)
    pytest.fail(
        "test left xctx subprocesses running:\n"
        + "\n".join(
            f"pid={row.pid} ppid={row.ppid} pgid={row.pgid} cmd={row.cmd}" for row in runaways
        )
    )


def pytest_configure(config) -> None:
    ensure_test_process_scope()
    config.addinivalue_line("markers", "unit: fast framework/unit coverage")
    config.addinivalue_line("markers", "integration: connector/subprocess integration coverage")
    config.addinivalue_line("markers", "local_gate: required local development gate coverage")
    config.addinivalue_line("markers", "live_edgar: opt-in live SEC EDGAR coverage")
    config.addinivalue_line("markers", "slow: slow protocol matrix coverage")
    config.addinivalue_line("markers", "timeout(seconds): per-test timeout in seconds")


@pytest.fixture(autouse=True)
def enforce_test_timeout(request):
    marker = request.node.get_closest_marker("timeout")
    timeout_seconds = int(marker.args[0]) if marker and marker.args else 300
    if os.environ.get("XCTX_TEST_ENABLE_SIGNAL_TIMEOUTS") != "1" or not hasattr(signal, "SIGALRM"):
        yield
        return

    def timeout_handler(_signum, _frame) -> None:
        pytest.fail(f"test timed out after {timeout_seconds} seconds")

    previous_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
