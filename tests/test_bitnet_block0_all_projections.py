"""Multi-matrix bit-exact validation across an entire BitNet b1.58-2B-4T
transformer block.

Take every weight matrix in block 0 (q, k, v, o for attention;
gate, up, down for the FFN), slice each to 128 rows x 64 cols (8192
weight positions), compile through emit_layer_nor + cirom_nor_tile, run
Verilator, and confirm bit-exact match against ternary_matmul_nor
Python reference.

If the existing single-matrix test (test_microsoft_bitnet_nor_layer.py)
proves one matmul works end-to-end, this proves the same architecture
generalizes across all seven matmul shapes the BitNet transformer block
uses — closing the architectural validation chain at the block level.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.backend.verilog import _column_widths, emit_layer_nor
from ankhdjet.frontend.hf import load_weights
from ankhdjet.frontend.ir import Layer, LayerType, QuantScheme, WeightTensor
from ankhdjet.reference.nor import ternary_matmul_nor
from tests._verilator_runner import build_and_run

TILE_SV = REPO_ROOT / "rtl" / "column" / "cirom_nor_tile.sv"


TB = r"""
`timescale 1ns/1ps
module tb_block0_proj;
    localparam int N = {N};
    localparam int M = {M};
    localparam int K = {K};
    localparam int WACC = {WACC};
    logic clk, rst_n, start, valid;
    logic [K*N-1:0]              act_flat;
    logic signed [WACC*M-1:0]    acc_flat;
    logic [K-1:0]                act_byte [0:N-1];

    ankhdjet_layer_{NAME} dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .act_flat(act_flat),
        .acc_flat(acc_flat), .valid(valid)
    );

    always #5 clk = ~clk;
    int i, j, cycles, acc_val;

    initial begin
        $readmemh("act.hex", act_byte);
        for (i = 0; i < N; i = i + 1) begin
            act_flat[K*(i+1)-1 -: K] = act_byte[i];
        end
        clk = 0; rst_n = 0; start = 0;
        #23 rst_n = 1;
        @(negedge clk); start = 1;
        @(negedge clk); start = 0;
        cycles = 0;
        while (!valid && cycles < 200000) begin
            @(negedge clk);
            cycles++;
        end
        if (!valid) begin $display("TIMEOUT"); $finish; end
        for (j = 0; j < M; j = j + 1) begin
            acc_val = $signed(acc_flat[WACC*(j+1)-1 -: WACC]);
            $display("OUT[%0d]=%0d", j, acc_val);
        end
        $display("CYCLES=%0d", cycles);
        $finish;
    end
endmodule
"""


# All 7 matmul slots in a BitNet b1.58-2B-4T transformer block.
BLOCK0_MATRICES = ["b0_q", "b0_k", "b0_v", "b0_o", "b0_gate", "b0_up", "b0_down"]

# Slice size used for each matrix. Same as the existing single-matrix
# test: 128 rows x 64 cols = 8192 weight positions per matrix, K=8 act bits.
SLICE_N = 128
SLICE_M = 64
K_BITS  = 8
SUBCOL  = 64


def _hf_cache_has_repo(repo_id: str) -> bool:
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    safe = repo_id.replace("/", "--")
    return any(cache_dir.glob(f"models--{safe}*"))


def run_one_matrix(model, mat_name: str, work_root: Path) -> tuple[bool, int, str]:
    """Compile + Verilate + bit-exact-check one matrix slice. Returns
    (passed, cycles, message)."""
    layer_full = next((L for L in model.layers if L.name == mat_name), None)
    if layer_full is None:
        return False, -1, f"matrix {mat_name} not in model"

    full = layer_full.weights["weight"].data
    full_n, full_m = full.shape
    n = min(SLICE_N, full_n)
    m = min(SLICE_M, full_m)
    W = full[:n, :m].astype(np.int8)

    rng = np.random.default_rng(seed=0xA2A4A + hash(mat_name) % (2**31))
    act = rng.integers(0, 2**K_BITS, size=n, dtype=np.int64)

    expected = ternary_matmul_nor(W, act, k_bits=K_BITS, subcol_rows=SUBCOL).astype(np.int64)

    layer = Layer(
        name=f"{mat_name}_slice",
        layer_type=LayerType.LINEAR,
        input_dim=n,
        output_dim=m,
        weights={"weight": WeightTensor(
            name="weight", data=W, scheme=QuantScheme.TERNARY)},
    )

    work = work_root / mat_name
    work.mkdir(parents=True, exist_ok=True)
    layer_v = work / f"ankhdjet_layer_{layer.name}.sv"
    layer_v.write_text(emit_layer_nor(layer, k_bits=K_BITS, subcol_rows=SUBCOL))

    _, wacc = _column_widths(n, K_BITS)
    tb_src = TB.format(N=n, M=m, K=K_BITS, WACC=wacc, NAME=layer.name)
    (work / "tb.sv").write_text(tb_src)
    (work / "act.hex").write_text("\n".join(f"{int(a):x}" for a in act) + "\n")

    stdout = build_and_run(
        workdir=work,
        sources=[TILE_SV, layer_v, work / "tb.sv"],
        top="tb_block0_proj",
        build_timeout=600.0, run_timeout=600.0,
    )

    measured = np.zeros(m, dtype=np.int64)
    cycles = -1
    for line in stdout.splitlines():
        mo = re.match(r"\s*OUT\[(\d+)\]=(-?\d+)", line)
        if mo:
            measured[int(mo.group(1))] = int(mo.group(2))
        mc = re.match(r"\s*CYCLES=(\d+)", line)
        if mc:
            cycles = int(mc.group(1))

    n_match = int((measured == expected).sum())
    passed = n_match == m
    msg = (f"slice {n}x{m}, +1/0/-1 = {(W==1).sum()}/{(W==0).sum()}/{(W==-1).sum()}, "
           f"cycles={cycles}, match={n_match}/{m}")
    return passed, cycles, msg


def main() -> int:
    repo_id = "microsoft/bitnet-b1.58-2B-4T"
    if not _hf_cache_has_repo(repo_id):
        print(f"[skip] HF cache lacks {repo_id}; download manually first")
        return 0

    print(f"Loading {repo_id} weights ...")
    model, _, _ = load_weights(repo_id, progress=False)

    work_root = Path(tempfile.mkdtemp(prefix="ankhdjet_block0_"))
    print(f"Verilator workdir: {work_root}")

    results: list[tuple[str, bool, int, str]] = []
    t0 = time.time()
    for mat in BLOCK0_MATRICES:
        print(f"\n=== {mat} ===")
        try:
            passed, cycles, msg = run_one_matrix(model, mat, work_root)
        except Exception as e:
            passed, cycles, msg = False, -1, f"exception: {e!r}"
        marker = "ok" if passed else "FAIL"
        print(f"  [{marker}] {msg}")
        results.append((mat, passed, cycles, msg))

    elapsed = time.time() - t0
    print(f"\n=== Summary (elapsed {elapsed:.1f} s) ===")
    n_ok = sum(1 for _, p, _, _ in results if p)
    for mat, passed, cycles, msg in results:
        marker = "ok" if passed else "FAIL"
        print(f"  [{marker:>4}] {mat:<10}  {msg}")
    print(f"\n{n_ok}/{len(results)} matrices bit-exact through NOR-array RTL")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
