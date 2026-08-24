"""Bit-exact validation of the grid RTL emitter.

Emits a multi-macro grid top for a random ternary layer, simulates it with
behavioral chunk arrays, and checks the streamed matrix-vector result
against an independent numpy integer matmul. This exercises the new thing
the single-macro path does not: inter-macro accumulation across a
GRID_R x GRID_C grid, including ragged (zero-padded) edges.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.backend.grid_rtl import emit_grid

GRID_DIR = REPO_ROOT / "rtl" / "grid"
TOP = "ankhdjet_grid_test"


def _run_case(tmp_path: Path, n: int, m: int, mr: int, mc: int,
              seed: int) -> None:
    rng = np.random.default_rng(seed)
    W = rng.choice([-1, 0, 1], size=(n, m)).astype(np.int8)
    act = rng.integers(0, 1 << 4, size=n).astype(np.int64)   # 4-bit unsigned
    golden = (act @ W.astype(np.int64))                       # (m,) signed

    g = emit_grid(W, tmp_path, layer_name="L", top_name=TOP,
                  macro_rows=mr, macro_cols=mc, act_w=4, acc_w=16)

    # the grid computes the padded N x M layer; padded rows/cols are zero
    # weights, so pad activations and golden to the grid's dimensions.
    act_p = np.zeros(g["N"], dtype=np.int64); act_p[:n] = act
    golden_p = np.zeros(g["M"], dtype=np.int64); golden_p[:m] = golden
    (tmp_path / "act.memh").write_text(
        "\n".join(f"{int(a):02x}" for a in act_p) + "\n")
    (tmp_path / "golden.memh").write_text(
        "\n".join(f"{int(v) & 0xffff:04x}" for v in golden_p) + "\n")

    vvp = tmp_path / "grid.vvp"
    r = subprocess.run(
        ["iverilog", "-g2012",
         f"-DANKHDJET_GRID_TOP={TOP}",
         f"-DANKHDJET_N={g['N']}", f"-DANKHDJET_M={g['M']}",
         "-o", str(vvp),
         str(g["top"]), str(g["afe"]),
         str(GRID_DIR / "cirom_grid_ctrl.sv"),
         str(GRID_DIR / "cirom_array_beh.sv"),
         str(GRID_DIR / "sim" / "tb_grid.sv")],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"iverilog failed:\n{r.stderr}"

    # behavioral chunks $readmemh relative to out_dir; run vvp there
    r = subprocess.run(["vvp", str(vvp)], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"vvp failed:\n{r.stderr}"
    assert "TB PASS" in r.stdout, (
        f"grid {n}x{m} tiled {mr}x{mc}:\n{r.stdout[-2000:]}")


def test_grid_exact_2x2(tmp_path: Path) -> None:
    # 16x8 layer, 2x2 grid of 8x4 macros: clean tiling
    _run_case(tmp_path, n=16, m=8, mr=8, mc=4, seed=1)


def test_grid_exact_ragged(tmp_path: Path) -> None:
    # 20x10 layer, 8x4 macros -> 3x3 grid with zero-padded edges
    _run_case(tmp_path, n=20, m=10, mr=8, mc=4, seed=2)


if __name__ == "__main__":
    import tempfile
    for nm, args in {
        "2x2 clean": (16, 8, 8, 4, 1),
        "3x3 ragged": (20, 10, 8, 4, 2),
        "single macro": (8, 4, 8, 4, 3),
    }.items():
        with tempfile.TemporaryDirectory() as d:
            _run_case(Path(d), *args)
        print(f"[ok] grid {nm}: bit-exact")
    print("[ok] grid emitter: inter-macro accumulation bit-exact vs numpy")
