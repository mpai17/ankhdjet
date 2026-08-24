"""End-to-end macro-level smoke test: ankhdjet.estimate.compare runs the
full architectural derivation + area model across SKY130/GF180/ASAP7
and prints a per-PDK area + throughput row. Catches breakage in the
compiler -> area model -> PDK loader chain.

Default invocation uses a synthetic 22M-param BitNet shape (no HF
model download), so the test is fast and offline.
"""

from __future__ import annotations

import re
import subprocess
import sys

from conftest import REPO


def _run_compare_pdks(*extra_args: str) -> str:
    r = subprocess.run(
        [sys.executable, "-m", "ankhdjet.estimate.compare", *extra_args],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, (
        f"ankhdjet compare failed:\n"
        f"stdout:\n{r.stdout[-1500:]}\nstderr:\n{r.stderr[-500:]}"
    )
    return r.stdout


SKY_V4_ROW = r"^\s*sky130_v4\s+130nm\s+\d+\s+([\d.]+)\s+"
ASAP7_ROW = r"^\s*asap7\s+7nm\s+\d+\s+([\d.]+)\s+"


def test_compare_pdks_default_emits_per_pdk_rows() -> None:
    out = _run_compare_pdks()
    # Header columns the formatter prints.
    assert "pdk" in out and "process" in out and "tok/s" in out, \
        f"missing header in compare output:\n{out[-1500:]}"
    # The as-built anchor (130nm) and ASAP7 (7nm) must produce a row;
    # GF180 may go [over].
    sky130_row = re.search(SKY_V4_ROW, out, re.MULTILINE)
    asap7_row = re.search(ASAP7_ROW, out, re.MULTILINE)
    assert sky130_row, f"no sky130_v4 row:\n{out[-1500:]}"
    assert asap7_row, f"no asap7 row:\n{out[-1500:]}"
    sky_area = float(sky130_row.group(1))
    asap_area = float(asap7_row.group(1))
    # SKY130 130 nm must produce more area than ASAP7 7 nm for the same
    # workload (the headline node-portability claim).
    assert sky_area > asap_area, (
        f"SKY130 area {sky_area} not greater than ASAP7 {asap_area} -- "
        f"node-density check broke:\n{out[-1500:]}"
    )


def test_compare_pdks_biroma_gated_outside_window() -> None:
    """BiROMA is NO-GO at 130 nm (viability window 28-65 nm), so --biroma
    must be a per-node no-op at the listed anchors, with a printed note."""
    out_plain = _run_compare_pdks()
    out_biroma = _run_compare_pdks("--biroma")
    assert "--biroma ignored" in out_biroma, (
        f"window-guard note missing from --biroma output:\n{out_biroma[-1500:]}"
    )
    sky_plain = re.search(SKY_V4_ROW, out_plain, re.MULTILINE)
    sky_biroma = re.search(SKY_V4_ROW, out_biroma, re.MULTILINE)
    assert sky_plain and sky_biroma
    assert float(sky_biroma.group(1)) == float(sky_plain.group(1)), (
        f"--biroma changed the 130 nm anchor ({sky_plain.group(1)} -> "
        f"{sky_biroma.group(1)}) despite the NO-GO window guard"
    )


def test_compare_pdks_digital_readout_smaller() -> None:
    """The digital readout tier replaces per-bitline comparators with
    samplers, so the 130 nm anchor's area must shrink under
    --readout digital."""
    out_analog = _run_compare_pdks("--readout", "analog")
    out_digital = _run_compare_pdks("--readout", "digital")
    a = re.search(SKY_V4_ROW, out_analog, re.MULTILINE)
    d = re.search(SKY_V4_ROW, out_digital, re.MULTILINE)
    assert a and d
    assert float(d.group(1)) < float(a.group(1)), (
        f"digital readout {d.group(1)} not smaller than analog "
        f"{a.group(1)} -- readout-tier modeling broke"
    )
