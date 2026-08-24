"""Common paths for the precharge cell regression suite."""

from __future__ import annotations

from pathlib import Path

CELL_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = CELL_DIR / "build"
SIM_DIR = Path(__file__).resolve().parent

CELL_MAG = BUILD_DIR / "precharge.mag"
