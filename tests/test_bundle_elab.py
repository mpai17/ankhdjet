"""Design-bundle elaboration and smoke simulation with Icarus: the
compiled bundle must elaborate standalone from its filelist, and one
layer's grid top must reproduce the reference matrix-vector product
through the copied bench, exactly as a pip user would run it."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.backend.bundle import emit_design_bundle
from ankhdjet.frontend.ir import Layer, LayerType, ModelIR, QuantScheme, WeightTensor

pytestmark = pytest.mark.skipif(shutil.which("iverilog") is None,
                                reason="iverilog not installed")

N, M = 8, 4


def _bundle(tmp_path: Path, harden: bool = False) -> tuple[Path, np.ndarray]:
    rng = np.random.default_rng(7)
    W = rng.integers(-1, 2, size=(N, M)).astype(np.int8)
    model = ModelIR(name="tiny", layers=[
        Layer(name="blk_1", layer_type=LayerType.LINEAR,
              weights={"weight": WeightTensor(name="weight", data=W,
                                              scheme=QuantScheme.TERNARY)},
              input_dim=N, output_dim=M)])
    emit_design_bundle(model, tmp_path, macro_rows=N, macro_cols=M,
                       harden=harden)
    return tmp_path, W


def test_bundle_elaborates(tmp_path):
    out, _ = _bundle(tmp_path)
    subprocess.run(
        ["iverilog", "-g2012", "-f", "filelist.f", "-o", "bundle.vvp"],
        cwd=out, check=True, capture_output=True, text=True)


def test_hardened_view_elaborates(tmp_path):
    out, _ = _bundle(tmp_path, harden=True)
    subprocess.run(
        ["iverilog", "-g2012", "-f", "filelist_hard.f", "-o", "hard.vvp"],
        cwd=out, check=True, capture_output=True, text=True)


def test_bundle_smoke_sim_bit_exact(tmp_path):
    out, W = _bundle(tmp_path)
    rng = np.random.default_rng(11)
    act = rng.integers(0, 16, size=N).astype(np.int64)
    golden = act @ W.astype(np.int64)

    (out / "act.memh").write_text(
        "\n".join(f"{int(a):02x}" for a in act) + "\n")
    (out / "golden.memh").write_text(
        "\n".join(f"{int(g) & 0xFFFF:04x}" for g in golden) + "\n")

    subprocess.run(
        ["iverilog", "-g2012",
         f"-DANKHDJET_N={N}", f"-DANKHDJET_M={M}",
         "-DANKHDJET_GRID_TOP=ankhdjet_grid_blk_1",
         "-f", "filelist.f", "sim/tb_grid.sv", "-o", "tb.vvp"],
        cwd=out, check=True, capture_output=True, text=True)
    run = subprocess.run(["vvp", "tb.vvp"], cwd=out, check=True,
                         capture_output=True, text=True)
    assert "TB PASS" in run.stdout, run.stdout
