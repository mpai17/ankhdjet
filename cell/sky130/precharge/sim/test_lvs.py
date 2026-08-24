"""LVS regression for the precharge cell family.

  precharge        single PMOS, 0.42/0.15 — LVS vs precharge_schematic.spice
  precharge_row4   4-PMOS shared-gate array — currently xfail: the
                   hand-painted layout fragments poly into multiple
                   small fingers (Magic warns "Device has multiple
                   lengths"). LVS scaffolding is in place; the layout
                   needs a re-do with PCell instances before this can
                   pass.
"""

from __future__ import annotations

import glob
import subprocess
from pathlib import Path

import pytest

from conftest import BUILD_DIR, CELL_DIR

SCHEMATIC = CELL_DIR / "precharge_schematic.spice"


def _find_netgen_setup() -> Path:
    matches = glob.glob(
        str(Path.home() / ".ciel/sky130A/libs.tech/netgen/sky130A_setup.tcl")
    )
    assert matches, "sky130A_setup.tcl not found in volare install"
    return Path(matches[0])


def _wrap_top_level(text: str, cell_name: str) -> str:
    """Magic emits row-level layouts with no port labels as a NGSPICE
    top-level netlist (`* Top level circuit <name>` followed by X-lines
    and `.end`). Netgen's LVS expects a `.subckt <name>` block. Wrap the
    bare X-lines inline so the diff-against-schematic comparison works."""
    if f".subckt {cell_name}" in text:
        return text
    lines = text.splitlines()
    out: list[str] = []
    in_top = False
    for ln in lines:
        if ln.startswith(f"* Top level circuit {cell_name}"):
            in_top = True
            out.append(f".subckt {cell_name}")
            continue
        if in_top and ln.strip() == ".end":
            out.append(f".ends {cell_name}")
            in_top = False
            continue
        out.append(ln)
    return "\n".join(out) + "\n"


def _run_lvs(extracted: Path, layout_cell: str, schematic: Path,
             schematic_cell: str, tmp_path: Path) -> str:
    norm = tmp_path / f"{layout_cell}_vgnd.spice"
    text = extracted.read_text().replace("VSUBS", "VGND")
    text = _wrap_top_level(text, layout_cell)
    norm.write_text(text)
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


def test_lvs_precharge(tmp_path: Path) -> None:
    extracted = BUILD_DIR / "precharge_extracted.spice"
    if not extracted.exists():
        pytest.skip(f"{extracted.name} missing — run extract_precharge.tcl first")
    assert SCHEMATIC.exists()
    text = _run_lvs(extracted, "precharge", SCHEMATIC, "precharge", tmp_path)
    n_equiv = sum(1 for ln in text.splitlines() if "are equivalent." in ln)
    assert n_equiv >= 2, f"LVS not equivalent (saw {n_equiv} equiv lines):\n{text[-2000:]}"
    assert "Circuits match uniquely." in text or "Netlists match uniquely." in text, \
        f"netlists do not match uniquely:\n{text[-2000:]}"
    assert "Cell pin lists are equivalent." in text, \
        f"pin lists not equivalent:\n{text[-2000:]}"


def test_lvs_precharge_row4(tmp_path: Path) -> None:
    extracted = BUILD_DIR / "precharge_row4_extracted.spice"
    if not extracted.exists():
        pytest.skip(f"{extracted.name} missing — run gen_precharge_row.tcl + "
                    "extract_precharge.tcl first")
    schematic = CELL_DIR / "precharge_row4_schematic.spice"
    assert schematic.exists()
    text = _run_lvs(extracted, "precharge_row4", schematic, "precharge_row4", tmp_path)
    n_equiv = sum(1 for ln in text.splitlines() if "are equivalent." in ln)
    assert n_equiv >= 2, f"LVS not equivalent (saw {n_equiv} equiv lines):\n{text[-2000:]}"
    assert "Circuits match uniquely." in text or "Netlists match uniquely." in text, \
        f"netlists do not match uniquely:\n{text[-2000:]}"
    assert "Cell pin lists are equivalent." in text, \
        f"pin lists not equivalent:\n{text[-2000:]}"


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_lvs_precharge(Path(d))
    print("[ok] precharge LVS equivalent")
