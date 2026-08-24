"""Cell-level DRC for the precharge family.

Standalone PCell paint at minimum-W produces 6 met1.6 (M1 minimum
area 0.083 um^2) markers at S/D/G contact stubs — those are expected
at cell level and resolve when the cell is integrated into a column
where its M1 stubs become parts of routed wires. Anything beyond
met1.6 stub markers is a real violation.

Rows of N cells inherit the per-cell stub budget linearly (N x 6) so
the expected-pattern test scales with row size. Row shapes are
discovered from build/ at collection time so the regression covers
whatever layout the engineer just generated.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from conftest import BUILD_DIR


PER_CELL_STUB_BUDGET = 6  # met1.6 stubs per precharge cell at placement level

ROW_RE = re.compile(r"^precharge_row(\d+)$")


def _discover_rows() -> list[tuple[str, int]]:
    """Find precharge_row<N>.mag files in build/ and return (name, budget)."""
    rows: list[tuple[str, int]] = []
    if BUILD_DIR.exists():
        for mag in sorted(BUILD_DIR.glob("precharge_row*.mag")):
            m = ROW_RE.match(mag.stem)
            if m:
                n = int(m.group(1))
                rows.append((mag.stem, n * PER_CELL_STUB_BUDGET))
    return rows


def _drc_count(cell: str) -> tuple[int, str]:
    tcl = (
        "drc off\n"
        f"load {cell}\n"
        "drc on\n"
        "select top cell\n"
        "drc check\n"
        "drc catchup\n"
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
        capture_output=True, timeout=120,
    )
    out = r.stdout + r.stderr
    m = re.search(r"COUNT=(\d+)", out)
    assert m, f"{cell}: no DRC count in output:\n{out[-1500:]}"
    return int(m.group(1)), out


def test_drc_only_placement_stubs() -> None:
    mag = BUILD_DIR / "precharge.mag"
    if not mag.exists():
        pytest.skip(f"{mag} missing -- run gen_precharge.tcl first (layouts are generated, not committed)")
    n, out = _drc_count("precharge")
    assert n <= PER_CELL_STUB_BUDGET, (
        f"precharge DRC = {n} > {PER_CELL_STUB_BUDGET} (expected only met1.6 stubs):\n"
        f"{out[-1500:]}"
    )
    for line in out.splitlines():
        if line.startswith("RULE:"):
            assert "met1.6" in line, f"unexpected rule beyond met1.6 stubs:\n{line}"


@pytest.mark.parametrize("cell,budget", _discover_rows())
def test_drc_row_only_placement_stubs(cell: str, budget: int) -> None:
    mag = BUILD_DIR / f"{cell}.mag"
    if not mag.exists():
        pytest.skip(f"{mag} missing -- run gen_precharge_row.tcl first (layouts are generated, not committed)")
    n, out = _drc_count(cell)
    assert n <= budget, (
        f"{cell} DRC = {n} > {budget} (expected only N x 6 met1.6 stubs):\n"
        f"{out[-1500:]}"
    )
    for line in out.splitlines():
        if line.startswith("RULE:"):
            assert "met1.6" in line, f"unexpected rule beyond met1.6 stubs:\n{line}"


if __name__ == "__main__":
    test_drc_only_placement_stubs()
    print("[ok] precharge DRC only placement stubs")
    for cell, budget in _discover_rows():
        test_drc_row_only_placement_stubs(cell, budget)
        print(f"[ok] {cell} DRC <= {budget} (placement stubs only)")
