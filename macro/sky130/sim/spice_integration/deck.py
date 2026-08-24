"""SPICE deck emitter for the cirom_array integration test.

`emit_array_deck(W, act_seq, corner)` returns a complete ngspice
deck as a string: solver options, stimulus PWLs, precharge PMOSes,
mask-programmed bitcell array, per-column StrongARM SAs, BL load,
.measure directives, .tran. No file I/O.
"""

from __future__ import annotations

import re
import numpy as np

from paths import SA_SCHEMATIC, SKY130_LIB


# Cycle timing (ns). Each row-read cycle is 20 ns:
#   pre   precharge window  [0.05, 2.0]
#   wl    word-line pulse   [2.05, 9.5]
#   strobe SA sense window  [3.5, 9.0]
#   reset SA reset window   [9.0, 20.0]   (11 ns of strobe-low for SA reset)
CYCLE_NS     = 20.0
PRE_LO_START = 0.05
PRE_LO_END   = 2.0
WL_START     = 2.05
WL_END       = 9.5
STROBE_START = 3.5
STROBE_END   = 9.0


def _ns(t: float) -> str:
    """Quantize time to ps grid so PWL points stay strictly increasing
    despite Python float repr (`2.05 + 0.05 = 2.099999999...`)."""
    return f"{round(t, 3):.3f}n"


def emit_array_deck(W: np.ndarray, act_seq: np.ndarray, corner: str = "tt",
                    vdd: float = 1.8, subcol_rows: int = 64) -> str:
    """Emit the full SPICE deck for an N x M array reading row-by-row.

    Args:
        W:           (N, M) int8 in {-1, 0, +1}, the mask-programmed weights.
        act_seq:     (N,) uint8 in {0, 1}, the per-row activation bit.
        corner:      sky130 corner name ("tt", "ss", "ff").
        vdd:         supply voltage (1.8 V nominal).
        subcol_rows: explicit BL capacitance models the SUBCOL_ROWS-row
                     sub-column load. C_DRAIN = 0.6 fF, C_WIRE = 0.262 fF
                     per cell (per cell/sky130/bitcell_v4/sim/test_harness.sp).
                     Without this, small-N tests have tiny BL cap and the
                     active cell discharges BL fully -- which the W=0.42
                     precharge PMOS can't recover in 2 ns.
    """
    N, M = W.shape
    assert len(act_seq) == N, f"need one act_bit per row, got {len(act_seq)} for N={N}"

    pwl_end_ns = N * CYCLE_NS + 5

    lines: list[str] = []
    _header(lines, corner, vdd)
    _wl_pwls(lines, N, act_seq, pwl_end_ns)
    _pre_n_pwl(lines, N, pwl_end_ns)
    _strobe_pwl(lines, N, pwl_end_ns)
    _precharge_pmos(lines, M)
    _bl_load(lines, M, subcol_rows, N)
    _bitcell_array(lines, W)
    _strongarm_sas(lines, M)
    _measurements(lines, N, M)
    _tail(lines, N)
    return "\n".join(lines)


# ---------- deck sections ----------

def _header(lines: list[str], corner: str, vdd: float) -> None:
    lines.extend([
        f'.lib "{SKY130_LIB}" {corner}',
        f"* cirom_array SPICE integration deck",
        f"* corner={corner} vdd={vdd:.2f} V",
        "",
        # Per OpenRAM characterizer + KLU paper (Lannutti DATE 2012):
        # KLU is required at >10k devices; noinit suppresses .OP printing;
        # optran warm-start = pseudo-transient OP for fast digital
        # startup; reltol 1e-3 is the digital-flow standard. Do NOT
        # enable savecurrents -- ngspice manual explicitly warns it
        # explodes memory on large circuits.
        ".option klu",
        ".option noinit",
        ".option reltol=1e-3",
        ".option method=trap",
        ".option optran=0 0 0 100p 2n 0",
        "",
        f".param VDD_V = {vdd}",
        "Vvdd vdd 0 'VDD_V'",
        "Vgnd vgnd 0 0",
        "",
    ])


def _wl_pwls(lines: list[str], N: int, act_seq: np.ndarray, pwl_end_ns: float) -> None:
    """Per-row WL pulse: HIGH during the matching cycle if act_seq[r]=1."""
    for r in range(N):
        cyc_t0  = r * CYCLE_NS
        wl_hi   = "VDD_V" if act_seq[r] else "0"
        t_pre   = cyc_t0 + WL_START
        t_pre_r = cyc_t0 + WL_START + 0.05
        t_post  = cyc_t0 + WL_END
        t_post_r= cyc_t0 + WL_END + 0.05
        lines.append(
            f"Vwl_{r} wl_{r} 0 PWL("
            f"0 0  {_ns(t_pre)} 0  {_ns(t_pre_r)} {wl_hi}  "
            f"{_ns(t_post)} {wl_hi}  {_ns(t_post_r)} 0  {_ns(pwl_end_ns)} 0)"
        )
    lines.append("")


def _pre_n_pwl(lines: list[str], N: int, pwl_end_ns: float) -> None:
    """Single shared PRE_n: low during precharge windows of every cycle."""
    pts = ["0 'VDD_V'"]
    for r in range(N):
        cyc_t0 = r * CYCLE_NS
        pts += [
            f"{cyc_t0 + PRE_LO_START:.3f}n 'VDD_V'",
            f"{cyc_t0 + PRE_LO_START + 0.05:.3f}n 0",
            f"{cyc_t0 + PRE_LO_END:.3f}n 0",
            f"{cyc_t0 + PRE_LO_END + 0.05:.3f}n 'VDD_V'",
        ]
    pts.append(f"{pwl_end_ns:.3f}n 'VDD_V'")
    lines.append("Vpre_n pre_n 0 PWL(" + " ".join(pts) + ")")
    lines.append("")


def _strobe_pwl(lines: list[str], N: int, pwl_end_ns: float) -> None:
    """Single shared STROBE: pulses HIGH during the sense window each cycle."""
    pts = ["0 0"]
    for r in range(N):
        cyc_t0 = r * CYCLE_NS
        pts += [
            f"{cyc_t0 + STROBE_START:.3f}n 0",
            f"{cyc_t0 + STROBE_START + 0.05:.3f}n 'VDD_V'",
            f"{cyc_t0 + STROBE_END:.3f}n 'VDD_V'",
            f"{cyc_t0 + STROBE_END + 0.05:.3f}n 0",
        ]
    pts.append(f"{pwl_end_ns:.3f}n 0")
    lines.append("Vstrobe strobe 0 PWL(" + " ".join(pts) + ")")
    lines.append("")


def _precharge_pmos(lines: list[str], M: int) -> None:
    """One precharge PMOS per BL pole per column."""
    for c in range(M):
        lines.append(
            f"Xpre_p_{c} blp_{c} pre_n vdd vdd sky130_fd_pr__pfet_01v8 "
            "w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42"
        )
        lines.append(
            f"Xpre_n_{c} bln_{c} pre_n vdd vdd sky130_fd_pr__pfet_01v8 "
            "w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42"
        )
    lines.append("")


def _bl_load(lines: list[str], M: int, subcol_rows: int, N: int) -> None:
    """Lumped BL capacitance for sibling cells not emitted as devices."""
    sibling_count = max(0, subcol_rows - N)
    if sibling_count == 0:
        return
    c_total_fF = sibling_count * (0.6 + 0.262)
    for c in range(M):
        lines.append(f"Cbl_p_{c} blp_{c} 0 {c_total_fF:.3f}fF")
        lines.append(f"Cbl_n_{c} bln_{c} 0 {c_total_fF:.3f}fF")
    lines.append("")


def _bitcell_array(lines: list[str], W: np.ndarray) -> None:
    """One bitcell NMOS per (row, col), drain mask-programmed by W."""
    N, M = W.shape
    for r in range(N):
        for c in range(M):
            w = int(W[r, c])
            if   w >  0: drain = f"blp_{c}"
            elif w <  0: drain = f"bln_{c}"
            else:        drain = "vgnd"
            lines.append(
                f"Xcell_{r}_{c} {drain} wl_{r} vgnd vgnd sky130_fd_pr__nfet_01v8 "
                "w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42"
            )
    lines.append("")


def _strongarm_sas(lines: list[str], M: int) -> None:
    """Per-column StrongARM SA, .subckt pulled from the project schematic."""
    sa_text = SA_SCHEMATIC.read_text()
    m = re.search(r"\.subckt\s+strongarm.*?\.ends.*", sa_text, re.DOTALL)
    assert m, "could not find .subckt strongarm block"
    lines.append(m.group(0))
    lines.append("")
    for c in range(M):
        lines.append(
            f"Xsa_{c} blp_{c} bln_{c} outp_{c} outm_{c} strobe vdd vgnd strongarm"
        )
    lines.append("")


def _measurements(lines: list[str], N: int, M: int) -> None:
    """Four .measure per (row, col): BLP/BLN at strobe-rise (true leakage
    detector) + OUTP/OUTM near strobe-fall (SA decision)."""
    for r in range(N):
        t_strobe_rise = r * CYCLE_NS + STROBE_START + 0.05
        t_meas        = r * CYCLE_NS + STROBE_END - 0.1
        for c in range(M):
            lines.append(f".measure tran v_blp_r{r}_c{c} FIND v(blp_{c}) AT={t_strobe_rise:.3f}n")
            lines.append(f".measure tran v_bln_r{r}_c{c} FIND v(bln_{c}) AT={t_strobe_rise:.3f}n")
            lines.append(f".measure tran v_outp_r{r}_c{c} FIND v(outp_{c}) AT={t_meas:.3f}n")
            lines.append(f".measure tran v_outm_r{r}_c{c} FIND v(outm_{c}) AT={t_meas:.3f}n")


def _tail(lines: list[str], N: int) -> None:
    total_ns = N * CYCLE_NS + 1.0
    lines.append("")
    lines.append(f".tran 10p {total_ns:.1f}n")
    lines.append(".end")
