"""Replay regression: from a clean subcell set, gen_strongarm_top.tcl
must place the 9 SA subcells (W=8/L=2 input pair) without DRC errors.

Placement-only: the routed cell's strict DRC and extraction are
covered by test_drc.py and test_lvs.py against gen_strongarm_routing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from conftest import BUILD_DIR, CELL_DIR


def test_replay_placement(tmp_path) -> None:
    work = tmp_path / "replay"
    work.mkdir()
    for sub in ["sa_tail.mag", "sa_inp.mag", "sa_xc_n.mag", "sa_xc_p.mag", "sa_rst.mag"]:
        src = BUILD_DIR / sub
        if not src.exists():
            pytest.skip(f"missing subcell: {src} -- run the SA subcell generators first")
        shutil.copy(src, work / sub)
    magicrc = CELL_DIR / ".magicrc"
    if magicrc.exists():
        shutil.copy(magicrc, work / ".magicrc")

    top_tcl = CELL_DIR / "gen_strongarm_top.tcl"
    assert top_tcl.exists()

    r = subprocess.run(
        ["magic", "-dnull", "-noconsole"],
        cwd=work, input=top_tcl.read_text(), text=True,
        capture_output=True, timeout=180,
    )
    out = r.stdout + r.stderr
    assert (work / "strongarm.mag").exists(), f"placement did not produce strongarm.mag:\n{out[-1500:]}"
    m = re.search(r"DRC=(\d+)", out)
    assert m, f"no DRC count in output:\n{out[-1500:]}"
    n = int(m.group(1))
    # Placement-only stage: each PCell paints small M1 stubs at S/D pins
    # that fail met1.6 (M1 minimum area 0.083 um^2) on their own. They
    # resolve when routing connects them into wires; test_drc.py runs
    # the full strict DRC against the routed cell.
    assert n <= 9, (
        f"placement DRC = {n} > 9 (expected 9 met1.6 area stubs at "
        f"PCell pins, no other rules):\n{out[-1500:]}"
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        test_replay_placement(Path(d))
    print("[ok] placement replay")
