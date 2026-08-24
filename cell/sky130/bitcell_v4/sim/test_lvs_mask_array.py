"""LVS for mask-programmed v4_array_NxM_<pattern> variants.

Each pattern emits a different weight assignment via mask programming
(via1 + M2/M3 patches per cell). The mask determines which BL the
cell drain connects to: w=+1 -> BLP_<col>, w=-1 -> BLN_<col>, w=0 ->
no via (drain isolated). Sources are isolated per cell (no VGND
rail in the array yet); gates are shared per row via the M1 WL
strap.

This test catches a class of bugs that DRC misses entirely: the
earlier mask programming had an M1 bridge that crossed the cell's
source M1 strap, shorting drain to source on every cell with a via.
The layout was DRC-clean but electrically nonfunctional. Only LVS
caught it.

Patterns covered: all_pos | all_neg | checker. all_zero is excluded
because zero-weight cells have no via and the drain net would be
extracted as floating, which the LVS engine cannot match against a
schematic with named drain nets.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from conftest import BUILD_DIR
from test_lvs_array import _find_netgen_setup, _wrap_top_level


MASK_RE = re.compile(r"^v4_array_(\d+)x(\d+)_(all_pos|all_neg|checker)$")


def _weight_at(r: int, c: int, pattern: str) -> int:
    if pattern == "all_pos":
        return 1
    if pattern == "all_neg":
        return -1
    if pattern == "checker":
        return 1 if (r + c) % 2 == 0 else -1
    raise ValueError(f"unknown pattern {pattern}")


def _emit_mask_array_schematic(name: str, n_rows: int, n_cols: int,
                                pattern: str) -> str:
    """Reference netlist for a mask-programmed array.

    Wiring:
      drain  -> BLP_<col> if weight=+1, BLN_<col> if weight=-1
      source -> S_<r>_<c>  (isolated per cell, no VGND rail yet)
      gate   -> WL_<row>   (shared via M1 strap)
      body   -> VGND       (= VSUBS, normalized)
    """
    lines: list[str] = [
        f"* Auto-generated reference for {name} ({pattern}, {n_rows}x{n_cols}).",
        ".subckt bitcell_v4 D S G VGND",
        "X1 D G S VGND sky130_fd_pr__nfet_01v8 w=0.42 l=0.17",
        ".ends bitcell_v4",
        "",
        f".subckt {name}",
    ]
    inst = 0
    for r in range(n_rows):
        for c in range(n_cols):
            w = _weight_at(r, c, pattern)
            d_net = f"BLP_{c}" if w == 1 else f"BLN_{c}"
            lines.append(
                f"Xbitcell_v4_{inst} {d_net} S_{r}_{c} WL_{r} VGND bitcell_v4"
            )
            inst += 1
    lines.append(f".ends {name}")
    return "\n".join(lines) + "\n"


def _discover_mask_arrays() -> list[tuple[str, int, int, str]]:
    out: list[tuple[str, int, int, str]] = []
    if not BUILD_DIR.exists():
        return out
    for mag in sorted(BUILD_DIR.glob("v4_array_*x*_*.mag")):
        m = MASK_RE.match(mag.stem)
        if m:
            n, mcols, pat = int(m.group(1)), int(m.group(2)), m.group(3)
            out.append((mag.stem, n, mcols, pat))
    return out


@pytest.mark.parametrize("cell,n_rows,n_cols,pattern", _discover_mask_arrays())
def test_lvs_mask_array(cell: str, n_rows: int, n_cols: int, pattern: str,
                         tmp_path: Path) -> None:
    extracted = BUILD_DIR / f"{cell}_extracted.spice"
    if not extracted.exists():
        pytest.skip(f"{extracted.name} missing -- run extract_bitcell_v4.tcl first")

    n_cells = n_rows * n_cols
    if n_cells > 16384:
        pytest.skip(f"{cell}: {n_cells} cells exceed netgen flat-LVS budget")

    layout = tmp_path / f"{cell}_layout.spice"
    text = extracted.read_text().replace("VSUBS", "VGND")
    text = _wrap_top_level(text, cell)
    layout.write_text(text)

    schematic = tmp_path / f"{cell}_ref.spice"
    schematic.write_text(_emit_mask_array_schematic(cell, n_rows, n_cols, pattern))

    log_path = tmp_path / "lvs.log"
    setup = _find_netgen_setup()
    netgen_timeout = max(60, 60 + n_cells // 100)
    subprocess.run(
        ["netgen", "-batch", "lvs",
         f"{layout} {cell}",
         f"{schematic} {cell}",
         str(setup),
         str(log_path)],
        cwd=tmp_path,
        capture_output=True, text=True, timeout=netgen_timeout, check=False,
    )
    log = log_path.read_text() if log_path.exists() else ""
    assert "Circuits match uniquely." in log or "Netlists match uniquely." in log, \
        f"{cell}: LVS failed (drain-source short bug returned?):\n{log[-2000:]}"
