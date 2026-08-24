"""LVS regression for the bitcell_v4 family.

Each cell's extracted netlist (produced by `extract_bitcell_v4.tcl`)
must be device-class-equivalent to the schematic reference per netgen.

Coverage:
  bitcell_v4         single NMOS, 0.42/0.15 — LVS vs bitcell_v4_schematic.spice
  bitcell_v4_biroma  identical layout with extra D_E/D_O label aliases
                     for bidirectional read; LVS uses the same
                     bitcell_v4 schematic since the extracted netlist
                     collapses the aliases to D and S.
  body_tap           psub diffusion contact only, no devices — LVS not
                     applicable.
"""

from __future__ import annotations

import glob
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import BUILD_DIR, CELL_DIR

SCHEMATIC = CELL_DIR / "bitcell_v4_schematic.spice"


def _find_netgen_setup() -> Path:
    matches = glob.glob(
        str(Path.home() / ".ciel/sky130A/libs.tech/netgen/sky130A_setup.tcl")
    )
    assert matches, "sky130A_setup.tcl not found in volare install"
    return Path(matches[0])


def _run_lvs(extracted: Path, layout_cell: str, schematic: Path,
             schematic_cell: str, tmp_path: Path) -> str:
    """Run netgen on a (VSUBS-normalized) extracted netlist + schematic."""
    norm = tmp_path / f"{layout_cell}_vgnd.spice"
    norm.write_text(extracted.read_text().replace("VSUBS", "VGND"))
    log = tmp_path / "lvs.log"
    setup = _find_netgen_setup()
    subprocess.run(
        ["netgen", "-batch", "lvs",
         f"{norm} {layout_cell}",
         f"{schematic} {schematic_cell}",
         str(setup),
         str(log)],
        cwd=tmp_path,
        capture_output=True, text=True, timeout=120, check=False,
    )
    return log.read_text() if log.exists() else ""


@pytest.mark.parametrize("layout_cell", ["bitcell_v4", "bitcell_v4_biroma"])
def test_lvs_bitcell(tmp_path: Path, layout_cell: str) -> None:
    extracted = BUILD_DIR / f"{layout_cell}_extracted.spice"
    if not extracted.exists():
        pytest.skip(f"{extracted.name} missing — run extract_bitcell_v4.tcl first")
    assert SCHEMATIC.exists()
    text = _run_lvs(extracted, layout_cell, SCHEMATIC, "bitcell_v4", tmp_path)
    n_equiv = sum(1 for ln in text.splitlines() if "are equivalent." in ln)
    assert n_equiv >= 2, f"LVS not equivalent (saw {n_equiv} equiv lines):\n{text[-2000:]}"
    assert "Circuits match uniquely." in text or "Netlists match uniquely." in text, \
        f"netlists do not match uniquely:\n{text[-2000:]}"
    assert "Cell pin lists are equivalent." in text, \
        f"pin lists not equivalent:\n{text[-2000:]}"


if __name__ == "__main__":
    import tempfile
    for cell in ["bitcell_v4", "bitcell_v4_biroma"]:
        with tempfile.TemporaryDirectory() as d:
            test_lvs_bitcell(Path(d), cell)
        print(f"[ok] {cell} LVS equivalent")
