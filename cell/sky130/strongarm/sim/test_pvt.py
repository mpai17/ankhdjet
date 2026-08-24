"""PVT regression — schematic + post-extraction.

Runs run_pvt.py once per source (schematic, extracted) and asserts
the runner exited 0 (i.e. SS @ 100 mV resolved within 500 ps target
across all 18 corner × Vdiff points).
"""

from __future__ import annotations

import os
import subprocess

import pytest

from conftest import EXTRACTED, SIM_DIR


@pytest.mark.parametrize("source", ["schematic", "extracted"])
def test_pvt(source: str) -> None:
    if source == "extracted" and not EXTRACTED.exists():
        pytest.skip(f"{EXTRACTED} missing — run extract_parasitics.tcl")
    env = {**os.environ, "ANKHDJET_SA_SOURCE": source}
    r = subprocess.run(
        ["python3", "run_pvt.py"],
        cwd=SIM_DIR, env=env,
        capture_output=True, text=True, timeout=900,
    )
    assert r.returncode == 0, (
        f"PVT {source} failed (rc={r.returncode}):\n"
        f"{r.stdout[-2000:]}\n{r.stderr[-1000:]}"
    )


if __name__ == "__main__":
    for s in ["schematic", "extracted"]:
        try:
            test_pvt(s)
            print(f"[ok] PVT {s} passes")
        except AssertionError as e:
            print(f"[FAIL] PVT {s}: {e}")
