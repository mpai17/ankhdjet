"""Functional regression: precharge cell must recharge a SUBCOL=64
loaded BL (32 fF) from a 200 mV droop back to within 5% of VDD in
<= 1 ns at SS, per gen_precharge.tcl spec.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import SIM_DIR


def test_recharge_passes_ss() -> None:
    r = subprocess.run(
        [sys.executable, "run_recharge.py"],
        cwd=SIM_DIR, capture_output=True, text=True, timeout=300,
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"recharge run failed:\n{out[-2000:]}"
    assert "[ok] SS @ 32 fF" in out, f"missing pass marker:\n{out[-2000:]}"
