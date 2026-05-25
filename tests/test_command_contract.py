"""Framework command-surface and legacy-removal tests."""

from __future__ import annotations

import json

import pytest

from framework_helpers import ROOT, ensure_libs_path, run_runtime_json


pytestmark = [pytest.mark.unit, pytest.mark.release, pytest.mark.timeout(60)]


ROOT_NEXT_MOVES = [
    {
        "desc": "Discover configured agent domains in this universe.",
        "run_cmd": "./xctx discover",
    },
    {
        "desc": "Inspect the machine command surface explicitly.",
        "run_cmd": "./xctx help",
    },
    {
        "desc": "Audit loaded configuration, live adapters, and offline/maintenance findings.",
        "run_cmd": "./xctx audit root",
    },
]


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
    for rejected_command in ("status", "identify", "doctor", "write", "discovery"):
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

    for rejected_command in ("status", "identify", "doctor", "write", "discovery", "d", "xctx_other"):
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


def test_protocol_walker_uses_visible_command_surface_only() -> None:
    assert "xctx_other" not in (ROOT / "bin" / "protocol_walker").read_text(encoding="utf-8")


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
    assert payload["error"] == "configured command has no production handler: repair"
