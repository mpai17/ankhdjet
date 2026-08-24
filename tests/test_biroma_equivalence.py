"""BiROMA encoding produces identical dot products to standard NOR-array
encoding — this is a regression check on the BiROMA python reference.

If they ever diverge, the BiROMA encoding has acquired a bug or the
NOR-array reference has changed in a way the BiROMA path doesn't
mirror. Both should always agree because BiROMA only changes the
physical cell-sharing scheme, not the math.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.package


import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ankhdjet.reference.biroma import (biroma_cell_count,
                                        ternary_matmul_biroma)
from ankhdjet.reference.nor import ternary_matmul_nor


def main() -> int:
    rng = np.random.default_rng(0xA2A4A)
    cases = [
        (16, 16, 8, 16),    # tiny even
        (15, 16, 8, 16),    # tiny odd (exercises BiROMA padding)
        (128, 64, 8, 64),   # the standard validation slice
        (256, 32, 4, 128),  # different K, subcol
    ]
    n_pass = 0
    for n, m, k_bits, subcol in cases:
        W = rng.choice([-1, 0, 1], size=(n, m), p=[0.4, 0.2, 0.4]).astype(np.int8)
        act = rng.integers(0, 2**k_bits, size=n, dtype=np.int64)

        nor_out = ternary_matmul_nor(W, act, k_bits=k_bits, subcol_rows=subcol)
        biroma_out = ternary_matmul_biroma(W, act, k_bits=k_bits, subcol_rows=subcol)

        match = np.array_equal(nor_out, biroma_out)
        cells_nor = n * m
        cells_bir = biroma_cell_count(n, m)
        density_ratio = cells_nor / cells_bir
        print(f"  N={n:4d} M={m:4d} K={k_bits} SUBCOL={subcol}  "
              f"match={match}  cells: nor={cells_nor} biroma={cells_bir} "
              f"({density_ratio:.2f}x)")
        if match:
            n_pass += 1

    if n_pass == len(cases):
        print(f"[ok] BiROMA bit-exact vs NOR on all {n_pass} cases; "
              f"BiROMA cell count ~half of NOR")
        return 0
    print(f"[FAIL] {n_pass}/{len(cases)} cases match")
    return 1


if __name__ == "__main__":
    sys.exit(main())
