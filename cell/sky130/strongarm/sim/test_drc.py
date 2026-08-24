"""DRC regression for the routed StrongARM cell (KLayout authoritative).

Magic's met*.3b / met*.5b "long-edge spacing to unrelated metal" rules
over-report relative to the foundry PDK; sign-off DRC is KLayout
(sky130A_mr.drc). This test streams the routed cell to GDS and runs the
KLayout deck, asserting zero violations.
"""

from __future__ import annotations

import glob
import re
import subprocess
from pathlib import Path

import pytest

from conftest import BUILD_DIR, ROUTED_MAG


def _klayout_deck() -> Path:
    matches = glob.glob(
        str(Path.home() / ".ciel/sky130A/libs.tech/klayout/drc/sky130A_mr.drc")
    )
    assert matches, "sky130A_mr.drc not found in the Ciel sky130A install"
    return Path(matches[0])


def test_drc_clean(tmp_path) -> None:
    if not ROUTED_MAG.exists():
        pytest.skip(f"{ROUTED_MAG} missing — SA layout not yet routed.")

    gds = BUILD_DIR / "strongarm.gds"
    subprocess.run(
        ["magic", "-dnull", "-noconsole", "-T", "sky130A"],
        cwd=BUILD_DIR,
        input="load strongarm -quiet\ngds write strongarm.gds\nquit -noprompt\n",
        text=True, capture_output=True, timeout=120,
    )
    assert gds.exists(), "magic did not emit strongarm.gds"

    report = tmp_path / "drc.lyrdb"
    subprocess.run(
        ["klayout", "-b", "-r", str(_klayout_deck()),
         "-rd", f"input={gds}", "-rd", "topcell=strongarm",
         "-rd", f"report={report}",
         "-rd", "feol=true", "-rd", "beol=true", "-rd", "offgrid=true"],
        capture_output=True, text=True, timeout=600,
    )
    text = report.read_text() if report.exists() else ""
    items = re.findall(r"<item>.*?</item>", text, re.S)
    cats = [
        m.group(1)
        for it in items
        if (m := re.search(r"<category>([^<]+)</category>", it))
    ]
    assert not items, f"KLayout DRC: {len(items)} violations: {cats}"


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_drc_clean(Path(d))
    print("[ok] KLayout DRC clean")
