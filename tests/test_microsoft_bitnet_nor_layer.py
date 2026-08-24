"""Bit-exact Verilator validation of one slice of real Microsoft BitNet
weights through the NOR-array architecture (emit_layer_nor + cirom_nor_tile
+ reference_nor).

Closes the chain: HF safetensors -> our unpack -> NOR-array RTL -> Python
NOR reference -> matches PyTorch (validated separately by
test_microsoft_bitnet_pytorch_match.py). All four levels independently
bit-exact -> end-to-end correctness.
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

from ankhdjet.backend.verilog import _column_widths, emit_layer_nor
from ankhdjet.frontend.hf import load_weights
from ankhdjet.frontend.ir import Layer, LayerType, QuantScheme, WeightTensor
from ankhdjet.reference.nor import ternary_matmul_nor
from tests._verilator_runner import build_and_run

TILE_SV = REPO_ROOT / "rtl" / "column" / "cirom_nor_tile.sv"


TB = r"""
`timescale 1ns/1ps
module tb_msbn_nor;
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
    model, arch, _ = load_weights(repo_id, progress=False)
    full = next(L for L in model.layers if L.name == "b0_k").weights["weight"].data

    # NOR tile literal cap: HAS_VIA_POS and HAS_VIA_NEG are each N*M bits.
    # Verilator's literal limit is 65536 -> N*M <= 65536. With N=128, M=64
    # that's exactly 8192 each, comfortable.
    n, m = 128, 64
    W = full[:n, :m].copy()
    nz_pos = int((W == 1).sum()); nz_neg = int((W == -1).sum())
    nz_zero = int((W == 0).sum())
    print(f"  slice W[:{n}, :{m}] = {n*m} positions, "
          f"+1: {nz_pos}, -1: {nz_neg}, 0: {nz_zero}")

    layer = Layer(
        name="msbn_b0_k_nor",
        layer_type=LayerType.LINEAR,
        weights={"weight": WeightTensor(name="weight", data=W,
                                        scheme=QuantScheme.TERNARY)},
        input_dim=n, output_dim=m,
    )

    k_bits = 8
    subcol = 64  # half the input dim, exercises sub-column tiling
    rng = np.random.default_rng(0xCAFE)
    act = rng.integers(0, 1 << k_bits, size=n, dtype=np.int64)
    expected = ternary_matmul_nor(W, act, k_bits=k_bits, subcol_rows=subcol)

    with tempfile.TemporaryDirectory(prefix="msbn_nor_") as td:
        work = Path(td)
        layer_v = work / "layer.sv"
        layer_v.write_text(emit_layer_nor(layer, k_bits=k_bits, subcol_rows=subcol))

        _, wacc = _column_widths(n, k_bits)
        tb_src = TB.format(N=n, M=m, K=k_bits, WACC=wacc, NAME=layer.name)
        (work / "tb.sv").write_text(tb_src)
        (work / "act.hex").write_text("\n".join(f"{int(a):x}" for a in act) + "\n")

        print(f"Building + running Verilator (N={n}, M={m}, K={k_bits}, "
              f"SUBCOL={subcol}) ...", flush=True)
        stdout = build_and_run(
            workdir=work,
            sources=[TILE_SV, layer_v, work / "tb.sv"],
            top="tb_msbn_nor",
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

    matches = int((measured == expected).sum())
    print(f"  Verilator finished in {cycles} cycles; "
          f"{matches}/{m} outputs bit-exact vs ternary_matmul_nor")
    if matches != m:
        mis = np.where(measured != expected)[0]
        for j in mis[:3]:
            print(f"    out[{j}]: expected={expected[j]} got={measured[j]}")
        print("[FAIL]")
        return 1
    print(f"[ok] microsoft/bitnet-b1.58-2B-4T b0_k[:{n},:{m}] bit-exact "
          f"through NOR-array RTL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
