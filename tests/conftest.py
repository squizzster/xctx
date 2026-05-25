"""Pytest fixtures shared by all xctx tests."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_xctx_runtime_dir(monkeypatch):
    runtime_parent = ROOT / "experiments_tmp"
    runtime_parent.mkdir(exist_ok=True)
    runtime_dir = Path(tempfile.mkdtemp(prefix="pytest_runtime_", dir=runtime_parent))
    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(runtime_dir))
    try:
        yield runtime_dir
    finally:
        shutil.rmtree(runtime_dir, ignore_errors=True)
