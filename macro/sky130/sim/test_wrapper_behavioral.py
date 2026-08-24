"""Behavioral simulation of the macro wrapper through Verilator.

Closes the macro-level testing gap: gen_anchor_abstracts.py emits a wrapper.sv
that declares `cirom_array_NxM` as `(* blackbox *)`, so Yosys never
synthesizes it and the macro test suite never exercises its function.
This test plugs a behavioral fill-in for the blackbox -- a row-
sequential 1T-NOR array with a baked-in random ternary weight matrix
-- and drives the wrapper's `_test_harness` cycle-by-cycle, checking
result_p / result_n against a Python reference.

What's validated end-to-end:
  1. The wrapper's counter increments wl_addr correctly across N rows.
  2. The macro output port shapes (bl_pos[M-1:0], bl_neg[M-1:0]) are
     wired right; per-cycle bits land in result_p / result_n.
  3. The reset semantics zero result_p / result_n synchronously.
  4. result_p[m] = (act_bit AND HAS_VIA_POS[wl_addr, m]) and similarly
     for bl_neg -- the macro's row-sequential NOR semantics.

The test does NOT validate timing (Liberty arcs are unrelated to
behavioral function) or layout (LEF placement is unrelated). Those
are covered by other macro tests + cell-level sims.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

from conftest import MACRO_DIR, REPO

sys.path.insert(0, str(REPO))
from tests._verilator_runner import build_and_run  # noqa: E402


# Behavioral fill-in for the (* blackbox *) cirom_array_64x32 module.
# Per-cycle, row-sequential: at each rising clk edge, given wl_addr it
# emits bl_pos[m] = HAS_VIA_POS[wl_addr][m] & act_bit (and similarly
# for neg). HAS_VIA_POS / HAS_VIA_NEG are baked-in parameters chosen
# by the testbench from the random weight matrix.
BEHAVIORAL_MACRO = r"""
module cirom_array_64x32 #(
    parameter int N = 64,
    parameter int M = 32,
    parameter [N*M-1:0] HAS_VIA_POS = {(N*M){1'b0}},
    parameter [N*M-1:0] HAS_VIA_NEG = {(N*M){1'b0}}
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        act_bit,
    input  wire [5:0]  wl_addr,
    output reg  [M-1:0] bl_pos,
    output reg  [M-1:0] bl_neg
);
    integer m;
    always @(posedge clk) begin
        if (!rst_n) begin
            bl_pos <= '0;
            bl_neg <= '0;
        end else begin
            for (m = 0; m < M; m = m + 1) begin
                bl_pos[m] <= act_bit & HAS_VIA_POS[wl_addr*M + m];
                bl_neg[m] <= act_bit & HAS_VIA_NEG[wl_addr*M + m];
            end
        end
    end
endmodule
"""


def _strip_blackbox_decl(wrapper_sv: str) -> str:
    """Remove the (* blackbox *) cirom_array_64x32 module decl from
    the auto-generated wrapper so Verilator uses our behavioral
    fill-in instead of seeing a duplicate module name."""
    pattern = re.compile(
        r"\(\* blackbox \*\)\s*module cirom_array_64x32.*?endmodule",
        re.DOTALL,
    )
    out, n = pattern.subn("", wrapper_sv)
    assert n == 1, f"failed to find/strip blackbox decl (n={n})"
    return out


def _bitvec_param(mat: np.ndarray) -> str:
    """Pack an (N, M) {0, 1} matrix into an N*M-bit Verilog literal,
    most-significant row last (matches HAS_VIA_*[wl_addr*M + m] indexing)."""
    flat = mat.reshape(-1).astype(np.uint8)
    bits = "".join(str(b) for b in flat[::-1])
    return f"{flat.size}'b{bits}"


def _build_tb(N: int, M: int, has_pos: np.ndarray, has_neg: np.ndarray,
              n_cycles: int, act_bits_seq: np.ndarray) -> str:
    """Synthesize the testbench: clock + reset + drive act_bit, print
    result_p / result_n each cycle so the Python harness can compare."""
    pos_lit = _bitvec_param(has_pos)
    neg_lit = _bitvec_param(has_neg)
    act_inits = "\n        ".join(
        f"act_seq[{i}] = 1'b{int(act_bits_seq[i])};" for i in range(n_cycles)
    )
    return f"""
`timescale 1ns/1ps
module tb;
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg act_bit = 1'b0;
    wire [{M-1}:0] result_p;
    wire [{M-1}:0] result_n;

    // Override the behavioral macro's parameters with the test's
    // random weight matrix. The wrapper's own instance of
    // cirom_array_64x32 picks these up via Verilog elaboration
    // (the module name matches; Verilator binds to the only def).
    defparam u_dut.u_macro.HAS_VIA_POS = {pos_lit};
    defparam u_dut.u_macro.HAS_VIA_NEG = {neg_lit};

    cirom_array_{N}x{M}_test_harness u_dut (
        .clk(clk),
        .rst_n(rst_n),
        .act_bit(act_bit),
        .result_p(result_p),
        .result_n(result_n)
    );

    always #5 clk = ~clk;

    reg act_seq [0:{n_cycles - 1}];

    initial begin
        {act_inits}
        // Synchronous reset for two cycles, then run.
        rst_n = 1'b0; act_bit = 1'b0;
        @(posedge clk); @(posedge clk);
        rst_n = 1'b1;
        for (int i = 0; i < {n_cycles}; i = i + 1) begin
            act_bit = act_seq[i];
            @(posedge clk);
            // result_p / result_n register the previous cycle's
            // bl_pos_w / bl_neg_w (one cycle of latency through the
            // wrapper's output reg). i+1 prints after the i-th drive.
            $display("CYC=%0d ACT=%0b WL=%0d RP=%h RN=%h",
                     i, act_seq[i], i, result_p, result_n);
        end
        $finish;
    end
endmodule
"""


def _expected_results(N: int, M: int, has_pos: np.ndarray, has_neg: np.ndarray,
                      act_seq: np.ndarray) -> list[tuple[int, int]]:
    """One cycle of net latency: at iter i's posedge the macro samples
       the OLD wl_addr (= i, since it advances 0->1, 1->2, ... each iter
       starting from 0 after reset) and the freshly-set act_bit
       (= act_seq[i]); on the SAME edge the wrapper latches the
       previous-cycle bl_pos_w into result_p. So result_p observed
       after iter i corresponds to wl_addr=i-1, act=act_seq[i-1].
       Iter 0 produces zero (still latching reset state)."""
    out = []
    for i in range(len(act_seq)):
        eff_i = i - 1
        if eff_i < 0:
            out.append((0, 0))
            continue
        a = int(act_seq[eff_i])
        wl = eff_i % N   # 6-bit counter wraps
        rp = 0
        rn = 0
        for m in range(M):
            if a and has_pos[wl, m]:
                rp |= 1 << m
            if a and has_neg[wl, m]:
                rn |= 1 << m
        out.append((rp, rn))
    return out


@pytest.mark.parametrize("seed", [0, 1, 7])
def test_wrapper_behavioral_matches_reference(tmp_path, seed: int) -> None:
    rows, cols = 64, 32
    rng = np.random.default_rng(seed)
    # Random ternary weights; encoded as one-hot {has_pos, has_neg}.
    W = rng.choice([-1, 0, 1], size=(rows, cols),
                   p=[0.30, 0.40, 0.30]).astype(np.int8)
    has_pos = (W == 1).astype(np.uint8)
    has_neg = (W == -1).astype(np.uint8)

    # Drive 4 reset cycles then 64 row-sequential read cycles.
    n_cycles = rows + 4
    act_seq = rng.integers(0, 2, size=n_cycles, dtype=np.uint8)

    # Stage the wrapper.sv (with the blackbox decl stripped) and the
    # behavioral macro fill-in into tmp_path.
    wrapper_sv = (MACRO_DIR / "build" / f"cirom_array_{rows}x{cols}_sky130_wrapper.sv").read_text()
    if not wrapper_sv:
        pytest.skip("wrapper.sv missing -- run gen_anchor_abstracts.py first")
    wrapper_clean = _strip_blackbox_decl(wrapper_sv)

    (tmp_path / "wrapper.sv").write_text(wrapper_clean)
    (tmp_path / "behavioral_macro.sv").write_text(BEHAVIORAL_MACRO)
    (tmp_path / "tb.sv").write_text(_build_tb(rows, cols, has_pos, has_neg,
                                              n_cycles, act_seq))

    stdout = build_and_run(
        workdir=tmp_path,
        sources=[
            tmp_path / "behavioral_macro.sv",
            tmp_path / "wrapper.sv",
            tmp_path / "tb.sv",
        ],
        top="tb",
        build_timeout=180,
        run_timeout=60,
    )

    # Parse one CYC= line per cycle.
    cyc_re = re.compile(r"CYC=(\d+)\s+ACT=(\d+)\s+WL=(\d+)\s+RP=([0-9a-f]+)\s+RN=([0-9a-f]+)")
    observed = []
    for line in stdout.splitlines():
        m = cyc_re.search(line)
        if m:
            observed.append((int(m.group(4), 16), int(m.group(5), 16)))
    assert len(observed) == n_cycles, (
        f"got {len(observed)} cycles, expected {n_cycles}:\n{stdout[-1500:]}"
    )

    expected = _expected_results(rows, cols, has_pos, has_neg, act_seq)
    mismatches = []
    for i, ((rp_o, rn_o), (rp_e, rn_e)) in enumerate(zip(observed, expected)):
        if (rp_o, rn_o) != (rp_e, rn_e):
            mismatches.append(
                f"  cycle {i}: act={act_seq[i]} wl_eff={i-2}  "
                f"rp obs={rp_o:08x} exp={rp_e:08x}  "
                f"rn obs={rn_o:08x} exp={rn_e:08x}"
            )
    assert not mismatches, "behavioral mismatch:\n" + "\n".join(mismatches[:8])
