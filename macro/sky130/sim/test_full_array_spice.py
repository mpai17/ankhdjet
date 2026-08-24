"""Full-array SPICE integration regression: drive every (row, col) of a
hand-laid-out cirom_array through ngspice end-to-end (precharge ->
row-select -> sense-amp resolution) and verify every cell decision
against the Python reference.

Every device on the sense path is a real SKY130 BSIM model -- bitcell
NMOS, precharge PMOS, full StrongARM SA -- and every weight is a real
drain-routing choice.

Coverage tiers per OpenRAM functional.py / ISSCC CIM 2024 practice:

  tier 1: structured patterns (all-+1, all--1, checker, stripe row/col)
          -- catches leakage-summing, BL-droop, decoder collisions
  tier 2: random matrices with logged seed (smoke + statistical)
  tier 3: single-cell-hot exhaustive -- every (r, c) verified

The pytest test runs the SMOKE level (1 random pattern at TT corner,
4x2 array) -- ~30 s, fits the regression budget. Run thorough coverage
(tier1+random+exhaustive at SS corner, larger arrays, hours of wall-
clock) via the CLI:

  python macro/sky130/sim/spice_integration/runner.py \\
        -N 64 -M 32 --coverage tier1+random+exhaustive --corner ss

To write a single `.sp` deck to disk for hand inspection or piping
to another simulator:

  python macro/sky130/sim/spice_integration/gen_array_spice.py \\
        -N 64 -M 32 --pattern all_pos --corner tt -o /tmp/x.sp

Pass criterion (per cell): the SA decision must match the reference,
and |OUTP - OUTM| at sample edge must exceed Vmargin=0.1V (sense
margin), failing into one of 5 categorized modes:
  sense_margin / decision_flip / reset_incomplete / off_cell_leakage /
  measurement_missing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from conftest import MACRO_DIR


RUNNER = MACRO_DIR / "sim" / "spice_integration" / "runner.py"


def test_smoke_random_4x2_tt() -> None:
    """Smoke: 4x2 array, single random seed, TT corner, ~30 s ngspice."""
    r = subprocess.run(
        [sys.executable, str(RUNNER),
         "-N", "4", "-M", "2",
         "--coverage", "smoke",
         "--corner", "tt",
         "--timeout", "300"],
        capture_output=True, text=True, timeout=600,
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, (
        f"full-array SPICE smoke failed:\n{out[-2500:]}"
    )
    assert "summary: 1/1 patterns pass" in out, (
        f"missing pass marker:\n{out[-2500:]}"
    )


@pytest.mark.slow
def test_tier1_structured_4x2_tt() -> None:
    """Tier 1: 6 structured patterns (all-+1/-1/0, checker, stripes).
    ~3 min ngspice; marked slow so it doesn't run in default suite."""
    r = subprocess.run(
        [sys.executable, str(RUNNER),
         "-N", "4", "-M", "2",
         "--coverage", "tier1",
         "--corner", "tt",
         "--timeout", "600"],
        capture_output=True, text=True, timeout=1200,
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"tier1 failed:\n{out[-2500:]}"
    assert "summary: 6/6 patterns pass" in out, (
        f"missing tier1 pass marker:\n{out[-2500:]}"
    )
