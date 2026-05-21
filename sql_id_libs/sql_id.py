"""Compact reversible SQL integer IDs.

This module maps an internal integer ID to a fixed 16-character hex string and
back again:

    integer -> password-derived Feistel permutation -> 6-char RFC1924 base85
    -> 2-byte checksum -> 8-byte internal ID -> salted 64-bit Feistel -> hex

The result is meant for compact public IDs that can later decode back to a SQL
integer lookup key. It is not intended to provide cryptographic security,
authentication, secrecy guarantees, or tamper-proof tokens. The checksum and
canonical decode checks are deliberately small because the output must stay at
8 bytes / 16 hex characters.

Public surface:
    id_to_hex(value) -> str | None
    hex_to_id(value) -> int | None

Both functions return None for invalid input and do not print errors. The
calling application owns user-facing error messages.

This ID scheme is a compact, deterministic, reversible public-handle layer for internal SQL integer identifiers. It preserves the operational advantages of `AUTO_INCREMENT` / integer primary keys while exposing only fixed-width 8-byte / 16-hex public IDs. The mapping uses a password-derived Feistel permutation over the integer payload, compact fixed-width base85 packing, checksum bytes, and an outer salted 64-bit Feistel transform before hex encoding. Decoding must reverse those layers and then pass strict validation: hex shape, outer Feistel decrypt, checksum match, valid RFC1924 base85 payload, canonical re-encoding, inverse payload permutation, and final SQL ID range enforcement. The result is suitable for high-volume identifiers such as `job_id`, `log_id`, `event_id`, or ordinary row IDs, avoiding extra `public_id` columns, secondary unique indexes, random collision handling, and public enumeration of sequential IDs. This is a defense-in-depth identifier obfuscation mechanism, not an authentication or authorization system; decoded IDs must still be checked against normal application permissions and business rules.
"""

from __future__ import annotations

import hashlib
import os
import re


ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~"
BASE = len(ALPHABET)
WIDTH = 6

# Public ID range. We reserve SQL ID 0 as invalid, while the scrambled payload
# internally uses zero-based indexes so the whole 6-char base85 space is usable.
MIN_ID = 1
MAX_ID = BASE**WIDTH - 1
_MAX_ID_DIGITS = len(str(MAX_ID))

# Internal representation is exactly 8 bytes:
#   checksum byte 0 + 6-byte base85 payload + checksum byte 1
#
# Before returning it to the caller, we run those 8 bytes through a reversible
# 64-bit Feistel layer using SHA256(env password + FEISTEL_SALT_HEX). It adds no
# bytes, so the final public value is still 8 bytes rendered as 16 hex chars.
_HEX_RE = re.compile(r"^[0-9a-fA-F]{16}$")

# Fixed 32-byte salt/domain-separation constant. It is embedded in source, so
# it is not secret; it just separates this ID scheme's Feistel keys
# from other password-derived uses.
FEISTEL_SALT_HEX = "798fa8088558c58f382e0dc42b43d3d0d1c705fd621797ec8ea5dff7a2c01381"
_FEISTEL_SALT = bytes.fromhex(FEISTEL_SALT_HEX)

# The Feistel block is 40 bits: two 20-bit halves. This is larger than the
# 6-char base85 domain, so cycle-walking maps the larger permutation back into
# exactly the valid payload range without changing output length.
ROUNDS = 12
_BLOCK_HALF_BITS = 20
_BLOCK_HALF_MASK = (1 << _BLOCK_HALF_BITS) - 1
_OUTER_HALF_BITS = 32
_OUTER_HALF_MASK = (1 << _OUTER_HALF_BITS) - 1
_MAX_CYCLE_WALKS = 10_000


def _load_password_bytes() -> bytes:
    # The password is read once at import time. Applications must set
    # XCTX_ID_PASSWORD before importing this module.
    password = os.environ.get("XCTX_ID_PASSWORD")
    if password is None:
        raise RuntimeError("XCTX_ID_PASSWORD is required")
    return password.encode("utf-8")


_PASSWORD_BYTES = _load_password_bytes()


def _derive_round_keys(label: bytes, half_bytes: int) -> tuple[bytes, ...]:
    # Each Feistel round gets an independent key derived from the password.
    # This is not a security construction here; it is deterministic scrambling
    # for compact public IDs.
    seed = hashlib.sha256(_PASSWORD_BYTES + _FEISTEL_SALT + label).digest()
    return tuple(
        hashlib.sha256(seed + b":round:" + str(round_id).encode("ascii") + b":half:" + bytes([half_bytes])).digest()
        for round_id in range(ROUNDS)
    )


_INNER_ROUND_KEYS = _derive_round_keys(b":inner-payload-permutation:", 3)
_OUTER_ROUND_KEYS = _derive_round_keys(b":outer-64-bit-id-encryption:", 4)


def _round_function(right: int, key: bytes, half_bytes: int, mask: int) -> int:
    # Feistel only needs a deterministic 20-bit function of the right half and
    # the round key. SHA-256 is convenient and stable in the Python stdlib.
    digest = hashlib.sha256(key + right.to_bytes(half_bytes, "big")).digest()
    return int.from_bytes(digest[:4], "big") & mask


def _feistel_encrypt(value: int) -> int:
    # Classic Feistel step:
    #   new_left = right
    #   new_right = left XOR F(right, round_key)
    # This is reversible even when F itself is not reversible.
    left = (value >> _BLOCK_HALF_BITS) & _BLOCK_HALF_MASK
    right = value & _BLOCK_HALF_MASK
    for key in _INNER_ROUND_KEYS:
        left, right = right, left ^ _round_function(right, key, 3, _BLOCK_HALF_MASK)
    return (left << _BLOCK_HALF_BITS) | right


def _feistel_decrypt(value: int) -> int:
    # Reverse the same rounds in reverse order. This exactly undoes
    # _feistel_encrypt for any 40-bit value.
    left = (value >> _BLOCK_HALF_BITS) & _BLOCK_HALF_MASK
    right = value & _BLOCK_HALF_MASK
    for key in reversed(_INNER_ROUND_KEYS):
        left, right = right ^ _round_function(left, key, 3, _BLOCK_HALF_MASK), left
    return (left << _BLOCK_HALF_BITS) | right


def _outer_encrypt(packed: bytes) -> bytes:
    # Final reversible 8-byte transform. This encrypts the whole internal ID
    # after checksum construction, adds no bytes, and has no checksum of its own.
    value = int.from_bytes(packed, "big")
    left = (value >> _OUTER_HALF_BITS) & _OUTER_HALF_MASK
    right = value & _OUTER_HALF_MASK
    for key in _OUTER_ROUND_KEYS:
        left, right = right, left ^ _round_function(right, key, 4, _OUTER_HALF_MASK)
    return ((left << _OUTER_HALF_BITS) | right).to_bytes(8, "big")


def _outer_decrypt(packed: bytes) -> bytes:
    # Exact inverse of _outer_encrypt. After this step the inner checksum and
    # canonical base85 checks decide whether the caller supplied a valid ID.
    value = int.from_bytes(packed, "big")
    left = (value >> _OUTER_HALF_BITS) & _OUTER_HALF_MASK
    right = value & _OUTER_HALF_MASK
    for key in reversed(_OUTER_ROUND_KEYS):
        left, right = right ^ _round_function(left, key, 4, _OUTER_HALF_MASK), left
    return ((left << _OUTER_HALF_BITS) | right).to_bytes(8, "big")


def _permute_index(index: int) -> int:
    # Cycle-walking lets us use a 40-bit permutation while exposing only the
    # smaller 0..MAX_ID-1 base85 domain. We repeatedly encrypt until the result
    # falls back inside the valid domain.
    value = index
    for _ in range(_MAX_CYCLE_WALKS):
        value = _feistel_encrypt(value)
        if value < MAX_ID:
            return value
    raise RuntimeError("cycle walk failed")


def _unpermute_index(index: int) -> int:
    # Inverse cycle-walking. Starting from a valid exposed payload index, walk
    # backward through the same permutation until another valid domain value is
    # reached; that value is the original zero-based SQL index.
    value = index
    for _ in range(_MAX_CYCLE_WALKS):
        value = _feistel_decrypt(value)
        if value < MAX_ID:
            return value
    raise RuntimeError("cycle walk failed")


def _coerce_id(value: object) -> int:
    # Be strict. Silent int() coercion would accept floats like 12.9 as 12,
    # which is not acceptable for an ID surface.
    if isinstance(value, bool):
        raise ValueError("bool is not an id")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"^[0-9]+$", value):
        if len(value) > _MAX_ID_DIGITS:
            raise ValueError("id string too long")
        return int(value)
    raise ValueError("id must be an int or decimal digit string")


def _index_to_base85(value: int) -> str:
    # Fixed-width base85 payload. The left padding character is ALPHABET[0],
    # which is "0" for the RFC1924 alphabet.
    if not 0 <= value < MAX_ID:
        raise ValueError("index out of range")

    chars = []
    n = value
    if n == 0:
        chars.append(ALPHABET[0])
    while n:
        n, remainder = divmod(n, BASE)
        chars.append(ALPHABET[remainder])
    return "".join(reversed(chars)).rjust(WIDTH, ALPHABET[0])


def _base85_to_index(text: str) -> int:
    # Decode exactly WIDTH RFC1924 base85 characters back to a zero-based
    # payload index.
    if len(text) != WIDTH:
        raise ValueError("wrong base85 width")

    value = 0
    for char in text:
        digit = ALPHABET.find(char)
        if digit < 0:
            raise ValueError("invalid base85 character")
        value = value * BASE + digit

    if not 0 <= value < MAX_ID:
        raise ValueError("decoded index out of range")
    return value


def _checksum(core: bytes) -> bytes:
    # This is a compact typo/random-input checksum, not a security boundary.
    # usedforsecurity=False keeps the intent explicit on Python builds that
    # enforce FIPS-like MD5 restrictions.
    try:
        digest = hashlib.md5(core, usedforsecurity=False).digest()
    except TypeError:
        digest = hashlib.md5(core).digest()
    return digest[:2]


def id_to_hex(value: object) -> str | None:
    """Return a 16-character hex public ID for an integer, or None."""
    try:
        id_value = _coerce_id(value)
        if not MIN_ID <= id_value <= MAX_ID:
            return None

        # Convert to a zero-based index, scramble it inside the valid payload
        # domain, encode to 6 base85 bytes, wrap it with two checksum bytes,
        # then apply the outer Feistel layer.
        payload = _index_to_base85(_permute_index(id_value - 1)).encode("ascii")
        check = _checksum(payload)
        return _outer_encrypt(check[:1] + payload + check[1:]).hex()
    except Exception:  # noqa: BLE001 - public API returns None for all failures
        return None


def hex_to_id(value: object) -> int | None:
    """Return the original integer for a 16-character hex public ID, or None."""
    try:
        # Reject early: callers get None for everything invalid and decide their
        # own user-facing error message.
        if not isinstance(value, str) or not _HEX_RE.fullmatch(value):
            return None

        external = bytes.fromhex(value)
        if len(external) != 8:
            return None

        # The public 16-hex ID is outer-Feistel wrapped. Reverse that layer
        # before the compact checksum/canonical validation.
        packed = _outer_decrypt(external)
        payload = packed[1:7]
        check = _checksum(payload)
        if packed[0] != check[0] or packed[7] != check[1]:
            return None

        # Checksum success is not enough. The payload must be valid ASCII
        # RFC1924 base85, decode into the payload domain, and be canonical when
        # encoded again.
        base85 = payload.decode("ascii")
        permuted_index = _base85_to_index(base85)
        if _index_to_base85(permuted_index) != base85:
            return None

        # Unscramble back to the zero-based SQL index, then restore the public
        # one-based SQL ID range.
        id_value = _unpermute_index(permuted_index) + 1
        if not MIN_ID <= id_value <= MAX_ID:
            return None
        return id_value
    except Exception:  # noqa: BLE001 - public API returns None for all failures
        return None
