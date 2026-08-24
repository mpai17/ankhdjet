"""LVS regression: extracted netlist must be device-class-equivalent
to strongarm_schematic.spice per netgen.

Magic emits VSUBS as the substrate net; schematic uses VGND for NMOS
bulk. Aliasing is done by sed-substituting VSUBS->VGND on a temp copy
of the extracted netlist before LVS.
"""

from __future__ import annotations

import glob
import re
import shutil
import subprocess
from pathlib import Path

from conftest import BUILD_DIR, EXTRACTED, SCHEMATIC


def _find_netgen_setup() -> Path:
    matches = glob.glob(
        str(Path.home() / ".ciel/sky130A/libs.tech/netgen/sky130A_setup.tcl")
    )
    assert matches, "sky130A_setup.tcl not found in volare install"
    return Path(matches[0])


def test_lvs_equivalent(tmp_path) -> None:
    if not EXTRACTED.exists():
        import pytest
        pytest.skip(
            f"{EXTRACTED} missing — SA layout pending re-route at the new "
            "W=10/L=2 sizing; schematic-level validation (test_pvt.py + "
            "test_mc.py) is current."
        )
    assert SCHEMATIC.exists()

    norm = tmp_path / "extracted_vgnd.spice"
    norm.write_text(EXTRACTED.read_text().replace("VSUBS", "VGND"))

    log = tmp_path / "lvs.log"
    setup = _find_netgen_setup()
    subprocess.run(
        ["netgen", "-batch", "lvs",
         f"{norm} strongarm",
         f"{SCHEMATIC} strongarm",
         str(setup),
         str(log)],
        cwd=tmp_path,
        capture_output=True, text=True, timeout=120, check=False,
    )
    text = log.read_text() if log.exists() else ""
    # netgen prints "Device classes <a> and <b> are equivalent." for
    # every cell + the top — must match all three (pfet, nfet, strongarm).
    n_equiv = sum(1 for ln in text.splitlines() if "are equivalent." in ln)
    assert n_equiv >= 3, f"LVS not equivalent (saw {n_equiv} equiv lines):\n{text[-3000:]}"
    assert "Circuits match uniquely." in text or "Netlists match uniquely." in text, \
        f"netlists do not match uniquely:\n{text[-2000:]}"
    assert "Cell pin lists are equivalent." in text, \
        f"pin lists not equivalent:\n{text[-2000:]}"


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_lvs_equivalent(Path(d))
    print("[ok] LVS equivalent")
