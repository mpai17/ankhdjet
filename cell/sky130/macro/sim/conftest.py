"""Common paths for the macro_array_pc regression suite."""

from __future__ import annotations

from pathlib import Path

CELL_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = CELL_DIR / "build"
SIM_DIR = Path(__file__).resolve().parent


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: tests that take many minutes (large-array netgen LVS)",
    )
