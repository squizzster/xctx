"""Framework connector-runtime boundary tests."""

from __future__ import annotations

import sys

import pytest

from framework_helpers import ensure_libs_path


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


def test_runtime_env_is_propagated_through_framework_connector_layers(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.ports import external_command  # noqa: PLC0415
    from xctx_connectors import runtime as connector_runtime  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", "/tmp/xctx-framework-runtime")
    assert "XCTX_RUNTIME_DIR" in external_command.SAFE_ENV_KEYS
    assert "XCTX_RUNTIME_DIR" in connector_runtime.SAFE_ENV_KEYS
    assert (
        external_command._adapter_env({"_domain_id": "domain", "id": "subdomain"})["XCTX_RUNTIME_DIR"]
        == "/tmp/xctx-framework-runtime"
    )
    assert connector_runtime.sanitized_env({})["XCTX_RUNTIME_DIR"] == "/tmp/xctx-framework-runtime"


def test_connector_runtime_sanitizes_env_and_bounds_output() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    code = (
        "import os, sys; "
        "sys.stdout.write('secret=' + str(os.environ.get('SECRET_TOKEN')) + '\\n'); "
        "sys.stdout.write('domain=' + str(os.environ.get('XCTX_AGENT_DOMAIN')) + '\\n'); "
        "sys.stdout.write('x' * 5000)"
    )
    result = runtime.run_external(
        [sys.executable, "-c", code],
        timeout=5,
        max_output_bytes=1024,
        env={"SECRET_TOKEN": "should_not_leak", "XCTX_AGENT_DOMAIN": "stock_intelligence_hub"},
    )
    assert result["ok"] is True
    assert len(result["stdout"]) == 1024
    assert "should_not_leak" not in result["stdout"]
    assert "secret=None" in result["stdout"]
    assert "domain=stock_intelligence_hub" in result["stdout"]


def test_connector_runtime_rejects_unsafe_subprocess_limits() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    with pytest.raises(ValueError, match="timeout_seconds"):
        runtime.run_external([sys.executable, "-c", "print('ok')"], timeout=0, max_output_bytes=1024)
    with pytest.raises(ValueError, match="max_output_bytes"):
        runtime.run_external([sys.executable, "-c", "print('ok')"], timeout=1, max_output_bytes=10)
