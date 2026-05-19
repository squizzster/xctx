"""identify command."""

from __future__ import annotations

import argparse

from xctx.commands.helpers import cmdline_arg
from xctx.domain.identity import identity_query_fields, identity_records, record_matches_query
from xctx.protocol.emitter import emit_final_stderr, emit_record, emit_stderr_event


def handle(store: dict, args: argparse.Namespace) -> int:
    command = "identify"
    called_as = cmdline_arg(args, command)
    emit_stderr_event(store, command, "start", "collecting immutable identities")
    records = identity_records(store, args.category)
    if args.query:
        fields = identity_query_fields(store)
        records = [record for record in records if record_matches_query(record, args.query, fields)]
    for record in records:
        emit_record(store, command, "result", record, cmdline_arg=called_as)
    emit_final_stderr(store, command, True, "identity enumeration complete", records=len(records))
    return 0
