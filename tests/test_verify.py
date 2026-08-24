"""The emission audit at the pip envelope: reassembled mask programs
must match the reference bit-for-bit, and both defect classes the
audit exists for (content mismatch, nonzero padding) must be caught."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.backend.macro_grid import emit_model
from ankhdjet.backend.verify import verify_model
from ankhdjet.frontend.ir import Layer, LayerType, ModelIR, QuantScheme, WeightTensor

pytestmark = pytest.mark.package


def _layer(name: str, n: int, m: int, seed: int = 0) -> Layer:
    rng = np.random.default_rng(seed)
    W = rng.integers(-1, 2, size=(n, m)).astype(np.int8)
    return Layer(name=name, layer_type=LayerType.LINEAR,
                 weights={"weight": WeightTensor(name="weight", data=W,
                                                 scheme=QuantScheme.TERNARY)},
                 input_dim=n, output_dim=m)


def _emitted(tmp_path):
    model = ModelIR(name="tiny", layers=[
        _layer("blk.0", 10, 6, seed=0),   # padded at 8x4 chunks
        _layer("blk_1", 8, 4, seed=1),    # exact fit
    ])
    emit_model(model, tmp_path, macro_rows=8, macro_cols=4)
    return model


def test_clean_emission_passes(tmp_path):
    model = _emitted(tmp_path)
    res = verify_model(model, tmp_path)
    assert res["ok"] and res["n_ok"] == 2 and res["failures"] == []


def test_content_corruption_caught(tmp_path):
    model = _emitted(tmp_path)
    p = tmp_path / "blk_1" / "r0_c0.wmat"
    text = p.read_text()
    flip = {"+": "-", "-": "0", "0": "+"}[text[0]]
    p.write_text(flip + text[1:])
    res = verify_model(model, tmp_path)
    assert not res["ok"]
    assert res["failures"] == [("blk_1", "content mismatch vs checkpoint")]


def test_nonzero_padding_caught(tmp_path):
    model = _emitted(tmp_path)
    # blk.0 is 10x6 at 8x4 chunks: chunk r1_c1 covers rows 8-15, cols
    # 4-7, so its last row is pure padding; program one padded cell.
    p = tmp_path / "blk.0" / "r1_c1.wmat"
    lines = p.read_text().splitlines()
    lines[-1] = "+" + lines[-1][1:]
    p.write_text("\n".join(lines) + "\n")
    res = verify_model(model, tmp_path)
    assert not res["ok"]
    assert res["failures"][0][0] == "blk.0"
    assert "padding" in res["failures"][0][1]
