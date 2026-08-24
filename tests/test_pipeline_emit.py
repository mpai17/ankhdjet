"""Bit-exact Verilator validation of ankhdjet.backend.verilog.emit_pipeline.

Builds a 3-layer ternary chain (random weights) and compares the Verilator
output of the emitted `ankhdjet_pipeline_*` top against the Python reference
chain (ternary_matmul_nor -> requantize -> ternary_matmul_nor -> requantize
-> ternary_matmul_nor). Exercises the multi-layer valid/start handshake
the manual TB in test_full_model.py was hand-glued to.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.backend.verilog import _column_widths, emit_pipeline
from ankhdjet.frontend.ir import Layer, LayerType, QuantScheme, WeightTensor
from ankhdjet.reference.between import requantize
from ankhdjet.reference.nor import ternary_matmul_nor
from tests._verilator_runner import build_and_run

TILE_SV = REPO_ROOT / "rtl" / "column" / "cirom_nor_tile.sv"
BL_SV   = REPO_ROOT / "rtl" / "between_layer" / "between_layer.sv"
REQ_SV  = REPO_ROOT / "rtl" / "between_layer" / "requantize.sv"


TB = r"""
`timescale 1ns/1ps
module tb_pipeline;
    localparam int N0       = {N0};
    localparam int MLAST    = {MLAST};
    localparam int K        = {K};
    localparam int WACCLAST = {WACCLAST};

    logic clk, rst_n, start, valid;
    logic [K*N0-1:0]              act_flat;
    logic signed [WACCLAST*MLAST-1:0] acc_flat;
    logic [K-1:0] act_byte [0:N0-1];

    ankhdjet_pipeline_{NAME} dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .act_flat(act_flat),
        .acc_flat(acc_flat), .valid(valid)
    );

    always #5 clk = ~clk;
    int i, j, cycles, acc_val;

    initial begin
        $readmemh("act.hex", act_byte);
        for (i = 0; i < N0; i = i + 1) begin
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
        for (j = 0; j < MLAST; j = j + 1) begin
            acc_val = $signed(acc_flat[WACCLAST*(j+1)-1 -: WACCLAST]);
            $display("OUT[%0d]=%0d", j, acc_val);
        end
        $display("CYCLES=%0d", cycles);
        $finish;
    end
endmodule
"""


def _make_layer(name: str, n: int, m: int, rng) -> tuple[Layer, np.ndarray]:
    W = rng.choice([-1, 0, 1], size=(n, m), p=[0.30, 0.40, 0.30]).astype(np.int64)
    layer = Layer(
        name=name,
        layer_type=LayerType.LINEAR,
        weights={"weight": WeightTensor(name="weight", data=W,
                                        scheme=QuantScheme.TERNARY)},
        input_dim=n, output_dim=m,
    )
    return layer, W


def main() -> int:
    rng = np.random.default_rng(0xBEEF_1234)

    shapes = [(8, 16), (16, 12), (12, 8)]
    k_bits = 4
    subcol_rows = 16
    q_frac = 8
    scales_q = [1 << q_frac, 1 << q_frac]
    pipeline_name = "test3"

    layers: list[Layer] = []
    weights: list[np.ndarray] = []
    for idx, (n, m) in enumerate(shapes):
        L, W = _make_layer(f"l{idx}", n, m, rng)
        layers.append(L)
        weights.append(W)

    n0 = shapes[0][0]
    act = rng.integers(0, 1 << k_bits, size=n0, dtype=np.int64)

    cur = act
    for i, W in enumerate(weights):
        acc = ternary_matmul_nor(W, cur, k_bits=k_bits, subcol_rows=subcol_rows)
        if i < len(weights) - 1:
            cur = requantize(acc, scale_q=scales_q[i], q_frac=q_frac,
                             k_bits=k_bits, activation="relu").astype(np.int64)
        else:
            ref_out = acc

    m_last = shapes[-1][1]
    _, wacc_last = _column_widths(shapes[-1][0], k_bits)

    pipeline_src = emit_pipeline(
        layers, name=pipeline_name, k_bits=k_bits,
        subcol_rows=subcol_rows, scales_q=scales_q,
        q_frac=q_frac, activation=0,
    )

    with tempfile.TemporaryDirectory(prefix="pipe_emit_") as td:
        work = Path(td)
        (work / "pipeline.sv").write_text(pipeline_src)
        tb_src = TB.format(
            N0=n0, MLAST=m_last, K=k_bits, WACCLAST=wacc_last,
            NAME=pipeline_name,
        )
        (work / "tb.sv").write_text(tb_src)
        (work / "act.hex").write_text(
            "\n".join(f"{int(a):x}" for a in act) + "\n")

        stdout = build_and_run(
            workdir=work,
            sources=[TILE_SV, REQ_SV, BL_SV,
                     work / "pipeline.sv", work / "tb.sv"],
            top="tb_pipeline",
            build_timeout=600.0, run_timeout=600.0,
        )

    measured = np.zeros(m_last, dtype=np.int64)
    cycles = -1
    for line in stdout.splitlines():
        mo = re.match(r"\s*OUT\[(\d+)\]=(-?\d+)", line)
        if mo:
            measured[int(mo.group(1))] = int(mo.group(2))
        mc = re.match(r"\s*CYCLES=(\d+)", line)
        if mc:
            cycles = int(mc.group(1))

    matches = int((measured == ref_out).sum())
    print(f"  3-layer pipeline (N0={n0} -> {shapes[0][1]} -> {shapes[1][1]} -> "
          f"{m_last}, K={k_bits}): {matches}/{m_last} bit-exact, {cycles} cycles")
    if matches != m_last:
        mis = np.where(measured != ref_out)[0]
        for j in mis[:5]:
            print(f"    out[{j}]: expected={ref_out[j]} got={measured[j]}")
        print("[FAIL]")
        return 1
    print("[ok] emit_pipeline 3-layer chain bit-exact vs Python reference")
    return 0


if __name__ == "__main__":
    sys.exit(main())
