"""Bounded subprocess capture utilities used by xctx protocol ports.

The protocol runtime and connector middleware both need the same subprocess
contract: bounded stdout/stderr previews, hard timeouts, and process-tree cleanup.
Output is captured through temporary files rather than pipes so adapters cannot
block on a full pipe and long local-gate tests do not accumulate reader threads.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping, Sequence

POLL_SECONDS = 0.05
KILL_GRACE_SECONDS = 1.0


@dataclass(frozen=True)
class CapturedProcess:
    argv: tuple[str, ...]
    returncode: int | None
    timed_out: bool
    stdout: str
    stderr: str
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_captured_bytes: int = 0
    stderr_captured_bytes: int = 0
    stdout_total_bytes: int = 0
    stderr_total_bytes: int = 0
    max_output_bytes: int = 0

    @property
    def exit_code(self) -> int | None:
        return self.returncode

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.returncode == 0


def decode_bytes(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def read_limited(stream: BinaryIO, max_output_bytes: int) -> str:
    return _read_limited_with_metadata(stream, max_output_bytes)[0]


def _read_limited_with_metadata(stream: BinaryIO, max_output_bytes: int) -> tuple[str, bool, int, int]:
    stream.flush()
    stream.seek(0, os.SEEK_END)
    total_bytes = stream.tell()
    stream.seek(0)
    raw = stream.read(max_output_bytes)
    captured_bytes = len(raw)
    return decode_bytes(raw), total_bytes > captured_bytes, captured_bytes, total_bytes


def kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Best-effort kill for the process and its process group/session."""

    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
            return
        proc.kill()
    except ProcessLookupError:
        return


def _wait_with_deadline(proc: subprocess.Popen[bytes], timeout: float) -> bool:
    """Return True when the process timed out, False when it exited."""

    deadline = time.monotonic() + timeout
    while proc.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            kill_process_tree(proc)
            return True
        time.sleep(min(POLL_SECONDS, remaining))
    return False


def _finish_after_kill(proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + KILL_GRACE_SECONDS
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass


def capture_process(
    argv: Sequence[str],
    *,
    timeout: float,
    max_output_bytes: int,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CapturedProcess:
    """Run a subprocess and capture bounded stdout/stderr previews.

    Temporary-file capture trades a small amount of disk IO for a simpler and
    more reliable process contract: no pipe backpressure, no selector quirks,
    and no reader-thread leakage across many adapter invocations.
    """

    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        proc = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=(os.name == "posix"),
        )
        timed_out = _wait_with_deadline(proc, timeout)
        if timed_out:
            _finish_after_kill(proc)

        stdout, stdout_truncated, stdout_captured_bytes, stdout_total_bytes = _read_limited_with_metadata(
            stdout_file,
            max_output_bytes,
        )
        stderr, stderr_truncated, stderr_captured_bytes, stderr_total_bytes = _read_limited_with_metadata(
            stderr_file,
            max_output_bytes,
        )

    return CapturedProcess(
        argv=tuple(str(part) for part in argv),
        returncode=proc.returncode,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        stdout_captured_bytes=stdout_captured_bytes,
        stderr_captured_bytes=stderr_captured_bytes,
        stdout_total_bytes=stdout_total_bytes,
        stderr_total_bytes=stderr_total_bytes,
        max_output_bytes=max_output_bytes,
    )
