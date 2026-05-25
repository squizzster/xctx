"""Environment sanitization shared by subprocess ports and connectors."""

from __future__ import annotations

import os
from collections.abc import Mapping

from xctx.process.python_subprocess import with_isolated_pythonpath

SAFE_ENV_KEYS = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "TMPDIR",
        "VIRTUAL_ENV",
        "XCTX_RUNTIME_DIR",
    }
)


def sanitized_env(extra: Mapping[str, str | None] | None = None) -> dict[str, str]:
    """Return a minimal, deterministic environment for child processes.

    Explicit ``None`` values remove inherited keys. ``XCTX_*`` variables are
    admitted so future scoped connectors can receive protocol-local context
    without broadening the ambient environment.
    """
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
    for key, value in (extra or {}).items():
        if value is None:
            env.pop(key, None)
        elif key in SAFE_ENV_KEYS or key.startswith("XCTX_"):
            env[key] = str(value)
    return with_isolated_pythonpath(env)
