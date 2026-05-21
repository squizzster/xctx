#!/usr/bin/env python3
"""Small manual test harness for sql_id.py."""

from __future__ import annotations

import sys

from sql_id import MAX_ID, hex_to_id, id_to_hex


def self_test() -> int:
    examples = [1, 12, 999_999, MAX_ID]
    for value in examples:
        encoded = id_to_hex(value)
        decoded = hex_to_id(encoded)
        if encoded is None or decoded != value:
            print(f"failed round trip: {value} -> {encoded} -> {decoded}", file=sys.stderr)
            return 1

    invalid_values = [None, True, False, 0, -1, MAX_ID + 1, "12.0", "abc", " 12"]
    for value in invalid_values:
        if id_to_hex(value) is not None:
            print(f"accepted invalid id: {value!r}", file=sys.stderr)
            return 1

    invalid_hex_values = ["", "0", "0000000000000000", "zzzzzzzzzzzzzzzz", "7300000000000019"]
    for value in invalid_hex_values:
        if hex_to_id(value) is not None:
            print(f"accepted invalid hex: {value!r}", file=sys.stderr)
            return 1

    print("ok")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "--self-test":
        return self_test()

    if len(argv) != 2:
        print(f"usage: {argv[0]} <decimal-id | 16-hex-chars | --self-test>", file=sys.stderr)
        return 2

    value = argv[1].strip()
    if len(value) == 16 and all(char in "0123456789abcdefABCDEF" for char in value):
        result = hex_to_id(value)
    else:
        result = id_to_hex(value)

    if result is None:
        print("invalid")
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
