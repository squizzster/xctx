"""Discovery action payloads and result projection."""

from __future__ import annotations

from typing import Any

from xctx.errors import XctxError
from xctx.protocol.accessors import format_run_cmd, guidance_cmd, response_template, run_cmd_key
from xctx.store.resolver import collection_records, resolve_collection, subsystem_by_id

_RESERVED_TEMPLATE_KEYS = {"subsystem_id", "action"}


def build_root_discovery_payload(store: dict[str, Any]) -> dict[str, Any]:
    template = response_template(store, "root_discovery")
    run_key = run_cmd_key(store)
    root_actions = store.get("subsystem_registry", {}).get("root_discovery", {}).get("actions", {})
    if root_actions:
        results: dict[str, Any] = {}
        for name, config in sorted(root_actions.items(), key=lambda item: item[1].get("priority", 9999)):
            if not isinstance(config, dict):
                raise XctxError(f"next valid move: inspect root discovery action {name}")
            source_subsystem = config.get("from_subsystem")
            source_action = config.get("from_action", name)
            if not source_subsystem:
                raise XctxError(f"next valid move: add from_subsystem to root discovery action {name}")
            subsystem = subsystem_by_id(store, source_subsystem)
            if not subsystem:
                raise XctxError(f"next valid move: inspect subsystem registry entry {source_subsystem}")
            action = subsystem.get("discovery", {}).get("actions", {}).get(source_action)
            if not action:
                raise XctxError(f"next valid move: inspect discovery action {source_action}")
            entry = {
                key: value
                for key, value in config.items()
                if key not in {"from_subsystem", "from_action", "run_cmd", run_key}
            }
            entry.setdefault("desc", action.get("desc", ""))
            run_template = config.get(run_key, config.get("run_cmd", action.get(run_key, action.get("run_cmd", ""))))
            if run_template:
                entry[run_key] = format_run_cmd(store, run_template, subsystem_id=subsystem["id"], action=name)
            results[name] = entry
        return results

    results: dict[str, Any] = {}
    for subsystem in store["subsystems"]:
        system_ref = subsystem.get("_system_ref", {})
        run_template = system_ref.get("run_cmd", template.get("subsystem_run_cmd", ""))
        results[subsystem["id"]] = {
            "desc": subsystem["desc"],
            run_key: format_run_cmd(store, run_template, subsystem_id=subsystem["id"]),
        }
    return results


def build_subsystem_discovery_payload(store: dict[str, Any], subsystem_id: str) -> dict[str, Any]:
    subsystem = subsystem_by_id(store, subsystem_id)
    if not subsystem:
        run_cmd = guidance_cmd(store, "discover_root_run_cmd")
        raise XctxError(f"next valid move: {run_cmd}" if run_cmd else "next valid move: discover")

    run_key = run_cmd_key(store)
    results: dict[str, Any] = {}
    for name, config in subsystem.get("discovery", {}).get("actions", {}).items():
        entry = {
            key: value
            for key, value in config.items()
            if key
            not in {
                "collection",
                "id_field",
                "search_fields",
                "result_fields",
                "result_run_cmd",
                "observe",
                "run_cmd",
                run_key,
            }
        }
        if config.get("run_cmd"):
            entry[run_key] = format_run_cmd(store, config["run_cmd"], subsystem_id=subsystem["id"], action=name)
        results[name] = entry
    for name, config in subsystem.get("discovery", {}).get("collections", {}).items():
        count_from = config.get("count_from", name)
        entry = {key: value for key, value in config.items() if key not in {"count_from", "run_cmd", run_key}}
        entry["count"] = len(collection_records(store, count_from, subsystem["id"]))
        command_template = config.get(run_key, config.get("run_cmd", ""))
        if command_template:
            entry[run_key] = format_run_cmd(store, command_template, subsystem_id=subsystem["id"])
        results[name] = entry
    return results


def find_discovery_action(store: dict[str, Any], action_name: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for subsystem in store["subsystems"]:
        action = subsystem.get("discovery", {}).get("actions", {}).get(action_name)
        if action:
            return subsystem, action
    return None


def text_values(record: dict[str, Any], fields: list[str]) -> list[str]:
    values: list[str] = []
    for field in fields:
        value = record.get(field)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif isinstance(value, dict):
            values.extend(str(item) for item in value.values())
        elif value is not None:
            values.append(str(value))
    return values


def project_record(record: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {field: record[field] for field in fields if field in record}


def _template_context(record: dict[str, Any], result_id: str) -> dict[str, Any]:
    context = {key: value for key, value in record.items() if key not in _RESERVED_TEMPLATE_KEYS}
    context["id"] = result_id
    context["source_id"] = record.get("id")
    return context


def discover_action_results(
    store: dict[str, Any],
    subsystem: dict[str, Any],
    action_name: str,
    action: dict[str, Any],
    query_text: str,
) -> dict[str, Any]:
    run_key = run_cmd_key(store)
    if not query_text.strip():
        entry = {"desc": action.get("desc", "")}
        if action.get("run_cmd"):
            entry[run_key] = format_run_cmd(store, action["run_cmd"], subsystem_id=subsystem["id"], action=action_name)
        return {action_name: entry}

    collection = resolve_collection(store, action["collection"], subsystem["id"])
    id_field = action.get("id_field", collection["spec"].get("identity_id_field", "id"))
    search_fields = action.get("search_fields", ["name", "id"])
    result_fields = action.get("result_fields", ["name"])
    query = query_text.lower()
    results: dict[str, Any] = {}
    for record in collection["records"]:
        haystack = " ".join(text_values(record, search_fields)).lower()
        if query not in haystack:
            continue
        result_id = str(record.get(id_field, record.get("id")))
        projected = project_record(record, result_fields)
        observe_template = action.get("result_run_cmd", action.get("observe", {}).get("run_cmd"))
        if observe_template:
            projected[run_key] = format_run_cmd(
                store,
                observe_template,
                subsystem_id=subsystem["id"],
                action=action_name,
                **_template_context(record, result_id),
            )
        results[result_id] = projected
    if not results and isinstance(action.get("empty_result"), dict):
        empty_result = action["empty_result"]
        entry = {key: value for key, value in empty_result.items() if key not in {"run_cmd", run_key}}
        run_template = empty_result.get(run_key, empty_result.get("run_cmd", action.get(run_key, action.get("run_cmd", ""))))
        if run_template:
            entry[run_key] = format_run_cmd(
                store,
                run_template,
                subsystem_id=subsystem["id"],
                action=action_name,
                query=query_text,
            )
        return {action_name: entry}
    return results


def observe_action_result(
    store: dict[str, Any],
    subsystem: dict[str, Any],
    action_name: str,
    action: dict[str, Any],
    item_id: str,
) -> dict[str, Any]:
    collection = resolve_collection(store, action["collection"], subsystem["id"])
    id_field = action.get("id_field", collection["spec"].get("identity_id_field", "id"))
    record = next((item for item in collection["records"] if str(item.get(id_field, "")) == str(item_id)), None)
    if not record:
        run_cmd = guidance_cmd(store, "discover_root_run_cmd")
        raise XctxError(f"next valid move: {run_cmd}" if run_cmd else "next valid move: discover")

    observe_config = action.get("observe", {})
    fields = observe_config.get("result_fields", action.get("result_fields", ["name"]))
    result = project_record(record, fields)
    run_template = observe_config.get("run_cmd")
    if run_template:
        result_id = str(record.get(id_field, item_id))
        result[run_cmd_key(store)] = format_run_cmd(
            store,
            run_template,
            subsystem_id=subsystem["id"],
            action=action_name,
            **_template_context(record, result_id),
        )
    return result
