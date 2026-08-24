"""DRC regression for the bitcell_v4 family.

Three classes of cells are checked:
  * fixed primitives:  bitcell_v4, bitcell_v4_biroma, body_tap
  * sub-columns:       any v4_subcol_<rows>.mag in build/
  * arrays:            any v4_array_<rows>x<cols>.mag in build/

Sub-column and array shapes are discovered from build/ at collection
time so the same regression runs against whatever shape the engineer
just generated (gen_subcol_v4.tcl / gen_array.tcl take their dimensions
from env vars).
"""

from __future__ import annotations

import re
import subprocess

import pytest

from conftest import BUILD_DIR


PRIMITIVE_CELLS = ["bitcell_v4", "bitcell_v4_biroma", "body_tap"]
SUBCOL_RE = re.compile(r"^v4_subcol_(\d+)$")
ARRAY_RE  = re.compile(r"^v4_array_(\d+)x(\d+)$")


def _discover_cells() -> list[str]:
    cells = list(PRIMITIVE_CELLS)
    if BUILD_DIR.exists():
        for mag in sorted(BUILD_DIR.glob("v4_subcol_*.mag")):
            if SUBCOL_RE.match(mag.stem):
                cells.append(mag.stem)
        for mag in sorted(BUILD_DIR.glob("v4_array_*.mag")):
            if ARRAY_RE.match(mag.stem):
                cells.append(mag.stem)
    return cells


CELLS = _discover_cells()


@pytest.mark.parametrize("cell", CELLS)
def test_drc_clean(cell: str) -> None:
    mag = BUILD_DIR / f"{cell}.mag"
    if not mag.exists():
        pytest.skip(f"{mag} missing — run gen_*.tcl first (layouts are generated, not committed)")
    tcl = (
        "drc off\n"
        f"load {cell}\n"
        "drc on\n"
        "select top cell\n"
        "drc check\n"
        "drc catchup\n"
        f"puts \"COUNT={cell}=[drc list count total]\"\n"
        "quit -noprompt\n"
    )
    r = subprocess.run(
        ["magic", "-dnull", "-noconsole"],
        cwd=BUILD_DIR, input=tcl, text=True,
        capture_output=True, timeout=300,
    )
    out = r.stdout + r.stderr
    m = re.search(rf"COUNT={cell}=(\d+)", out)
    assert m, f"{cell}: no DRC count in output:\n{out[-1500:]}"
    n = int(m.group(1))
    assert n == 0, f"{cell}: {n} DRC violations\n{out[-1000:]}"


if __name__ == "__main__":
    for c in CELLS:
        try:
            test_drc_clean(c)
            print(f"[ok] {c} DRC clean")
        except AssertionError as e:
            print(f"[FAIL] {c}: {str(e)[:200]}")
