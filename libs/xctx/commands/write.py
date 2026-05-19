"""write command."""

from __future__ import annotations

import argparse
import json

from xctx.commands.helpers import cmdline_arg
from xctx.errors import XctxError
from xctx.io.yaml_io import load_yaml, write_yaml
from xctx.protocol.accessors import format_run_cmd, guidance_cmd, run_cmd_key
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event
from xctx.store.resolver import find_by_id, resolve_collection


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "write"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "validating write request", operation=args.operation)
    collection = resolve_collection(store, args.collection)
    operation = collection["spec"].get("write", {}).get(args.operation)
    if not operation:
        run_cmd = guidance_cmd(store, "discover_root_run_cmd")
        raise XctxError(f"next valid move: {run_cmd}" if run_cmd else "next valid move: discover")

    payload = json.loads(args.data_json) if args.data_json else {}
    for field in operation.get("required_fields", []):
        if field not in payload:
            raise XctxError(f"next valid move: include data_json field {field}")
    if payload.get("id") and find_by_id(collection["records"], payload["id"]):
        run_cmd = guidance_cmd(store, "observe_id_run_cmd", id=payload["id"])
        raise XctxError(f"next valid move: {run_cmd}" if run_cmd else "next valid move: observe")

    result = {
        "request": {"operation": args.operation, "collection": collection["name"], "apply": args.apply},
        "record": payload,
    }
    if args.apply:
        collection_doc = load_yaml(collection["path"])
        collection_doc.setdefault(collection["root_key"], []).append(payload)
        write_yaml(collection["path"], collection_doc)
        result["status"] = "applied"
    else:
        result["status"] = "planned"
        if operation.get("run_cmd"):
            result[run_cmd_key(store)] = format_run_cmd(
                store,
                operation["run_cmd"], collection=collection["name"], operation=args.operation
            )

    emit_record(store, command, "result", result, cmdline_arg=called_as)
    emit_final_stderr(store, command, True, "write request complete", applied=args.apply, records=1)
    return 0
