"""Bit-exact Python reference for BiROMA-encoded NOR-array CiROM.

BiROMA (BitROM Sec III-B1, arXiv 2509.08542) packs TWO ternary weights
into one 1T cell by using the cell's source/drain bidirectionally:
  - Reading from the "even" side (E) on cycle k: cell discharges BL+/BL-
    according to W[2*r] (the even-row weight).
  - Reading from the "odd" side (O) on cycle k+1: same cell discharges
    according to W[2*r+1] (the odd-row weight).

The physical cell stays one transistor; the array stores N rows of
weights using N/2 cells. Stored-weight density doubles vs the standard
1-weight-per-1T-cell pattern.

This module is the COMPILER-side reference. It implements the
externally-observable BiROMA behavior (per-dot-product output) and
tracks the halved cell count. The physical encoding was investigated
at SKY130 and closed as NO-GO there (both implementation forks:
discharge-domain is break-even, voltage-domain refunds the 2x through
driven-rail droop); its viability window is 65-28 nm, where this
reference anchors the smaller-node estimates. The estimator tools gate
the encoding to that window.

Bit-exact equivalence: BiROMA produces the same dot-product result as
the standard NOR-array reference for any (W, act) — the encoding only
changes how rows are scheduled and physically stored, not the math.
"""

from __future__ import annotations

import numpy as np

from ankhdjet.reference.nor import DEFAULT_SUBCOL_ROWS, ternary_matmul_nor


def ternary_matmul_biroma(
    W: np.ndarray,
    act: np.ndarray,
    k_bits: int = 8,
    subcol_rows: int = DEFAULT_SUBCOL_ROWS,
) -> np.ndarray:
    """Compute `W.T @ act` using BiROMA-encoded NOR-array semantics.

    Same input/output as `ternary_matmul_nor`. Functionally identical;
    the difference is in the underlying physical encoding (each pair
    of adjacent rows shares one transistor cell, halving cell count).

    Padding: if N is odd, the bottom row is paired with a w=0 dummy.
    """
    n, m = W.shape
    if n % 2 == 1:
        # Pad to an even row count by appending a row of zeros — the
        # last cell stores a real weight on its E-side and a w=0 weight
        # on its O-side (drain via to VGND_TIE).
        Wp = np.vstack([W, np.zeros((1, m), dtype=W.dtype)])
        actp = np.concatenate([act, np.zeros(1, dtype=act.dtype)])
    else:
        Wp = W
        actp = act
    return ternary_matmul_nor(Wp, actp, k_bits=k_bits, subcol_rows=subcol_rows)


def biroma_cell_count(n_rows: int, m_cols: int) -> int:
    """How many physical 1T cells a BiROMA-encoded N x M weight matrix uses.

    Even N: exactly N*M/2.
    Odd N: ceil(N/2) * M (the last cell pair has one w=0 padding slot).
    """
    pairs_per_col = (n_rows + 1) // 2
    return pairs_per_col * m_cols


def biroma_cell_um2_per_weight(bare_cell_um2: float) -> float:
    """Per-stored-weight area when BiROMA halves cell count.

    Body-tap amortization is < 1% so we ignore it for this report;
    matches the bitcell_v3 + body_tap empirical data point.
    """
    return bare_cell_um2 / 2.0
