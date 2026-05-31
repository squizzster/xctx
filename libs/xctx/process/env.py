"""Environment sanitization shared by subprocess ports and connectors."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

from xctx.process.python_subprocess import with_isolated_pythonpath

EXPLICIT_EXTRA_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
BLOCKED_EXPLICIT_EXTRA_ENV_KEYS = frozenset({"PYTHONHOME", "PYTHONPATH"})

SAFE_ENV_KEYS = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "TMPDIR",
        "VIRTUAL_ENV",
        "XCTX_RUNTIME_DIR",
    }
)


def explicit_extra_env_key_allowed(key: str) -> bool:
    return bool(EXPLICIT_EXTRA_ENV_KEY_RE.fullmatch(key)) and key not in BLOCKED_EXPLICIT_EXTRA_ENV_KEYS


def connector_passthrough_env(connector: Mapping[str, Any] | None) -> dict[str, str]:
    """Return env vars explicitly requested by connector config.

    ``env_passthrough`` remains limited to protocol-local ``XCTX_*`` and the
    generic safe set. ``adapter_env_passthrough`` is an explicit adapter-owned
    allowlist for conventional provider variables while still blocking Python
    interpreter environment poisoning.
    """

    config = connector or {}
    env: dict[str, str] = {}
    for key in config.get("env_passthrough") or []:
        text_key = str(key)
        if text_key in os.environ and (text_key in SAFE_ENV_KEYS or text_key.startswith("XCTX_")):
            env[text_key] = os.environ[text_key]
    for key in config.get("adapter_env_passthrough") or []:
        text_key = str(key)
        if text_key in os.environ and explicit_extra_env_key_allowed(text_key):
            env[text_key] = os.environ[text_key]
    return env


def sanitized_env(
    extra: Mapping[str, str | None] | None = None,
    *,
    allow_explicit_extra: bool = False,
) -> dict[str, str]:
    """Return a minimal, deterministic environment for child processes.

    Explicit ``None`` values remove inherited keys. ``XCTX_*`` variables are
    admitted so scoped connectors can receive protocol-local context. Callers
    that have already built an explicit connector allowlist may opt into
    additional conventional environment variables with ``allow_explicit_extra``.
    """
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
    for key, value in (extra or {}).items():
        if value is None:
            env.pop(key, None)
        elif key in SAFE_ENV_KEYS or key.startswith("XCTX_") or (
            allow_explicit_extra and explicit_extra_env_key_allowed(key)
        ):
            env[key] = str(value)
    return with_isolated_pythonpath(env)
