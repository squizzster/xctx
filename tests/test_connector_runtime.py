"""Framework connector-runtime boundary tests."""

from __future__ import annotations

import json
import sys

import pytest

from framework_helpers import ROOT, ensure_libs_path


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


def test_connector_subprocess_env_does_not_inherit_pythonpath_or_pythonhome(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.process.env import SAFE_ENV_KEYS, sanitized_env  # noqa: PLC0415

    monkeypatch.setenv("PYTHONPATH", "/tmp/xctx-poison-path")
    monkeypatch.setenv("PYTHONHOME", "/tmp/xctx-poison-home")

    env = sanitized_env({})

    assert "PYTHONPATH" not in SAFE_ENV_KEYS
    assert "PYTHONHOME" not in SAFE_ENV_KEYS
    assert "/tmp/xctx-poison-path" not in env.get("PYTHONPATH", "")
    assert "PYTHONHOME" not in env


def test_connector_env_passthrough_is_explicit_and_xctx_scoped(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.ports import external_command  # noqa: PLC0415
    from xctx_connectors import middleware  # noqa: PLC0415

    monkeypatch.setenv("XCTX_TEST_CONNECTOR_TOKEN", "test identity")
    monkeypatch.setenv("UNSAFE_SECRET", "must not pass")
    subdomain = {
        "_domain_id": "generic_domain",
        "id": "generic_subdomain",
        "connector": {
            "kind": "xctx_native_passthrough",
            "env_passthrough": ["XCTX_TEST_CONNECTOR_TOKEN", "UNSAFE_SECRET"],
        },
    }

    parent_env = external_command._adapter_env({"root": ROOT}, subdomain)
    assert parent_env["XCTX_TEST_CONNECTOR_TOKEN"] == "test identity"
    assert "UNSAFE_SECRET" not in parent_env

    context = middleware._context_from_subdomain(ROOT, subdomain)
    child_env = middleware._passthrough_env(context)
    assert child_env["XCTX_TEST_CONNECTOR_TOKEN"] == "test identity"
    assert "UNSAFE_SECRET" not in child_env


def test_readonly_mapping_deep_freezes_nested_values() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    frozen = runtime.readonly_mapping(
        {
            "nested": {
                "items": [{"name": "alpha"}],
                "labels": {"one", "two"},
            },
            "scalar": 1,
        }
    )

    assert frozen["nested"]["items"][0]["name"] == "alpha"
    assert isinstance(frozen["nested"]["items"], tuple)
    assert isinstance(frozen["nested"]["labels"], frozenset)

    with pytest.raises(TypeError):
        frozen["scalar"] = 2
    with pytest.raises(TypeError):
        frozen["nested"]["new"] = "value"
    with pytest.raises(TypeError):
        frozen["nested"]["items"][0]["name"] = "beta"


def test_middleware_connector_context_is_deep_frozen() -> None:
    ensure_libs_path()
    from xctx_connectors import middleware  # noqa: PLC0415

    context = middleware._context_from_subdomain(
        ROOT,
        {
            "_domain_id": "demo_domain",
            "id": "demo_subdomain",
            "connector": {
                "kind": "xctx_native_passthrough",
                "limits": {"paths": ["one", "two"]},
            },
            "actions": {"observe": {"cli_options": [{"flags": ["--demo"], "dest": "demo"}]}},
        },
    )

    assert context.connector_config["limits"]["paths"] == ("one", "two")
    assert context.subdomain_config["actions"]["observe"]["cli_options"][0]["dest"] == "demo"
    with pytest.raises(TypeError):
        context.connector_config["limits"]["paths"][0] = "changed"
    with pytest.raises(TypeError):
        context.subdomain_config["actions"]["observe"]["cli_options"][0]["dest"] = "changed"


def test_connector_limits_from_config_coerces_values_and_applies_defaults() -> None:
    ensure_libs_path()
    from xctx.process.limits import DEFAULT_MAX_OUTPUT_BYTES  # noqa: PLC0415
    from xctx_connectors import runtime  # noqa: PLC0415

    explicit = runtime.ConnectorLimits.from_config({"timeout_seconds": "2.5", "max_output_bytes": "2048"})
    defaulted = runtime.ConnectorLimits.from_config({})

    assert explicit.timeout_seconds == 2.5
    assert explicit.max_output_bytes == 2048
    assert defaulted.timeout_seconds == 30
    assert defaulted.max_output_bytes == DEFAULT_MAX_OUTPUT_BYTES


def test_connector_limits_reject_invalid_values() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    with pytest.raises(ValueError, match="connector.timeout_seconds"):
        runtime.ConnectorLimits.from_config({"timeout_seconds": 0})
    with pytest.raises(ValueError, match="connector.max_output_bytes"):
        runtime.ConnectorLimits.from_config({"max_output_bytes": 10})


def test_connector_limits_from_values_preserves_call_site_error_labels() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    with pytest.raises(ValueError, match="entrypoint.timeout_seconds"):
        runtime.ConnectorLimits.from_values(timeout_seconds="bad", timeout_label="entrypoint.timeout_seconds")
    with pytest.raises(ValueError, match="passthrough.max_output_bytes"):
        runtime.ConnectorLimits.from_values(max_output_bytes="bad", max_output_label="passthrough.max_output_bytes")


def test_connector_context_default_limits_are_validated_contract_object() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    context = runtime.ConnectorContext(
        workspace_root=ROOT,
        domain_id="demo_domain",
        subdomain_id="demo_subdomain",
        subdomain_config=runtime.readonly_mapping({"id": "demo_subdomain"}),
        connector_config=runtime.readonly_mapping({"kind": "external_command"}),
    )

    assert isinstance(context.limits, runtime.ConnectorLimits)
    assert context.limits.timeout_seconds == 30
    assert context.limits.max_output_bytes >= 1024


def test_middleware_connector_context_carries_validated_limits() -> None:
    ensure_libs_path()
    from xctx_connectors import middleware  # noqa: PLC0415

    context = middleware._context_from_subdomain(
        ROOT,
        {
            "_domain_id": "demo_domain",
            "id": "demo_subdomain",
            "connector": {
                "kind": "xctx_native_passthrough",
                "timeout_seconds": "4.5",
                "max_output_bytes": "4096",
            },
            "actions": {},
        },
    )

    assert context.limits.timeout_seconds == 4.5
    assert context.limits.max_output_bytes == 4096


def test_parent_writes_resolved_connector_context_snapshot(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.core import resolve_subdomain  # noqa: PLC0415
    from xctx.ports import external_command  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    subdomain = resolve_subdomain(store, "guess_the_number_game", "choose_random_number")

    path, payload = external_command._write_resolved_connector_context(store, subdomain, ["discover"])
    env = external_command._adapter_env(
        store,
        subdomain,
        resolved_context_path=path,
        config_fingerprint=str(payload["config_fingerprint"]),
    )

    assert path.exists()
    assert path.parent == tmp_path / "resolved_contexts"
    assert path.stat().st_mode & 0o777 == 0o600
    assert payload["domain_id"] == "guess_the_number_game"
    assert payload["subdomain_id"] == "choose_random_number"
    assert len(payload["config_fingerprint"]) == 64
    assert env["XCTX_RESOLVED_CONTEXT_FILE"] == str(path)
    assert env["XCTX_CONFIG_FINGERPRINT"] == payload["config_fingerprint"]


def test_middleware_uses_resolved_context_without_reloading_store(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.core import resolve_subdomain  # noqa: PLC0415
    from xctx.ports import external_command  # noqa: PLC0415
    from xctx_connectors import middleware  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    subdomain = resolve_subdomain(store, "guess_the_number_game", "choose_random_number")
    path, payload = external_command._write_resolved_connector_context(store, subdomain, ["discover"])
    monkeypatch.setenv("XCTX_AGENT_DOMAIN", "guess_the_number_game")
    monkeypatch.setenv("XCTX_AGENT_SUBDOMAIN", "choose_random_number")
    monkeypatch.setenv("XCTX_RESOLVED_CONTEXT_FILE", str(path))
    monkeypatch.setenv("XCTX_CONFIG_FINGERPRINT", str(payload["config_fingerprint"]))

    def fail_load_store(*_args, **_kwargs):
        raise AssertionError("middleware should not reload YAML when a resolved context is present")

    monkeypatch.setattr(middleware, "load_store", fail_load_store)

    resolved = middleware._subdomain_from_env(ROOT)

    assert resolved["id"] == "choose_random_number"
    assert resolved["_domain_id"] == "guess_the_number_game"


def test_middleware_rejects_resolved_context_fingerprint_mismatch(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.core import resolve_subdomain  # noqa: PLC0415
    from xctx.ports import external_command  # noqa: PLC0415
    from xctx_connectors import middleware  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    subdomain = resolve_subdomain(store, "guess_the_number_game", "choose_random_number")
    path, _payload = external_command._write_resolved_connector_context(store, subdomain, ["discover"])
    monkeypatch.setenv("XCTX_AGENT_DOMAIN", "guess_the_number_game")
    monkeypatch.setenv("XCTX_AGENT_SUBDOMAIN", "choose_random_number")
    monkeypatch.setenv("XCTX_RESOLVED_CONTEXT_FILE", str(path))
    monkeypatch.setenv("XCTX_CONFIG_FINGERPRINT", "0" * 64)

    with pytest.raises(ValueError, match="fingerprint mismatch"):
        middleware._subdomain_from_env(ROOT)


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
    assert result["stdout_truncated"] is True
    assert result["stdout_captured_bytes"] == 1024
    assert result["stdout_total_bytes"] > result["stdout_captured_bytes"]
    assert result["max_output_bytes"] == 1024
    assert "should_not_leak" not in result["stdout"]
    assert "secret=None" in result["stdout"]
    assert "domain=stock_intelligence_hub" in result["stdout"]


def test_capture_process_reports_stdout_and_stderr_truncation_metadata() -> None:
    ensure_libs_path()
    from xctx.process.capture import capture_process  # noqa: PLC0415

    captured = capture_process(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('o' * 2048); sys.stderr.write('e' * 1536)",
        ],
        timeout=5,
        max_output_bytes=1024,
    )

    assert captured.ok is True
    assert len(captured.stdout) == 1024
    assert len(captured.stderr) == 1024
    assert captured.stdout_truncated is True
    assert captured.stderr_truncated is True
    assert captured.stdout_captured_bytes == 1024
    assert captured.stderr_captured_bytes == 1024
    assert captured.stdout_total_bytes == 2048
    assert captured.stderr_total_bytes == 1536
    assert captured.max_output_bytes == 1024


def test_command_status_from_external_result_includes_truncation_metadata() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    result = runtime.run_external(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 2048)"],
        timeout=5,
        max_output_bytes=1024,
    )
    status = runtime.command_status_from_external_result(result)

    assert status["stdout_truncated"] is True
    assert status["stdout_captured_bytes"] == 1024
    assert status["stdout_total_bytes"] == 2048
    assert status["max_output_bytes"] == 1024


def test_connector_stdout_truncation_reports_limit_instead_of_invalid_json(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.core import resolve_subdomain  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.ports import external_command  # noqa: PLC0415
    from xctx.process.capture import CapturedProcess  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    subdomain = resolve_subdomain(store, "guess_the_number_game", "choose_random_number")

    def truncated_stdout(*_args: object, **_kwargs: object) -> CapturedProcess:
        return CapturedProcess(
            argv=("connector",),
            returncode=0,
            timed_out=False,
            stdout='{"object_type":',
            stderr="",
            stdout_truncated=True,
            stdout_captured_bytes=64,
            stdout_total_bytes=2048,
            max_output_bytes=64,
        )

    monkeypatch.setattr(external_command, "capture_process", truncated_stdout)

    with pytest.raises(XctxError, match="stdout exceeded max_output_bytes"):
        external_command.call_external_command(store, subdomain, ["discover"])


def test_external_command_port_uses_entrypoint_connector_limits(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.core import resolve_subdomain  # noqa: PLC0415
    from xctx.ports import external_command  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    subdomain = resolve_subdomain(store, "guess_the_number_game", "choose_random_number")
    subdomain["entrypoint"] = {**subdomain["entrypoint"], "timeout_seconds": "2.5", "max_output_bytes": "4096"}
    captured: dict[str, object] = {}

    def fake_subprocess(*args: object) -> tuple[int, str, str, dict[str, object]]:
        captured["timeout"] = args[4]
        captured["max_output_bytes"] = args[5]
        return 0, '{"object_type":"ok"}', "", {"stdout_truncated": False, "max_output_bytes": args[5]}

    monkeypatch.setattr(external_command, "_call_python_entrypoint_subprocess", fake_subprocess)

    payload = external_command.call_external_command(store, subdomain, ["discover"])

    assert payload["object_type"] == "ok"
    assert captured == {"timeout": 2.5, "max_output_bytes": 4096}


def test_connector_stderr_truncation_metadata_is_preserved_on_failure() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    result = runtime.run_external(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('e' * 2048); raise SystemExit(2)",
        ],
        timeout=5,
        max_output_bytes=1024,
    )
    status = runtime.command_status_from_external_result(result)

    assert result["ok"] is False
    assert result["stderr_truncated"] is True
    assert result["stderr_captured_bytes"] == 1024
    assert result["stderr_total_bytes"] == 2048
    assert status["stderr_truncated"] is True
    assert status["stderr_total_bytes"] == 2048


def test_external_command_nonzero_truncated_stderr_reports_output_limit(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.domain.core import resolve_subdomain  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415
    from xctx.ports import external_command  # noqa: PLC0415
    from xctx.process.capture import CapturedProcess  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)
    subdomain = resolve_subdomain(store, "guess_the_number_game", "choose_random_number")

    def truncated_stderr(*_args: object, **_kwargs: object) -> CapturedProcess:
        return CapturedProcess(
            argv=("connector",),
            returncode=2,
            timed_out=False,
            stdout="",
            stderr="e" * 64,
            stderr_truncated=True,
            stderr_captured_bytes=64,
            stderr_total_bytes=2048,
            max_output_bytes=64,
        )

    monkeypatch.setattr(external_command, "capture_process", truncated_stderr)

    with pytest.raises(XctxError, match="stderr exceeded max_output_bytes"):
        external_command.call_external_command(store, subdomain, ["discover"])


def _passthrough_test_context() -> object:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    connector = runtime.readonly_mapping(
        {
            "kind": "xctx_native_passthrough",
            "target_entrypoint": "connector_supervisor.py",
            "timeout_seconds": 5,
            "max_output_bytes": 1024,
        }
    )
    return runtime.ConnectorContext(
        workspace_root=ROOT,
        domain_id="demo_domain",
        subdomain_id="demo_subdomain",
        subdomain_config=runtime.readonly_mapping({"id": "demo_subdomain", "connector": dict(connector)}),
        connector_config=connector,
        limits=runtime.ConnectorLimits.from_config(connector),
        detail_level="max",
    )


def test_passthrough_success_attaches_middleware_connector_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx_connectors import middleware  # noqa: PLC0415

    def fake_run_external(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "ok": True,
            "timed_out": False,
            "exit_code": 0,
            "stdout": json.dumps({"object_type": "demo_payload", "found": True}),
            "stderr": "",
        }

    monkeypatch.setattr(middleware.runtime, "run_external", fake_run_external)

    payload = middleware._passthrough(_passthrough_test_context(), ["discover"], compact=True)

    assert payload["object_type"] == "demo_payload"
    assert payload["found"] is True
    assert payload["connector"]["kind"] == "xctx_native_passthrough"
    assert payload["connector"]["adapter_ref"] == "demo_domain::demo_subdomain"


def test_passthrough_success_rejects_target_owned_connector_spoof(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx_connectors import middleware  # noqa: PLC0415

    def fake_run_external(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "ok": True,
            "timed_out": False,
            "exit_code": 0,
            "stdout": json.dumps(
                {
                    "object_type": "demo_payload",
                    "connector": {"kind": "spoofed"},
                    "command_status": {"ok": True},
                }
            ),
            "stderr": "",
        }

    monkeypatch.setattr(middleware.runtime, "run_external", fake_run_external)

    payload = middleware._passthrough(_passthrough_test_context(), ["discover"], compact=True)

    assert payload["object_type"] == "xctx_connector_error"
    assert payload["found"] is False
    assert "framework-owned keys: command_status, connector" in payload["command_status"]["error"]
    assert payload["connector"]["kind"] == "xctx_native_passthrough"


def test_passthrough_failure_preserves_capture_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx_connectors import middleware  # noqa: PLC0415

    def fake_run_external(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "ok": False,
            "timed_out": False,
            "exit_code": 2,
            "stdout": "",
            "stderr": "e" * 64,
            "stderr_truncated": True,
            "stderr_captured_bytes": 64,
            "stderr_total_bytes": 2048,
            "max_output_bytes": 64,
        }

    monkeypatch.setattr(middleware.runtime, "run_external", fake_run_external)

    payload = middleware._passthrough(_passthrough_test_context(), ["discover"], compact=True)

    assert payload["object_type"] == "xctx_native_passthrough_error"
    assert payload["command_status"]["stderr_truncated"] is True
    assert payload["command_status"]["stderr_captured_bytes"] == 64
    assert payload["command_status"]["stderr_total_bytes"] == 2048


def test_passthrough_uses_context_connector_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx_connectors import middleware  # noqa: PLC0415

    captured_kwargs: dict[str, object] = {}

    def fake_run_external(*_args: object, **kwargs: object) -> dict[str, object]:
        captured_kwargs.update(kwargs)
        return {
            "ok": True,
            "timed_out": False,
            "exit_code": 0,
            "stdout": json.dumps({"object_type": "demo_payload"}),
            "stderr": "",
        }

    monkeypatch.setattr(middleware.runtime, "run_external", fake_run_external)

    middleware._passthrough(_passthrough_test_context(), ["discover"], compact=True)

    assert captured_kwargs["timeout"] == 5
    assert captured_kwargs["max_output_bytes"] == 1024


def test_connector_runtime_rejects_unsafe_subprocess_limits() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime  # noqa: PLC0415

    with pytest.raises(ValueError, match="timeout_seconds"):
        runtime.run_external([sys.executable, "-c", "print('ok')"], timeout=0, max_output_bytes=1024)
    with pytest.raises(ValueError, match="max_output_bytes"):
        runtime.run_external([sys.executable, "-c", "print('ok')"], timeout=1, max_output_bytes=10)


def test_connector_runtime_uses_connector_limit_defaults_when_output_limit_omitted() -> None:
    ensure_libs_path()
    from xctx.process.limits import DEFAULT_MAX_OUTPUT_BYTES  # noqa: PLC0415
    from xctx_connectors import runtime  # noqa: PLC0415

    result = runtime.run_external([sys.executable, "-c", "print('ok')"], timeout=1)

    assert result["ok"] is True
    assert result["max_output_bytes"] == DEFAULT_MAX_OUTPUT_BYTES
