"""Macro-level DRC regression: macro_array_pc_<N>x<M>_<pattern>.

The macro stacks v4_array_NxM (mask-programmed) on top of
precharge_rowM and adds per-column M1 + via1 + M2 routing wiring
each precharge D to the array's BL+_<col> M2 strip.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from conftest import BUILD_DIR


MACRO_RE = re.compile(r"^macro_array_pc_(\d+)x(\d+)_(all_pos|all_neg|checker)$")


def _drc_count(cell: str) -> tuple[int, str]:
    tcl = (
        f"load {cell}\n"
        "select top cell\n"
        "drc on\ndrc check\ndrc catchup\n"
        'puts "COUNT=[drc list count total]"\n'
        "set rules [drc listall why]\n"
        "foreach {rule boxes} $rules {\n"
        '    puts "RULE: $rule [llength $boxes]"\n'
        "}\n"
        "quit -noprompt\n"
    )
    r = subprocess.run(
        ["magic", "-dnull", "-noconsole"],
        cwd=BUILD_DIR, input=tcl, text=True,
        capture_output=True, timeout=240,
    )
    out = r.stdout + r.stderr
    m = re.search(r"COUNT=(\d+)", out)
    assert m, f"{cell}: no DRC count in output:\n{out[-1500:]}"
    return int(m.group(1)), out


def _discover_macros() -> list[tuple[str, int, int, str]]:
    out: list[tuple[str, int, int, str]] = []
    if not BUILD_DIR.exists():
        return out
    for mag in sorted(BUILD_DIR.glob("macro_array_pc_*.mag")):
        m = MACRO_RE.match(mag.stem)
        if m:
            out.append((mag.stem, int(m.group(1)), int(m.group(2)), m.group(3)))
    return out


@pytest.mark.parametrize("cell,n_rows,n_cols,pattern", _discover_macros())
def test_macro_drc_clean(cell: str, n_rows: int, n_cols: int,
                          pattern: str) -> None:
    n, out = _drc_count(cell)
    assert n == 0, (
        f"{cell}: DRC = {n}, expected 0:\n{out[-2000:]}"
    )
