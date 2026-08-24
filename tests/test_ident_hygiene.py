"""Emission-boundary name hygiene: arbitrary layer/model names must
never reach the RTL as illegal Verilog identifiers, silently-colliding
module names, or path tokens that would break the SV string literal
quoting them."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.backend.grid_rtl import emit_grid
from ankhdjet.backend.idents import check_unique, path_token, sv_ident
from ankhdjet.backend.verilog import emit_layer_nor, emit_pipeline
from ankhdjet.frontend.ir import Layer, LayerType, QuantScheme, WeightTensor

pytestmark = pytest.mark.package


def _layer(name: str, n: int = 4, m: int = 3, seed: int = 0) -> Layer:
    rng = np.random.default_rng(seed)
    W = rng.integers(-1, 2, size=(n, m)).astype(np.int8)
    return Layer(
        name=name, layer_type=LayerType.LINEAR,
        weights={"weight": WeightTensor(name="weight", data=W,
                                        scheme=QuantScheme.TERNARY)},
        input_dim=n, output_dim=m,
    )


def test_sv_ident_legalizes():
    assert sv_ident("bitnet_b1.58_2B_4T") == "bitnet_b1_58_2B_4T"
    assert sv_ident("2b4t") == "_2b4t"
    assert sv_ident("b0_q") == "b0_q"
    with pytest.raises(ValueError):
        sv_ident("")


def test_check_unique_refuses_collisions_and_duplicates():
    check_unique(["b0_q", "b0_k", "b1.58"])
    with pytest.raises(ValueError, match="collides"):
        check_unique(["l.a", "l_a"])
    with pytest.raises(ValueError, match="duplicated"):
        check_unique(["x", "x"])


def test_path_token_accepts_and_refuses():
    assert path_token("b1.58-x_Y") == "b1.58-x_Y"
    for bad in ("has space", 'has"quote', "a/b", "a\\b", ".."):
        with pytest.raises(ValueError):
            path_token(bad)


def test_emit_layer_module_name_is_legal():
    v = emit_layer_nor(_layer("attn.0.q"))
    assert "module ankhdjet_layer_attn_0_q (" in v
    assert "attn.0.q" in v  # provenance stays in the comment
    assert re.search(r"module\s+\S*\.", v) is None


def test_emit_pipeline_legalizes_all_names():
    layers = [_layer("blk.0", 4, 3), _layer("blk.1", 3, 2, seed=1)]
    v = emit_pipeline(layers, name="b1.58")
    assert "module ankhdjet_pipeline_b1_58 (" in v
    assert "ankhdjet_layer_blk_0 u_l0 (" in v
    assert "ankhdjet_layer_blk_1 u_l1 (" in v


def test_emit_pipeline_refuses_colliding_layer_names():
    layers = [_layer("blk.0", 4, 3), _layer("blk_0", 3, 2, seed=1)]
    with pytest.raises(ValueError, match="collides"):
        emit_pipeline(layers, name="p")


def test_emit_grid_validates_names(tmp_path):
    W = np.zeros((8, 4), dtype=np.int8)
    for bad in ("has space", 'has"quote'):
        with pytest.raises(ValueError):
            emit_grid(W, tmp_path, layer_name=bad)
    g = emit_grid(W, tmp_path, layer_name="L", top_name="grid.top")
    assert g["top"].name == "grid_top.sv"
    assert "module grid_top (" in g["top"].read_text()
