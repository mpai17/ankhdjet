"""Common paths for the StrongARM regression suite."""

from __future__ import annotations

from pathlib import Path

CELL_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = CELL_DIR / "build"
SIM_DIR = Path(__file__).resolve().parent
SCHEMATIC = CELL_DIR / "strongarm_schematic.spice"
EXTRACTED = BUILD_DIR / "strongarm_extracted.spice"
ROUTED_MAG = BUILD_DIR / "strongarm.mag"
