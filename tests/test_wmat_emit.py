"""Validation of the compiler's mask-program (.wmat) emitter.

Three checks:
  1. Round-trip: random ternary matrices survive emit -> parse exactly.
  2. Artifact cross-check: the committed weights/test0.wmat agrees bit
     for bit with the signed-off macro's .wpos/.wneg memh views (the
     same programming data through the independent generator chain).
  3. Tile integration: emit_tt_digital with a weights_matrix writes the
     mask program alongside the RTL, and it parses back identically.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.package


import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.backend.wmat import emit_wmat, emit_layer_wmat, load_wmat
from ankhdjet.frontend.ir import Layer, LayerType, QuantScheme, WeightTensor

WMAT_TEST0 = REPO_ROOT / "weights" / "test0.wmat"
MEMH_BASE = REPO_ROOT / "macro" / "sky130" / "abstracts" / "macro_array_pc_64x32_test0"


def _load_memh_bits(path: Path) -> np.ndarray:
    """Parse a .memh view (one 32-bit hex word per row; bit c = column c)."""
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        v = int(line, 16)
        rows.append([(v >> c) & 1 for c in range(32)])
    return np.asarray(rows, dtype=np.int8)


def test_wmat_round_trip(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    for n, m in [(64, 32), (17, 5), (1, 1), (128, 64)]:
        W = rng.choice([-1, 0, 1], size=(n, m)).astype(np.int8)
        p = emit_wmat(W, tmp_path / f"w_{n}x{m}.wmat")
        rt = load_wmat(p)
        assert np.array_equal(rt, W), f"round-trip mismatch at {n}x{m}"


def test_wmat_matches_signed_off_memh_views() -> None:
    W = load_wmat(WMAT_TEST0)
    assert W.shape == (64, 32), f"test0.wmat shape {W.shape}"
    wpos = _load_memh_bits(MEMH_BASE.with_suffix(".wpos.memh"))
    wneg = _load_memh_bits(MEMH_BASE.with_suffix(".wneg.memh"))
    assert np.array_equal(wpos, (W == 1).astype(np.int8)), "wpos view disagrees"
    assert np.array_equal(wneg, (W == -1).astype(np.int8)), "wneg view disagrees"


def test_layer_and_tile_emission(tmp_path: Path) -> None:
    rng = np.random.default_rng(11)
    W = rng.choice([-1, 0, 1], size=(64, 32)).astype(np.int8)
    layer = Layer(
        name="l0", layer_type=LayerType.LINEAR,
        weights={"weight": WeightTensor(name="weight", data=W,
                                        scheme=QuantScheme.TERNARY)},
        input_dim=64, output_dim=32,
    )
    p = emit_layer_wmat(layer, tmp_path / "l0.wmat")
    assert np.array_equal(load_wmat(p), W)

    from ankhdjet.backend.tt_digital import emit_tt_digital
    r = emit_tt_digital(tmp_path, weights="audit", weights_matrix=W)
    assert r["wmat"].name == "audit.wmat"
    assert np.array_equal(load_wmat(r["wmat"]), W)


def test_macro_grid_emission(tmp_path: Path) -> None:
    """Grid tiling: ragged edges zero-pad, chunks round-trip to the
    exact layer slice, manifest totals reconcile."""
    import json
    from ankhdjet.backend.macro_grid import emit_layer_grid
    rng = np.random.default_rng(23)
    W = rng.choice([-1, 0, 1], size=(150, 70)).astype(np.int8)
    layer = Layer(
        name="g0", layer_type=LayerType.LINEAR,
        weights={"weight": WeightTensor(name="weight", data=W,
                                        scheme=QuantScheme.TERNARY)},
        input_dim=150, output_dim=70,
    )
    man = emit_layer_grid(layer, tmp_path, macro_rows=64, macro_cols=32)
    assert (man.grid_r, man.grid_c, man.n_macros) == (3, 3, 9)
    assert man.padded_positions == 3 * 3 * 64 * 32 - 150 * 70
    for i in range(3):
        for j in range(3):
            chunk = load_wmat(tmp_path / "g0" / f"r{i}_c{j}.wmat")
            r0, c0 = i * 64, j * 32
            ref = np.zeros((64, 32), dtype=np.int8)
            sl = W[r0:r0 + 64, c0:c0 + 32]
            ref[: sl.shape[0], : sl.shape[1]] = sl
            assert np.array_equal(chunk, ref), f"chunk r{i}_c{j}"
    j = json.loads((tmp_path / "g0" / "manifest.json").read_text())
    assert len(j["chunks_sha256_16"]) == 9


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_wmat_round_trip(Path(d))
        test_wmat_matches_signed_off_memh_views()
        test_layer_and_tile_emission(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_macro_grid_emission(Path(d))
    print("[ok] wmat emitter: round-trip, signed-off memh cross-check, "
          "tile integration, macro-grid tiling")
