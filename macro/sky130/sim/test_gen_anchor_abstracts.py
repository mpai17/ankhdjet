"""gen_anchor_abstracts.py must produce a syntactically-valid Liberty + LEF +
SystemVerilog wrapper + Yosys synth script for the supported (rows,
cols, pdk, biroma) combinations.

Each configuration is regenerated into a fresh tmp directory so the
test never depends on stale build/ artifacts.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import GEN_MACRO, MACRO_DIR, REPO


CONFIGS = [
    # (rows, cols, pdk, biroma)
    (64, 32, "sky130", False),
    (64, 32, "sky130", True),
    (64, 32, "gf180", False),
    (256, 256, "sky130", True),
]


def _stem(rows: int, cols: int, pdk: str, biroma: bool) -> str:
    s = f"cirom_array_{rows}x{cols}_{pdk}"
    if biroma:
        s += "_biroma"
    return s


@pytest.mark.parametrize("rows,cols,pdk,biroma", CONFIGS)
def test_gen_macro_emits_artifacts(tmp_path, rows, cols, pdk, biroma):
    # gen_anchor_abstracts.py writes into MACRO_DIR/build/. Run it, then copy the
    # outputs we care about into tmp_path for inspection so we don't
    # depend on whatever happened to be in the host build/ before.
    args = [sys.executable, str(GEN_MACRO), str(rows), str(cols), "--pdk", pdk]
    if biroma:
        args.append("--biroma")
    r = subprocess.run(args, cwd=MACRO_DIR, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"gen_anchor_abstracts failed:\n{r.stdout}\n{r.stderr}"

    stem = _stem(rows, cols, pdk, biroma)
    build = MACRO_DIR / "build"
    base = stem
    # Wrapper / synth script names are PDK-aware but biroma-agnostic
    # (biroma only changes area accounting, not RTL).
    wrapper_stem = stem.replace("_biroma", "")
    expected = {
        "lib":     build / f"{base}.lib",
        "lef":     build / f"{base}.lef",
        "wrapper": build / f"{wrapper_stem}_wrapper.sv",
        "synth":   build / f"{wrapper_stem}_synth.ys",
    }
    for kind, p in expected.items():
        assert p.exists(), f"{kind} not emitted: {p}\nstdout:\n{r.stdout}"


@pytest.mark.parametrize("rows,cols,pdk,biroma", CONFIGS)
def test_liberty_well_formed(rows, cols, pdk, biroma):
    stem = _stem(rows, cols, pdk, biroma)
    lib = MACRO_DIR / "build" / f"{stem}.lib"
    assert lib.exists(), f"missing {lib}"
    text = lib.read_text()
    # Liberty must declare a library, the cell, the supply, and a clock pin.
    assert re.search(rf"library\s*\(\s*{re.escape(stem)}\s*\)", text), \
        f"library header missing in {lib}"
    assert re.search(rf"cell\s*\(\s*cirom_array_{rows}x{cols}\s*\)", text), \
        f"cell block missing in {lib}"
    assert "pin (clk)" in text, "clk pin missing"
    # Balanced braces.
    assert text.count("{") == text.count("}"), \
        f"unbalanced braces in {lib}: {text.count('{')} vs {text.count('}')}"


@pytest.mark.parametrize("rows,cols,pdk,biroma", CONFIGS)
def test_liberty_lef_size_consistent(rows, cols, pdk, biroma):
    """The Liberty `area` field must match the LEF SIZE (W * H) within
    the wrapper-overhead headroom that gen_anchor_abstracts.py applies. Catches
    drift between the two emitters."""
    stem = _stem(rows, cols, pdk, biroma)
    lib = (MACRO_DIR / "build" / f"{stem}.lib").read_text()
    lef = (MACRO_DIR / "build" / f"{stem}.lef").read_text()

    m_area = re.search(r"area\s*:\s*([\d.]+)\s*;", lib)
    assert m_area, f"Liberty has no `area` field in {stem}.lib"
    lib_area_um2 = float(m_area.group(1))

    m_size = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", lef)
    assert m_size, f"LEF has no SIZE in {stem}.lef"
    lef_w, lef_h = float(m_size.group(1)), float(m_size.group(2))
    lef_area_um2 = lef_w * lef_h

    # Liberty `area` is the *active cell area*; LEF SIZE includes the
    # wrap_margin_x_um/wrap_margin_y_um padding. So lef_area >= lib_area
    # always, and the ratio must be reasonable (no more than 4x for
    # the smallest macros where the margin dominates).
    assert lef_area_um2 >= lib_area_um2 * 0.95, (
        f"{stem}: LEF area {lef_area_um2:.1f} < lib area {lib_area_um2:.1f}"
    )
    assert lef_area_um2 < lib_area_um2 * 5.0, (
        f"{stem}: LEF area {lef_area_um2:.1f} > 5x lib area {lib_area_um2:.1f}"
    )


@pytest.mark.parametrize("rows,cols,pdk,biroma", CONFIGS)
def test_lef_well_formed(rows, cols, pdk, biroma):
    stem = _stem(rows, cols, pdk, biroma)
    lef = MACRO_DIR / "build" / f"{stem}.lef"
    text = lef.read_text()
    # LEF must declare VERSION, MACRO, SIZE, and END MACRO.
    assert "VERSION" in text, "LEF missing VERSION"
    assert re.search(rf"MACRO\s+cirom_array_{rows}x{cols}", text), \
        "MACRO block missing"
    assert re.search(r"SIZE\s+[\d.]+\s+BY\s+[\d.]+", text), \
        "SIZE statement missing"
    assert "END LIBRARY" in text or "END\nLIBRARY" in text or text.rstrip().endswith("END LIBRARY"), \
        f"LEF missing END LIBRARY:\n{text[-200:]}"


@pytest.mark.parametrize("rows,cols,pdk,biroma", CONFIGS)
def test_wrapper_yosys_parses(rows, cols, pdk, biroma):
    """Yosys must read the auto-generated wrapper RTL without errors.
    Parse-only (read_verilog + hierarchy -check) — no synthesis."""
    if shutil.which("yosys") is None:
        pytest.skip("yosys not installed")
    stem = _stem(rows, cols, pdk, biroma)
    wrapper_stem = stem.replace("_biroma", "")
    wrapper = MACRO_DIR / "build" / f"{wrapper_stem}_wrapper.sv"
    assert wrapper.exists(), f"missing {wrapper}"

    yosys_cmd = (
        f"read_verilog -sv {wrapper}; "
        f"hierarchy -check -top cirom_array_{rows}x{cols}_test_harness; "
        "stat"
    )
    r = subprocess.run(
        ["yosys", "-q", "-p", yosys_cmd],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, (
        f"yosys parse failed for {wrapper}:\n"
        f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    )


# Synthesis test runs the wrapper RTL through Yosys all the way to
# gates against the SKY130 HD stdcell library. The committed
# synth.ys uses /host/... container paths; we rewrite those to host
# paths and run on a tmp copy. Only SKY130 configs (the GF180 .lib
# isn't installed locally).
SYNTH_CONFIGS = [(64, 32, "sky130", False), (64, 32, "sky130", True)]


@pytest.mark.parametrize("rows,cols,pdk,biroma", SYNTH_CONFIGS)
def test_yosys_synth_to_gates(tmp_path, rows, cols, pdk, biroma):
    import os
    sky130_lib_glob = "/home/mohnishp/.volare/volare/sky130/versions"
    candidates = list(Path(sky130_lib_glob).glob("*/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"))
    if not candidates:
        pytest.skip("sky130_fd_sc_hd stdcell .lib not installed in volare")
    stdcell_lib = candidates[0]

    stem = _stem(rows, cols, pdk, biroma)
    wrapper_stem = stem.replace("_biroma", "")
    macro_lib = MACRO_DIR / "build" / f"{stem}.lib"
    wrapper = MACRO_DIR / "build" / f"{wrapper_stem}_wrapper.sv"
    synth_ys = MACRO_DIR / "build" / f"{wrapper_stem}_synth.ys"
    assert all(p.exists() for p in (macro_lib, wrapper, synth_ys))

    # Rewrite the container-path synth.ys for host execution.
    text = synth_ys.read_text()
    text = text.replace("/host/.volare", str(Path.home() / ".volare"))
    text = text.replace("/host/repo", str(REPO))
    # The committed synth.ys uses .volare/sky130A directly; the host
    # also has it under .volare/volare/sky130/versions/<sha>/sky130A.
    if not (Path.home() / ".volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib").exists():
        text = text.replace(
            "/sky130A/libs.ref/sky130_fd_sc_hd",
            f"/volare/sky130/versions/{stdcell_lib.parents[4].name}/sky130A/libs.ref/sky130_fd_sc_hd",
        )
    # Also rewrite the macro lib path (it's already MACRO_DIR-relative
    # after /host/repo replacement).
    out_v = tmp_path / f"{wrapper_stem}_test_harness.gates.v"
    text = text.replace(
        f"/{wrapper_stem}_test_harness.gates.v",
        f"/{out_v.name}",
    )
    # Strip the absolute output path and write to tmp.
    rewritten = tmp_path / "synth.ys"
    # Replace the write_verilog destination with tmp_path/...
    import re as _re
    text = _re.sub(r"^write_verilog -noattr .*$",
                   f"write_verilog -noattr {out_v}",
                   text, flags=_re.MULTILINE)
    rewritten.write_text(text)

    r = subprocess.run(
        ["yosys", "-q", str(rewritten)],
        capture_output=True, text=True, timeout=300,
    )
    assert r.returncode == 0, (
        f"yosys synth failed for {stem}:\n"
        f"stdout:\n{r.stdout[-2000:]}\nstderr:\n{r.stderr[-2000:]}"
    )
    assert out_v.exists() and out_v.stat().st_size > 0, \
        f"synth produced no gate-level netlist at {out_v}"
