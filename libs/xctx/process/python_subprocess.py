"""Helpers for fast, deterministic Python entrypoint subprocesses."""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def _site_package_paths() -> list[str]:
    paths = sysconfig.get_paths()
    values: list[str | None] = []
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        major_minor = f"python{sys.version_info.major}.{sys.version_info.minor}"
        values.extend(
            [
                str(Path(virtual_env) / "lib" / major_minor / "site-packages"),
                str(Path(virtual_env) / "Lib" / "site-packages"),
            ]
        )
    values.extend([paths.get("purelib"), paths.get("platlib")])
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def merged_pythonpath(existing: str | None = None, extra_paths: Iterable[str | Path] = ()) -> str:
    """Return a PYTHONPATH that works with ``python -S`` without sitecustomize."""

    ordered: list[str] = []
    for value in [*(str(path) for path in extra_paths), *_site_package_paths(), *(existing or "").split(os.pathsep)]:
        if not value or value in ordered:
            continue
        ordered.append(value)
    return os.pathsep.join(ordered)


def with_isolated_pythonpath(env: Mapping[str, str], extra_paths: Iterable[str | Path] = ()) -> dict[str, str]:
    out = dict(env)
    out["PYTHONPATH"] = merged_pythonpath(None, extra_paths=extra_paths)
    return out


def python_entrypoint_argv(script: str | Path, args: Sequence[str] = ()) -> list[str]:
    """Build argv for a Python script while skipping costly site startup.

    ``-S`` prevents ambient sitecustomize/user-site imports from becoming part of
    connector latency. The caller must pair this with ``with_isolated_pythonpath``
    so third-party runtime dependencies remain importable.
    """

    return [sys.executable, "-S", str(script), *args]
