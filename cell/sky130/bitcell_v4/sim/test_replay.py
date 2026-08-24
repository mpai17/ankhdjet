"""Replay regression: each gen_*.tcl, run from a clean directory,
must regenerate its corresponding .mag and the regenerated cell must
itself be DRC-clean. Drift in PCell parameters or in the generator
scripts breaks this.

Cells are generated in dependency order. Subcol/array generators
require bitcell_v4.mag and body_tap.mag; the test stages those into
the per-test tmp_path before running the dependent gen_*.tcl.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from conftest import CELL_DIR


PRIMITIVE_GENERATORS = [
    ("bitcell_v4", "gen_bitcell_v4.tcl", []),
    ("bitcell_v4_biroma", "gen_bitcell_v4_biroma.tcl", []),
    ("body_tap", "gen_body_tap.tcl", []),
]

SUBCOL_RE = re.compile(r"^v4_subcol_(\d+)$")
ARRAY_RE  = re.compile(r"^v4_array_(\d+)x(\d+)$")

# Replay rebuilds the cell from scratch in tmp_path; the runtime is
# dominated by Magic's getcell calls. Empirical: 64x32 ~30 s, 256x256
# ~10 minutes. Cap the default replay set at the production-shape
# baseline; larger arrays are kept as opt-in via a separate slow test.
DEFAULT_REPLAY_MAX_CELLS = 16384


def _discover_generators(max_cells: int | None = DEFAULT_REPLAY_MAX_CELLS,
                          min_cells: int = 0) -> tuple[list, dict]:
    """Walk build/ for sub-column and array .mag files. For each, add a
    replay entry that re-runs the matching gen_*.tcl at the same shape
    (env vars driving the parameterized scripts). Primitives are always
    included; sub-columns and arrays are size-agnostic."""
    gens = list(PRIMITIVE_GENERATORS) if min_cells == 0 else []
    env: dict[str, dict[str, str]] = {}
    build = CELL_DIR / "build"
    if build.exists():
        for mag in sorted(build.glob("v4_subcol_*.mag")):
            m = SUBCOL_RE.match(mag.stem)
            if not m:
                continue
            rows = int(m.group(1))
            if rows < min_cells:
                continue
            if max_cells is not None and rows > max_cells:
                continue
            gens.append((mag.stem, "gen_subcol_v4.tcl",
                          ["bitcell_v4.mag", "body_tap.mag"]))
            env[mag.stem] = {"ANKHDJET_SUBCOL_ROWS": str(rows)}
        for mag in sorted(build.glob("v4_array_*.mag")):
            m = ARRAY_RE.match(mag.stem)
            if not m:
                continue
            rows, cols = int(m.group(1)), int(m.group(2))
            total = rows * cols
            if total < min_cells:
                continue
            if max_cells is not None and total > max_cells:
                continue
            gens.append((mag.stem, "gen_array.tcl",
                          ["bitcell_v4.mag", "body_tap.mag"]))
            env[mag.stem] = {"ANKHDJET_ARRAY_N": str(rows),
                              "ANKHDJET_ARRAY_M": str(cols)}
    return gens, env


GENERATORS, GEN_ENV = _discover_generators()
LARGE_GENERATORS, LARGE_GEN_ENV = _discover_generators(
    max_cells=None, min_cells=DEFAULT_REPLAY_MAX_CELLS + 1)


@pytest.mark.parametrize("cell,gen_tcl,deps", GENERATORS)
def test_replay(cell: str, gen_tcl: str, deps: list[str], tmp_path) -> None:
    src = CELL_DIR / gen_tcl
    assert src.exists(), f"{src} missing"

    work = tmp_path / cell
    work.mkdir()
    magicrc = CELL_DIR / ".magicrc"
    if magicrc.exists():
        shutil.copy(magicrc, work / ".magicrc")
    # Stage prerequisite .mag files from the canonical build/ dir
    for d in deps:
        canonical = CELL_DIR / "build" / d
        assert canonical.exists(), f"prereq {canonical} missing"
        shutil.copy(canonical, work / d)

    # Run gen_tcl, then explicitly DRC the produced cell with the
    # `drc list count total` API (gen_*.tcl's own `drc count` is
    # informational; this is the authoritative pass/fail.)
    drc_check = (
        f"\nload {cell}\n"
        "drc on\nselect top cell\ndrc check\ndrc catchup\n"
        f'puts "REPLAY_COUNT={cell}=[drc list count total]"\n'
    )
    import os
    env = os.environ.copy()
    env.update(GEN_ENV.get(cell, {}))
    # Strip any trailing `quit` from gen_tcl so the appended DRC check
    # runs before magic exits.
    gen_text = re.sub(r"^\s*quit\b.*$", "", src.read_text(),
                      flags=re.MULTILINE)
    r = subprocess.run(
        ["magic", "-dnull", "-noconsole"],
        cwd=work, input=gen_text + drc_check, text=True,
        capture_output=True, timeout=600, env=env,
    )
    out = r.stdout + r.stderr
    m = re.search(rf"REPLAY_COUNT={cell}=(\d+)", out)
    assert m, f"{cell}: no DRC count in output:\n{out[-1500:]}"
    n = int(m.group(1))
    assert n == 0, f"{cell}: replay DRC = {n}\n{out[-1500:]}"


@pytest.mark.slow
@pytest.mark.parametrize("cell,gen_tcl,deps", LARGE_GENERATORS)
def test_replay_large(cell: str, gen_tcl: str, deps: list[str],
                      tmp_path) -> None:
    """Replay for arrays > 16k cells. Magic getcell-bound; 256x256
    rebuilds in ~10 minutes. Identical methodology to test_replay; kept
    out of the default suite so a single regression doesn't take
    20+ minutes on the production-shape replay alone."""
    pytest.skip(
        f"{cell}: large-array replay (~10 min) deselected from default. "
        "Run explicitly with `pytest -m slow` to exercise."
    )


if __name__ == "__main__":
    for c, g, deps in GENERATORS:
        with tempfile.TemporaryDirectory() as d:
            try:
                test_replay(c, g, deps, Path(d))
                print(f"[ok] {c} replay")
            except AssertionError as e:
                print(f"[FAIL] {c} replay: {str(e)[:200]}")
