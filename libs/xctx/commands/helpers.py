"""Shared command helpers."""

from __future__ import annotations

import argparse


def cmdline_arg(args: argparse.Namespace, command: str) -> str:
    return getattr(args, "cmdline_arg", command)
