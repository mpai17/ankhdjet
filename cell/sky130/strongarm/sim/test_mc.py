"""Monte Carlo regression — schematic + post-extraction.

200 trials per default at SS @ 100 mV. Override via env:
  ANKHDJET_MC_TRIALS=200          (trials per source)
  ANKHDJET_VDIFF_MV=100           (input differential)
  ANKHDJET_MC_GATE_PERCENT=99.9   (correct% pass threshold; set 0 to
                                run as characterization-only)

The production sizing currently fails the 99.9% gate at 100 mV
under SS mismatch. ANKHDJET_MC_GATE_PERCENT=0 lets the suite emit
the characterization without hard-blocking on the mismatch margin.
"""

from __future__ import annotations

import os
import re
import subprocess

import pytest

from conftest import EXTRACTED, SIM_DIR


@pytest.mark.parametrize("source", ["schematic", "extracted"])
def test_mc(source: str) -> None:
    if source == "extracted" and not EXTRACTED.exists():
        pytest.skip(f"{EXTRACTED} missing — run extract_parasitics.tcl")
    trials = os.environ.get("ANKHDJET_MC_TRIALS", "200")
    vdiff = os.environ.get("ANKHDJET_VDIFF_MV", "100")
    gate_pct = float(os.environ.get("ANKHDJET_MC_GATE_PERCENT", "99.9"))

    env = {**os.environ, "ANKHDJET_SA_SOURCE": source,
           "ANKHDJET_MC_TRIALS": trials, "ANKHDJET_VDIFF_MV": vdiff}
    r = subprocess.run(
        ["python3", "run_mc.py"],
        cwd=SIM_DIR, env=env,
        capture_output=True, text=True, timeout=7200,
    )
    out = r.stdout
    m = re.search(rf"^\s*{vdiff}\s+\d+\s+([\d.]+)%\s+([\d.]+)%", out, re.MULTILINE)
    assert m, f"could not parse MC table for {source}:\n{out[-2000:]}"
    correct_pct = float(m.group(1))
    if gate_pct > 0:
        assert correct_pct >= gate_pct, (
            f"{source} MC at {vdiff}mV: {correct_pct}% correct < gate {gate_pct}%"
        )


if __name__ == "__main__":
    for s in ["schematic", "extracted"]:
        try:
            test_mc(s)
            print(f"[ok] MC {s} passes")
        except AssertionError as e:
            print(f"[FAIL] MC {s}: {e}")
