#!/usr/bin/env python3
"""Compatibility wrapper for the market_data_gateway live adapter."""

from __future__ import annotations

from market_data_gateway import main

if __name__ == "__main__":
    raise SystemExit(main())
