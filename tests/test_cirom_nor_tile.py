"""Bit-exact Verilator validation of cirom_nor_tile.

The new NOR-array tile (column-tiled row-sequential read, one-hot WL,
1 NMOS per ternary weight) replaces the legacy parallel-WL cirom_tile
which assumed per-cell digital outputs that 1T cells cannot produce.
Compares against ankhdjet.reference.nor.ternary_matmul_nor on random
ternary weights at multiple shapes.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.reference.nor import ternary_matmul_nor
from tests._verilator_runner import build_and_run

TILE_SV = REPO_ROOT / "rtl" / "column" / "cirom_nor_tile.sv"


TB = r"""
`timescale 1ns/1ps
module tb_nor;
    localparam int N = {N};
    localparam int M = {M};
    localparam int K = {K};
    localparam int SUBCOL = {SUBCOL};
    localparam int WACC = {WACC};

    logic clk, rst_n, start, valid;
    logic [K*N-1:0]              act_flat;
    logic signed [WACC*M-1:0]    acc_flat;
    logic [K-1:0]                act_byte [0:N-1];

    cirom_nor_tile #(
        .N(N), .M(M), .K(K), .SUBCOL_ROWS(SUBCOL), .WACC(WACC),
        .HAS_VIA_POS({POS_LIT}),
        .HAS_VIA_NEG({NEG_LIT})
    ) dut (
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
        @(negedge clk);
        start = 1;
        @(negedge clk);
        start = 0;
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


def _bits_literal(bits: np.ndarray) -> str:
    n = bits.size
    s = "".join("1" if int(bits[n - 1 - i]) else "0" for i in range(n))
    return f"{n}'b{s}"


def _write_act_hex(activations: np.ndarray, path: Path) -> None:
    path.write_text("\n".join(f"{int(a):x}" for a in activations) + "\n")


def run_case(workdir: Path, n: int, m: int, k_bits: int,
              subcol: int, w_seed: int = 0xA55) -> tuple[np.ndarray, int]:
    rng = np.random.default_rng(w_seed)
    W = rng.choice([-1, 0, 1], size=(n, m), p=[0.30, 0.40, 0.30]).astype(np.int64)
    act = rng.integers(0, 1 << k_bits, size=n, dtype=np.int64)

    expected = ternary_matmul_nor(W, act, k_bits=k_bits, subcol_rows=subcol)

    pos_bits = np.zeros(n * m, dtype=np.int64)
    neg_bits = np.zeros(n * m, dtype=np.int64)
    for r in range(n):
        for c in range(m):
            idx = r * m + c
            if W[r, c] == 1:  pos_bits[idx] = 1
            if W[r, c] == -1: neg_bits[idx] = 1

    wacc = max(8, int(np.ceil(np.log2((n * (1 << k_bits)) + 1))) + 1)
    tb_src = TB.format(
        N=n, M=m, K=k_bits, SUBCOL=subcol, WACC=wacc,
        POS_LIT=_bits_literal(pos_bits),
        NEG_LIT=_bits_literal(neg_bits),
    )
    (workdir / "tb.sv").write_text(tb_src)
    _write_act_hex(act, workdir / "act.hex")

    stdout = build_and_run(
        workdir=workdir, sources=[TILE_SV, workdir / "tb.sv"],
        top="tb_nor", build_timeout=300.0, run_timeout=300.0,
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
    if "TIMEOUT" in stdout:
        raise RuntimeError(f"timeout:\n{stdout[-1500:]}")
    return measured, cycles, expected


def main() -> int:
    cases = [
        # (n, m, k_bits, subcol)
        (16, 4, 4, 16),
        (32, 8, 8, 16),
        (64, 8, 8, 32),
        (128, 16, 8, 64),
        (256, 8, 8, 128),
    ]
    all_ok = True
    with tempfile.TemporaryDirectory(prefix="nor_") as td:
        work = Path(td)
        for idx, (n, m, k, sub) in enumerate(cases):
            measured, cycles, expected = run_case(work, n, m, k, sub)
            ok = np.array_equal(measured, expected)
            print(f"[{'ok' if ok else 'FAIL'}] case {idx}  N={n} M={m} K={k} "
                  f"SUBCOL={sub}  cycles={cycles}  match={int((measured==expected).sum())}/{m}")
            if not ok:
                mis = np.where(measured != expected)[0]
                for j in mis[:3]:
                    print(f"    out[{j}]: exp={expected[j]} got={measured[j]}")
                all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
