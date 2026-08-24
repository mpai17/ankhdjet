"""Python reference for the cirom_array sense path.

`expected_per_cell(W, act_seq)` returns the bit-level truth: for each
(row, col), what the SA *should* decide given the encoded weight and
activation. Derived from `ankhdjet.reference.nor` semantics: a 1T NOR
cell with drain on BLP/BLN/VGND per W[r,c]={+1,-1,0} pulls its BL low
iff WL[r] is asserted (act_seq[r]==1).
"""

from __future__ import annotations

import numpy as np


def expected_per_cell(W: np.ndarray, act_seq: np.ndarray
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Return (bl_pos_exp, bl_neg_exp), each (N, M) bool:
       bl_pos_exp[r, c] = (act_seq[r] AND W[r, c] == +1)
       bl_neg_exp[r, c] = (act_seq[r] AND W[r, c] == -1)

    The SA reads BLP/BLN and resolves OUTP/OUTM with opposite polarity:
       BLP discharge (bl_pos_exp) -> OUTP > OUTM (decision = +1)
       BLN discharge (bl_neg_exp) -> OUTM > OUTP (decision = -1)
       neither (W=0 or act=0)     -> BLs equal,  metastable (decision = 0)
    """
    bl_pos = (W ==  1) & (act_seq[:, None].astype(bool))
    bl_neg = (W == -1) & (act_seq[:, None].astype(bool))
    return bl_pos, bl_neg
