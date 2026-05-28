"""Regression tests for the hardened xctx framework refactor."""

from __future__ import annotations

import sys

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


def test_protocol_option_helpers_live_in_focused_modules() -> None:
    ensure_libs_path()
    from xctx.protocol import option_encoding, option_specs, option_surface  # noqa: PLC0415

    assert callable(option_specs.collect_cli_option_values)
    assert callable(option_specs.command_cli_option_specs)
    assert callable(option_specs.target_cli_option_specs)
    assert callable(option_encoding.encode_cli_options_for_target)
    assert callable(option_surface.option_config_checks)
    assert callable(option_surface.option_surface)


def test_format_cmd_preserves_unknown_placeholders_in_guidance_templates() -> None:
    ensure_libs_path()
    from xctx.protocol.formatting import format_cmd  # noqa: PLC0415

    assert (
        format_cmd("./xctx discover {agent_domain}::{missing}", agent_domain="stock_intelligence_hub")
        == "./xctx discover stock_intelligence_hub::{missing}"
    )


def test_repair_result_uses_agent_subdomain_domain_level_for_subdomain_targets() -> None:
    rc, payload = run_runtime_json(["repair", "down_for_maintenance:stock_intelligence_hub::fundamentals_gateway"])

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"] == "down_for_maintenance"
    assert payload["domain_level"] == "agent_subdomain"
    assert payload["results"]["target"] == "stock_intelligence_hub::fundamentals_gateway"


def test_plan_store_rejects_malformed_receipts_before_writing(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.store.plans import read_plan, write_plan  # noqa: PLC0415

    monkeypatch.setenv("XCTX_RUNTIME_DIR", str(tmp_path))
    store = load_store(root=ROOT)

    with pytest.raises(ValueError, match="64-character lowercase hex digest"):
        write_plan(store, {"receipt_sha256": "not-a-receipt"})

    assert read_plan(store, "../not-a-receipt") is None


def test_connector_runtime_rejects_zero_max_output_bytes_instead_of_defaulting() -> None:
    ensure_libs_path()
    from xctx_connectors import runtime as connector_runtime  # noqa: PLC0415

    with pytest.raises(ValueError, match="max_output_bytes must be between"):
        connector_runtime.run_external([sys.executable, "-c", "print('ok')"], timeout=1, max_output_bytes=0)


def test_capture_process_treats_missing_returncode_as_not_ok() -> None:
    ensure_libs_path()
    from xctx.process.capture import CapturedProcess  # noqa: PLC0415

    assert CapturedProcess(argv=("adapter",), returncode=None, timed_out=False, stdout="", stderr="").ok is False


def test_connector_runtime_preserves_missing_returncode(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_libs_path()
    from xctx.process.capture import CapturedProcess  # noqa: PLC0415
    from xctx_connectors import runtime as connector_runtime  # noqa: PLC0415

    monkeypatch.setattr(
        connector_runtime,
        "capture_process",
        lambda *_args, **_kwargs: CapturedProcess(
            argv=("adapter",),
            returncode=None,
            timed_out=False,
            stdout="",
            stderr="missing returncode",
        ),
    )

    result = connector_runtime.run_external(["adapter"], timeout=1, max_output_bytes=1024)

    assert result["ok"] is False
    assert result["exit_code"] is None
    assert result["error"] == "missing returncode"


def test_cmdline_arg_shell_quotes_scoped_values_with_spaces() -> None:
    rc, payload = run_runtime_json(["observe", "stock_intelligence_hub::equity_filing", "form:DEF 14A"])

    assert rc == 0
    assert payload["cmdline_arg"] == "--json observe stock_intelligence_hub::equity_filing 'form:DEF 14A'"


def test_global_options_do_not_strip_command_arguments_after_command_token() -> None:
    rc, payload = run_runtime_json(
        [
            "plan",
            "guess_the_number_game::choose_random_number::choose_between_bounds",
            "--minimum",
            "1",
            "--maximum",
            "2",
            "--json",
        ]
    )

    assert rc == 1
    assert payload["error"] == "unsupported action option for this action: --json"


def test_workspace_root_uses_explicit_environment_override(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.paths import project_root_from_module  # noqa: PLC0415

    monkeypatch.setenv("XCTX_WORKSPACE", str(ROOT))

    assert project_root_from_module("/tmp/x.py") == ROOT


def test_workspace_root_rejects_invalid_environment_override(tmp_path, monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.paths import project_root_from_module  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    monkeypatch.setenv("XCTX_WORKSPACE", str(tmp_path))

    with pytest.raises(XctxError, match="XCTX_WORKSPACE is not an xctx workspace root"):
        project_root_from_module("/tmp/x.py")


def test_workspace_root_missing_fails_with_actionable_error(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.config.paths import project_root_from_module  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    monkeypatch.delenv("XCTX_WORKSPACE", raising=False)

    with pytest.raises(XctxError, match="could not locate xctx workspace root"):
        project_root_from_module("/tmp/x.py")
