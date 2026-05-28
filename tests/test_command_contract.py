"""Framework command-surface and obsolete-command removal tests."""

from __future__ import annotations

import json

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.local_gate, pytest.mark.timeout(60)]


ROOT_NEXT_MOVES = [
    {
        "desc": "Discover configured agent domains in this universe.",
        "run_cmd": "./xctx discover",
    },
    {
        "desc": "Audit loaded configuration, live adapters, and offline/maintenance findings.",
        "run_cmd": "./xctx audit root",
    },
]


def assert_protocol_envelope(payload: dict) -> None:
    required = {"version_xctx", "cmdline_arg", "record_type", "ok", "results"}
    assert required <= set(payload), payload


def test_no_stale_status_or_identify_guidance() -> None:
    scanned_paths = [
        ROOT / "bin",
        ROOT / "connector_supervisor.py",
        ROOT / "libs" / "xctx",
        ROOT / "yaml_dynamic_config",
    ]
    stale_fragments = (
        "--system",
        "--agent-domain",
        "--domain",
        "active_system",
        "active_agent_domain",
        "XCTX_ACTIVE_SYSTEM",
        "XCTX_ACTIVE_AGENT_DOMAIN",
        "identity_resolution",
        "identify_query_run_cmd",
    )
    for base in scanned_paths:
        paths = [base] if base.is_file() else list(base.rglob("*"))
        for path in paths:
            if path.is_file() and (path.suffix in {".py", ".yaml", ".yml"} or path.parent == ROOT / "bin"):
                text = path.read_text(encoding="utf-8")
                for fragment in stale_fragments:
                    assert fragment not in text, f"{fragment!r} leaked in {path.relative_to(ROOT)}"


def test_command_policy_contract() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.accessors import command_map_for_group, configured_command_names  # noqa: PLC0415
    from xctx.protocol.command_policy import hidden_commands, visible_commands  # noqa: PLC0415

    store = load_store(root=ROOT)
    assert visible_commands(store) == {"discover", "observe", "plan", "execute", "audit", "repair"}
    assert hidden_commands(store) == {"other"}
    configured = configured_command_names(store)
    assert "other" in configured
    for rejected_command in ("status", "identify", "doctor", "write", "discovery", "version"):
        assert rejected_command not in configured

    store["protocol"]["command_groups"]["main"].append("status")
    store["commands"]["xctx"]["status"] = {"rejected status command": "[]"}
    assert "status" not in configured_command_names(store)
    assert "status" not in command_map_for_group(store, "xctx", "main")


def test_framework_cli_command_contract() -> None:
    for command in ("discover", "observe", "plan", "execute", "audit", "repair"):
        rc, payload = run_runtime_json([command])
        if command in {"observe", "execute", "repair"}:
            assert rc == 1
            assert payload["ok"] is False
        elif command == "plan":
            assert rc == 1
            assert payload["ok"] is False
            assert payload["error"] == "missing plan arguments"
            assert payload["next_moves"] == [{"run_cmd": "./xctx plan <operation> <target>"}]
        else:
            assert rc == 0
            assert payload["record_type"] in {"discovery", "audit"}

    rc, payload = run_runtime_json(["other", "--topic", "ping"])
    assert rc == 0
    assert payload["record_type"] == "extension"
    assert payload["results"]["topic"] == "ping"

    rc, payload = run_runtime_json(["other"])
    assert rc == 1
    assert payload["ok"] is False

    for rejected_command in ("status", "identify", "doctor", "write", "discovery", "version", "d", "xctx_other"):
        rc, payload = run_runtime_json([rejected_command])
        assert rc == 1
        assert payload["record_type"] == "error"
        assert "other" not in payload["error"]
        assert payload["next_moves"] == ROOT_NEXT_MOVES


def test_error_records_keep_guidance_out_of_error_text() -> None:
    marker = "next " + "valid move"
    cases = (
        ["discovery"],
        ["plan"],
        ["repair"],
        ["discover", "GOOG"],
        ["observe"],
    )
    for args in cases:
        rc, payload = run_runtime_json(list(args))
        assert rc == 1
        assert payload["record_type"] == "error"
        assert marker not in payload["error"]
        if "next_moves" in payload:
            assert all(isinstance(move, dict) and "run_cmd" in move for move in payload["next_moves"])


def test_root_discovery_explains_scoped_next_moves() -> None:
    universe_rc, universe_payload = run_runtime_json([])
    rc, payload = run_runtime_json(["discover"])
    assert universe_rc == 0
    assert rc == 0
    results = payload["results"]
    assert results["next_move_context"] == {
        "agent_domain_id": "Replace {{agent_domain_id}} with an id from agent_domains.",
        "agent_domain_scope_template": "./xctx discover {{agent_domain_id}}::",
        "examples": [
            "./xctx discover stock_intelligence_hub::",
            "./xctx discover file_manager::",
        ],
    }
    assert universe_payload["results"]["next_moves"] == ROOT_NEXT_MOVES
    assert results["next_moves"] == ROOT_NEXT_MOVES
    assert "xctx_other" not in json.dumps(results, sort_keys=True)


def test_next_moves_are_command_hint_objects() -> None:
    def assert_no_string_next_moves(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"next_moves", "lawful_next_moves"}:
                    assert isinstance(item, list)
                    assert all(isinstance(move, dict) and "run_cmd" in move for move in item)
                assert_no_string_next_moves(item)
        elif isinstance(value, list):
            for item in value:
                assert_no_string_next_moves(item)

    for args in (
        [],
        ["discover"],
        ["discover", "macro_intelligence_hub::"],
        ["other", "--topic", "ping"],
        ["plan", "inspect", "root"],
    ):
        rc, payload = run_runtime_json(list(args))
        assert rc == 0
        assert_no_string_next_moves(payload)


def test_scope_run_cmd_preserves_shell_quoted_arguments() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.accessors import scope_run_cmd  # noqa: PLC0415

    store = load_store(root=ROOT)

    assert (
        scope_run_cmd(store, "xctx observe stock_intelligence_hub::equity_filing 'form:DEF 14A'")
        == "./xctx observe stock_intelligence_hub::equity_filing 'form:DEF 14A'"
    )


def test_scope_run_cmd_quotes_shell_metacharacter_arguments() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.accessors import scope_run_cmd  # noqa: PLC0415

    store = load_store(root=ROOT)

    assert scope_run_cmd(store, "xctx other --topic 'a;b'") == "./xctx other --topic 'a;b'"
    assert scope_run_cmd(store, "xctx other --topic '$(whoami)'") == "./xctx other --topic '$(whoami)'"


def test_scope_run_cmd_keeps_placeholder_tokens_readable() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.accessors import scope_run_cmd  # noqa: PLC0415

    store = load_store(root=ROOT)

    assert (
        scope_run_cmd(store, "xctx observe <agent_domain>::<agent_subdomain> --id <id>")
        == "./xctx observe <agent_domain>::<agent_subdomain> --id <id>"
    )


def test_scope_run_cmd_leaves_non_xctx_commands_unchanged() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415
    from xctx.protocol.accessors import scope_run_cmd  # noqa: PLC0415

    store = load_store(root=ROOT)

    assert scope_run_cmd(store, "python -m tool 'hello world'") == "python -m tool 'hello world'"


def test_action_args_reject_unexpected_query_for_non_query_actions() -> None:
    ensure_libs_path()
    from xctx.domain.actions import validate_declared_action_args  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    action = {
        "query_required": False,
        "argument_patterns": ["[--limit N]", "[--projection compact|full]"],
        "collection": {"max_limit": 10, "item_projections": ["compact", "full"]},
    }

    with pytest.raises(XctxError, match="unexpected argument for non-query action: 10-K"):
        validate_declared_action_args(action, ["10-K"])


def test_action_args_allow_declared_positional_prefix_for_non_query_actions() -> None:
    ensure_libs_path()
    from xctx.domain.actions import validate_declared_action_args  # noqa: PLC0415

    action = {
        "query_required": False,
        "argument_patterns": ["[directory:<relative_path>]", "[--limit N]"],
        "collection": {"max_limit": 10},
    }

    validate_declared_action_args(action, ["directory:docs", "--limit", "2"])


def test_action_args_allow_declared_adapter_filter_options() -> None:
    ensure_libs_path()
    from xctx.domain.actions import validate_declared_action_args  # noqa: PLC0415

    action = {
        "query_required": False,
        "argument_patterns": ["[--status STATUS]", "[--limit N]"],
        "collection": {"max_limit": 10, "filters": ["--status"]},
    }

    validate_declared_action_args(action, ["--status", "active", "--limit", "2"])


def test_action_args_allow_declared_action_cli_options() -> None:
    ensure_libs_path()
    from xctx.domain.actions import validate_declared_action_args  # noqa: PLC0415

    action = {
        "query_required": False,
        "cli_options": [
            {"flags": ["--minimum"], "dest": "minimum", "type": "int", "commands": ["plan"]},
            {"flags": ["--maximum"], "dest": "maximum", "type": "int", "commands": ["plan"]},
        ],
    }

    validate_declared_action_args(action, ["--minimum", "1", "--maximum", "1000"])


def test_action_args_allow_declared_cli_option_mapping_keys() -> None:
    ensure_libs_path()
    from xctx.domain.actions import validate_declared_action_args  # noqa: PLC0415

    action = {
        "query_required": False,
        "cli_options": {
            "--game-result": {"dest": "game_result", "type": "str"},
            "guess": {"dest": "guess", "type": "int"},
        },
    }

    validate_declared_action_args(action, ["--game-result", "result:abc", "--guess", "42"])


def test_action_args_reject_missing_declared_cli_option_value() -> None:
    ensure_libs_path()
    from xctx.domain.actions import validate_declared_action_args  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    action = {"query_required": False, "cli_options": [{"flags": ["--minimum"], "dest": "minimum"}]}

    with pytest.raises(XctxError, match="missing value for --minimum"):
        validate_declared_action_args(action, ["--minimum"])


def test_action_args_reject_undeclared_flag_before_adapter() -> None:
    ensure_libs_path()
    from xctx.domain.actions import validate_declared_action_args  # noqa: PLC0415
    from xctx.errors import XctxError  # noqa: PLC0415

    action = {"query_required": True, "cli_options": [{"flags": ["--minimum"], "dest": "minimum"}]}

    with pytest.raises(XctxError, match="unsupported action option for this action: --maximum"):
        validate_declared_action_args(action, ["--maximum", "1000"])


def test_non_query_list_action_rejects_stray_query_before_adapter() -> None:
    rc, payload = run_runtime_json(["discover", "stock_intelligence_hub::equity_filing::list_forms", "10-K"])

    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["error"] == "unexpected argument for non-query action: 10-K"


def test_protocol_walker_uses_visible_command_surface_only() -> None:
    text = (ROOT / "bin" / "protocol_walker").read_text(encoding="utf-8")
    assert "xctx_other" not in text
    assert ".get(\"aliases\"" not in text


def test_configured_command_without_handler_fails_closed(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.process import runtime  # noqa: PLC0415

    original_command_handlers = runtime.command_handlers

    def missing_repair_handler() -> dict:
        handlers = original_command_handlers()
        handlers.pop("repair")
        return handlers

    monkeypatch.setattr(runtime, "command_handlers", missing_repair_handler)

    rc, payload = run_runtime_json(["repair", "offline:macro_intelligence_hub"])
    assert rc == 1
    assert payload["ok"] is False
    assert payload["record_type"] == "error"
    assert payload["error"] == "configured command has no handler: repair"


def test_version_uses_declared_protocol_envelope_and_help_is_rejected() -> None:
    ensure_libs_path()
    from xctx.config.loader import load_store  # noqa: PLC0415

    store = load_store(root=ROOT)
    declared_record_types = set(store["protocol"]["record_types"])
    assert "help" not in declared_record_types

    cases = (
        (["--version"], "version", "universe"),
        (["-V"], "version", "universe"),
    )
    for args, record_type, domain_level in cases:
        rc, payload = run_runtime_json(list(args))
        assert rc == 0
        assert_protocol_envelope(payload)
        assert payload["record_type"] == record_type
        assert payload["domain_level"] == domain_level
        assert payload["record_type"] in declared_record_types

    rc, payload = run_runtime_json(["help"])
    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["error"] == "unknown xctx command"


def test_usage_error_records_include_error_category() -> None:
    rc, payload = run_runtime_json(["unknown-command"])

    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["error"] == "unknown xctx command"
    assert payload["error_category"] == "usage_error"


def test_unexpected_runtime_exception_is_categorized_as_framework_bug(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.process import runtime  # noqa: PLC0415

    def broken_handlers() -> dict:
        raise RuntimeError("handler registry exploded")

    monkeypatch.setattr(runtime, "command_handlers", broken_handlers)

    rc, payload = run_runtime_json(["discover"])

    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["error_category"] == "framework_bug"
    assert payload["error"].startswith("unexpected_framework_error: RuntimeError")


def test_store_error_fallback_records_include_error_category(monkeypatch) -> None:
    ensure_libs_path()
    from xctx.process import runtime  # noqa: PLC0415

    def broken_load_store(*_args, **_kwargs) -> dict:
        raise OSError("runtime store unavailable")

    monkeypatch.setattr(runtime, "load_store", broken_load_store)

    rc, payload = run_runtime_json(["discover"])

    assert rc == 1
    assert payload["record_type"] == "error"
    assert payload["error_category"] == "store_error"
    assert payload["error"] == "runtime store unavailable"
