"""BL discharge sweep regression — runs run_bl_sweep.py and asserts
the SS @ N=128 t_50pct ≤ 1.5 ns target passes.

This is the array-level test for bitcell_v4: it characterizes how many
cells per column can be on a shared BL while still discharging within
the sense-amp-aware timing budget.
"""

from __future__ import annotations

import subprocess

from conftest import SIM_DIR


def test_bl_sweep_passes() -> None:
    r = subprocess.run(
        ["python3", "run_bl_sweep.py"],
        cwd=SIM_DIR, capture_output=True, text=True, timeout=900,
    )
    assert r.returncode == 0, (
        f"BL sweep failed (rc={r.returncode}):\n"
        f"{r.stdout[-2000:]}\n{r.stderr[-1000:]}"
    )


if __name__ == "__main__":
    test_bl_sweep_passes()
    print("[ok] BL sweep passes")
