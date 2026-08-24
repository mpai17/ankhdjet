"""Bit-exact verification of the between_layer RTL (scale + ReLU + K-bit
unsigned saturating quantize) against the Python fixed-point reference."""

from __future__ import annotations

import math
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.reference.between import requantize
from tests._verilator_runner import build_and_run

RTL   = REPO_ROOT / "rtl"
REQ_SV = RTL / "between_layer" / "requantize.sv"
BL_SV  = RTL / "between_layer" / "between_layer.sv"

TB = r"""
`timescale 1ns/1ps
module tb_bl;
    localparam int M       = {M};
    localparam int WACC    = {WACC};
    localparam int SCALE_W = {SCALE_W};
    localparam int Q_FRAC  = {Q_FRAC};
    localparam int K       = {K};

    logic [WACC*M-1:0] acc_flat;
    logic [K*M-1:0]    out_flat;

    between_layer #(
        .M(M), .WACC(WACC), .SCALE_W(SCALE_W), .Q_FRAC(Q_FRAC), .K(K),
        .SCALE_Q({SCALE_Q}), .ACTIVATION({ACTIVATION})
    ) dut (.acc_flat(acc_flat), .out_flat(out_flat));

    int fd, j, v;
    logic signed [WACC-1:0] tmp_acc;
    initial begin
        fd = $fopen("{ACC_FILE}", "r");
        acc_flat = '0;
        for (j = 0; j < M; j++) begin
            v = $fscanf(fd, "%d\n", tmp_acc);
            acc_flat[WACC*(j+1)-1 -: WACC] = tmp_acc;
        end
        $fclose(fd);
        #1;
        for (j = 0; j < M; j++) begin
            $display("OUT[%0d]=%0d", j, out_flat[K*(j+1)-1 -: K]);
        end
        $finish;
    end
endmodule
"""


def _width_widths(max_acc_mag: int, k_bits: int) -> int:
    return max(8, math.ceil(math.log2(max_acc_mag + 1)) + 1)


def _run_between_layer(
    workdir: Path, acc: np.ndarray, scale_q: int, q_frac: int,
    k_bits: int, scale_w: int, activation: int,
) -> np.ndarray:
    m = acc.size
    wacc = _width_widths(int(np.max(np.abs(acc))) + 1, k_bits)

    acc_file = workdir / "acc.txt"
    acc_file.write_text("\n".join(str(int(a)) for a in acc) + "\n")

    tb_src = TB.format(
        M=m, WACC=wacc, SCALE_W=scale_w, Q_FRAC=q_frac, K=k_bits,
        SCALE_Q=f"{scale_w}'d{scale_q}", ACTIVATION=activation,
        ACC_FILE="acc.txt",
    )
    (workdir / "tb.sv").write_text(tb_src)

    stdout = build_and_run(
        workdir=workdir,
        sources=[REQ_SV, BL_SV, workdir / "tb.sv"],
        top="tb_bl",
    )

    out = np.zeros(m, dtype=np.int64)
    for line in stdout.splitlines():
        m_ = re.match(r"\s*OUT\[(\d+)\]=(-?\d+)", line)
        if m_:
            idx = int(m_.group(1))
            out[idx] = int(m_.group(2))
    return out


def main() -> None:
    rng = np.random.default_rng(42)

    cases = [
        (8,   1000,   1 << 8,   8, 16, 8, 0),
        (16,  5000,   (3 << 8), 8, 16, 8, 0),
        (32,  100000, 64,       8, 16, 8, 0),
        (64,  500,    1 << 8,   8, 16, 4, 0),
        (32,  2000,   1 << 7,   8, 16, 8, 0),
        (16,  200,    1 << 9,   8, 16, 8, 0),
    ]

    all_pass = True
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for idx, (m, acc_range, sq, q_frac, scale_w, k_bits, activation) in enumerate(cases):
            acc = rng.integers(-acc_range, acc_range, size=m).astype(np.int64)
            expected = requantize(
                acc, scale_q=sq, q_frac=q_frac, k_bits=k_bits,
                activation="relu" if activation == 0 else "identity",
            )
            measured = _run_between_layer(
                work, acc, sq, q_frac, k_bits, scale_w, activation,
            )
            ok = np.array_equal(expected, measured)
            print(
                f"[{'ok' if ok else 'FAIL'}] case {idx}  M={m:3d} k={k_bits}  "
                f"scale_q={sq} q_frac={q_frac}  "
                f"match={m - int(np.sum(expected != measured))}/{m}"
            )
            if not ok:
                mis = np.where(expected != measured)[0]
                for i in mis[:5]:
                    print(f"    ch{i}: acc={acc[i]}  exp={expected[i]}  got={measured[i]}")
                all_pass = False

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
