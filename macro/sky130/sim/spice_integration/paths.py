"""Shared path constants for the SPICE integration framework."""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent.parent
SA_SCHEMATIC = REPO / "cell" / "sky130" / "strongarm" / "strongarm_schematic.spice"
SKY130_LIB = Path.home() / ".volare/sky130A/libs.tech/ngspice/sky130.lib.spice"
