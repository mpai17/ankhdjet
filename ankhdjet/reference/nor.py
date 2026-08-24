"""Bit-exact Python reference for the NOR-array CiROM architecture.

Architecture: mask-programmable NOR ROM (structural family with production
precedent WO2025217724A1 and academic precedent BitROM arXiv 2509.08542)
with 1 NMOS per ternary weight, via-1 drain customisation, column-tiled
sense, and row-sequential one-hot WL readout. The earlier
`ankhdjet.reference.ternary_matmul` modeled an unimplementable parallel-WL
abstraction; this file is the new ground truth.

Per-dot-product execution model:
    for sub in 0..ceil(N/SUBCOL_ROWS)-1:                    # column tiling
        precharge BL+ and BL- to VDD on every sub-column
        for r in 0..SUBCOL_ROWS-1:
            assert WL[sub*SUBCOL_ROWS + r] (one-hot inside sub-column)
            for each output column c:
                pos_hit[c] = (W[sub*SUBCOL_ROWS+r, c] == +1)   # via-1 to BL+
                neg_hit[c] = (W[sub*SUBCOL_ROWS+r, c] == -1)   # via-1 to BL-
                # multiply by activation bit for the current bit-slice k
                acc[c] += (pos_hit - neg_hit) * (act[r] >> k & 1) << k
            re-precharge before next row
The total cycle count per dot product is K * N (one row per cycle, K bit
slices). With column tiling at SUBCOL_ROWS rows per sub-column run in
parallel, the cycle count drops to K * ceil(N / SUBCOL_PARALLEL).
"""

from __future__ import annotations

import numpy as np

DEFAULT_SUBCOL_ROWS = 64  # as-built bitline depth; 256-row is the production-path geometry


def ternary_matmul_nor(
    W: np.ndarray,
    act: np.ndarray,
    k_bits: int = 8,
    subcol_rows: int = DEFAULT_SUBCOL_ROWS,
) -> np.ndarray:
    """Compute `W.T @ act` using NOR-array semantics.

    `W` is (N, M) ternary in {-1, 0, +1}. `act` is (N,) unsigned int with
    values in [0, 2**k_bits). Returns (M,) signed int = sum_i W[i,c] * act[i].

    The result is identical to a plain integer matmul; this reference exists
    to anchor the cycle-accurate behaviour of cirom_nor_subcol/tile.sv.
    """
    if W.ndim != 2:
        raise ValueError(f"W must be 2D (got {W.shape})")
    if set(np.unique(W).tolist()) - {-1, 0, 1}:
        raise ValueError("W must be ternary in {-1, 0, +1}")
    n, m = W.shape
    if act.shape != (n,):
        raise ValueError(f"act shape {act.shape} != (N={n},)")
    if subcol_rows <= 0:
        raise ValueError("subcol_rows must be > 0")

    acc = np.zeros(m, dtype=np.int64)
    for sub_start in range(0, n, subcol_rows):
        sub_end = min(sub_start + subcol_rows, n)
        for r in range(sub_start, sub_end):
            row_w = W[r]
            for k in range(k_bits):
                a_bit = (int(act[r]) >> k) & 1
                if a_bit == 0:
                    continue
                # pos_hit = (row_w == +1) -> add 2^k
                # neg_hit = (row_w == -1) -> sub 2^k
                acc += (row_w.astype(np.int64) << k) * a_bit
    return acc


def cycles_per_dot_product(n: int, k_bits: int = 8,
                            subcol_rows: int = DEFAULT_SUBCOL_ROWS,
                            subcol_parallel: bool = True) -> int:
    """Total cycle count for one dot product.

    With `subcol_parallel=True` (default), all ceil(n/subcol_rows)
    sub-columns are sensed in parallel each cycle, so the wall-clock cycle
    count is k_bits * subcol_rows. Without it (single shared sense amp),
    the cycle count is k_bits * n.
    """
    if subcol_parallel:
        return k_bits * min(n, subcol_rows)
    return k_bits * n


__all__ = ["ternary_matmul_nor", "cycles_per_dot_product",
           "DEFAULT_SUBCOL_ROWS"]
