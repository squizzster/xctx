"""Process signal setup for command-line execution."""

from __future__ import annotations

import signal


def configure_sigpipe() -> None:
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
