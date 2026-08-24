"""Replay regression: gen_precharge.tcl run from a clean tmp directory
must produce a precharge.mag matching the committed cell-level DRC
budget. Drift in PCell parameters or generator script breaks this.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from conftest import CELL_DIR


PLACEMENT_STUB_BUDGET = 6


def test_replay_precharge(tmp_path) -> None:
    work = tmp_path / "replay"
    work.mkdir()
    magicrc = CELL_DIR / ".magicrc"
    if magicrc.exists():
        shutil.copy(magicrc, work / ".magicrc")

    gen_tcl = CELL_DIR / "gen_precharge.tcl"
    assert gen_tcl.exists(), f"{gen_tcl} missing"

    r = subprocess.run(
        ["magic", "-dnull", "-noconsole"],
        cwd=work, input=gen_tcl.read_text(), text=True,
        capture_output=True, timeout=120,
    )
    out = r.stdout + r.stderr
    assert (work / "precharge.mag").exists(), (
        f"replay did not produce precharge.mag:\n{out[-1500:]}"
    )

    drc_tcl = (
        "drc off\n"
        "load precharge\n"
        "drc on\n"
        "select top cell\n"
        "drc check\n"
        "drc catchup\n"
        'puts "COUNT=[drc list count total]"\n'
        "quit -noprompt\n"
    )
    r2 = subprocess.run(
        ["magic", "-dnull", "-noconsole"],
        cwd=work, input=drc_tcl, text=True,
        capture_output=True, timeout=120,
    )
    out2 = r2.stdout + r2.stderr
    m = re.search(r"COUNT=(\d+)", out2)
    assert m, f"no DRC count in replay output:\n{out2[-1500:]}"
    n = int(m.group(1))
    assert n <= PLACEMENT_STUB_BUDGET, (
        f"replay DRC = {n} > {PLACEMENT_STUB_BUDGET}:\n{out2[-1500:]}"
    )
