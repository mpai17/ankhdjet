"""End-to-end pipeline validation: two chained BitLinear matmuls from real
microsoft/bitnet-b1.58-2B-4T weights, compiled through `emit_pipeline` and
run in Verilator, bit-exact against the Python reference chain
(ternary_matmul_nor -> requantize -> ternary_matmul_nor).

This is the smallest end-to-end demonstration of the compiler:
real ternary weights -> our IR -> `emit_pipeline` -> simulator -> integer
output identical to the reference. Each link in the chain
(load_weights, ternary_matmul_nor vs PyTorch, between_layer vs requantize,
cirom_nor_tile vs ternary_matmul_nor) is independently validated by other
tests; this composes them.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.backend.verilog import _column_widths, emit_pipeline
from ankhdjet.frontend.hf import load_weights
from ankhdjet.frontend.ir import Layer, LayerType, QuantScheme, WeightTensor
from ankhdjet.reference.between import requantize
from ankhdjet.reference.nor import ternary_matmul_nor
from tests._verilator_runner import build_and_run

TILE_SV = REPO_ROOT / "rtl" / "column" / "cirom_nor_tile.sv"
BL_SV   = REPO_ROOT / "rtl" / "between_layer" / "between_layer.sv"
REQ_SV  = REPO_ROOT / "rtl" / "between_layer" / "requantize.sv"


TB = r"""
`timescale 1ns/1ps
module tb_full_model;
    localparam int N1       = {N1};
    localparam int M2       = {M2};
    localparam int K        = {K};
    localparam int WACC2    = {WACC2};

    logic clk, rst_n, start, valid;
    logic [K*N1-1:0]              act_flat;
    logic signed [WACC2*M2-1:0]   acc_flat;
    logic [K-1:0] act_byte [0:N1-1];

    ankhdjet_pipeline_{NAME} dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .act_flat(act_flat),
        .acc_flat(acc_flat), .valid(valid)
    );

    always #5 clk = ~clk;
    int i, j, cycles, acc_val;

    initial begin
        $readmemh("act.hex", act_byte);
        for (i = 0; i < N1; i = i + 1) begin
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
        for (j = 0; j < M2; j = j + 1) begin
            acc_val = $signed(acc_flat[WACC2*(j+1)-1 -: WACC2]);
            $display("OUT[%0d]=%0d", j, acc_val);
        end
        $display("CYCLES=%0d", cycles);
        $finish;
    end
endmodule
"""


def _hf_cache_has_repo(repo_id: str) -> bool:
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    target = cache / "hub" / ("models--" + repo_id.replace("/", "--"))
    return target.exists() and any(target.rglob("*.safetensors"))


def main() -> int:
    repo_id = "microsoft/bitnet-b1.58-2B-4T"
    if not _hf_cache_has_repo(repo_id):
        print(f"[skip] {repo_id} not in HF cache; "
              f"run `uv run python -m ankhdjet.frontend.hf weights` first.")
        return 0

    print(f"Loading {repo_id} weights ...", flush=True)
    model, _, _ = load_weights(repo_id, progress=False)

    full_q = next(L for L in model.layers if L.name == "b0_q").weights["weight"].data
    full_o = next(L for L in model.layers if L.name == "b0_o").weights["weight"].data

    n1, m1 = 64, 32
    m2     = 16
    W1 = full_q[:n1, :m1].copy()
    W2 = full_o[:m1, :m2].copy()

    print(f"  W1 = b0_q[:{n1},:{m1}]  +1/-1/0 = "
          f"{int((W1==1).sum())}/{int((W1==-1).sum())}/{int((W1==0).sum())}")
    print(f"  W2 = b0_o[:{m1},:{m2}]  +1/-1/0 = "
          f"{int((W2==1).sum())}/{int((W2==-1).sum())}/{int((W2==0).sum())}")

    layer1 = Layer(
        name="msbn_full_l1",
        layer_type=LayerType.LINEAR,
        weights={"weight": WeightTensor(name="weight", data=W1,
                                        scheme=QuantScheme.TERNARY)},
        input_dim=n1, output_dim=m1,
    )
    layer2 = Layer(
        name="msbn_full_l2",
        layer_type=LayerType.LINEAR,
        weights={"weight": WeightTensor(name="weight", data=W2,
                                        scheme=QuantScheme.TERNARY)},
        input_dim=m1, output_dim=m2,
    )

    k_bits  = 8
    q_frac  = 8
    scale_q = 64           # Q.8: 0.25, keeps acc * scale within unsigned K-bit range after ReLU
    subcol1 = 32           # n1=64 -> two 32-row sub-columns
    subcol2 = 16           # m1=32 -> two 16-row sub-columns

    rng = np.random.default_rng(0xCAFE_BABE)
    act = rng.integers(0, 1 << k_bits, size=n1, dtype=np.int64)

    acc1_ref = ternary_matmul_nor(W1, act, k_bits=k_bits, subcol_rows=subcol1)
    act2_ref = requantize(acc1_ref, scale_q=scale_q, q_frac=q_frac,
                          k_bits=k_bits, activation="relu")
    acc2_ref = ternary_matmul_nor(W2, act2_ref.astype(np.int64),
                                  k_bits=k_bits, subcol_rows=subcol2)
    print(f"  Python ref chain: acc1[{m1}] -> requantize -> act2[{m1}] -> acc2[{m2}]")
    print(f"  acc1 range [{acc1_ref.min()}, {acc1_ref.max()}]; "
          f"act2 range [{act2_ref.min()}, {act2_ref.max()}]; "
          f"acc2 range [{acc2_ref.min()}, {acc2_ref.max()}]")

    _, wacc2 = _column_widths(m1, k_bits)
    pipeline_name = "msbn_full"

    with tempfile.TemporaryDirectory(prefix="msbn_full_") as td:
        work = Path(td)
        pipeline_src = emit_pipeline(
            [layer1, layer2], name=pipeline_name,
            k_bits=k_bits, subcol_rows=[subcol1, subcol2],
            scales_q=[scale_q], q_frac=q_frac, activation=0,
        )
        (work / "pipeline.sv").write_text(pipeline_src)
        tb_src = TB.format(
            N1=n1, M2=m2, K=k_bits, WACC2=wacc2, NAME=pipeline_name,
        )
        (work / "tb.sv").write_text(tb_src)
        (work / "act.hex").write_text(
            "\n".join(f"{int(a):x}" for a in act) + "\n")

        print(f"Building + running Verilator pipeline "
              f"(N1={n1} -> M1={m1} -> M2={m2}, K={k_bits}, "
              f"scale_q={scale_q}, subcols=[{subcol1},{subcol2}]) ...", flush=True)
        stdout = build_and_run(
            workdir=work,
            sources=[TILE_SV, REQ_SV, BL_SV,
                     work / "pipeline.sv", work / "tb.sv"],
            top="tb_full_model",
            build_timeout=600.0, run_timeout=600.0,
        )

    measured = np.zeros(m2, dtype=np.int64)
    cycles = -1
    for line in stdout.splitlines():
        mo = re.match(r"\s*OUT\[(\d+)\]=(-?\d+)", line)
        if mo:
            measured[int(mo.group(1))] = int(mo.group(2))
        mc = re.match(r"\s*CYCLES=(\d+)", line)
        if mc:
            cycles = int(mc.group(1))

    matches = int((measured == acc2_ref).sum())
    print(f"  Verilator chain finished in {cycles} cycles; "
          f"{matches}/{m2} outputs bit-exact vs Python reference chain")
    if matches != m2:
        mis = np.where(measured != acc2_ref)[0]
        for j in mis[:3]:
            print(f"    out[{j}]: expected={acc2_ref[j]} got={measured[j]}")
        print("[FAIL]")
        return 1
    print(f"[ok] microsoft/bitnet-b1.58-2B-4T (b0_q[:{n1},:{m1}] -> "
          f"between_layer -> b0_o[:{m1},:{m2}]) bit-exact through compiled RTL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
