"""Bit-exact reference for the between-layer pipeline.

Datapath (per channel j):
    product = acc[j] * scale          (signed integer)
    shifted = product >>> Q_FRAC      (arithmetic shift right)
    if relu: shifted = max(shifted, 0)
    out[j] = clip(shifted, 0, 2^K - 1) as unsigned K-bit

`scale` is stored as an unsigned Q(Q_INT.Q_FRAC) fixed-point integer. A
scale of 1.0 is 1 << Q_FRAC. A scale of 0.25 is 1 << (Q_FRAC - 2), etc.

All arithmetic uses Python big-ints, which matches Verilog's wide signed
arithmetic exactly.
"""

from __future__ import annotations

import numpy as np


def requantize(
    acc: np.ndarray,
    scale_q: int,
    q_frac: int = 8,
    k_bits: int = 8,
    activation: str = "relu",
) -> np.ndarray:
    """Apply scale, activation, and saturating quantize to K-bit unsigned.

    Args:
        acc: array of signed ints (the column accumulator outputs).
        scale_q: unsigned Q(Q_INT.Q_FRAC) fixed-point scale. scale_q = 1 << q_frac is 1.0.
        q_frac: fractional bits in the Q format.
        k_bits: output activation width (unsigned).
        activation: "relu" (clamp to 0) or "identity" (pass signed, then clamp to unsigned).
    Returns:
        array of K-bit unsigned ints.
    """
    acc = np.asarray(acc, dtype=object)  # big-int safe
    scale_q = int(scale_q)
    product = acc * scale_q
    # Python's // on negative ints is floor division, matching arithmetic shift right
    shifted = np.array([int(x) >> q_frac for x in product.flatten()], dtype=object).reshape(acc.shape)

    if activation == "relu":
        shifted = np.where(shifted < 0, 0, shifted)
    elif activation == "identity":
        pass
    else:
        raise ValueError(f"unknown activation: {activation}")

    max_val = (1 << k_bits) - 1
    clipped = np.clip(shifted.astype(np.int64), 0, max_val)
    return clipped.astype(np.int64)


if __name__ == "__main__":
    # Quick self-test
    acc = np.array([1000, -500, 200, 0, 70000], dtype=np.int64)
    out = requantize(acc, scale_q=256, q_frac=8, k_bits=8, activation="relu")
    print("acc   :", acc)
    print("out   :", out)
    # acc * 256 >> 8 = acc; ReLU then clip to [0, 255]
    #   1000 -> 255 (saturated)
    #   -500 -> 0 (ReLU)
    #   200 -> 200
    #   0 -> 0
    #   70000 -> 255 (saturated)
    expected = np.array([255, 0, 200, 0, 255], dtype=np.int64)
    assert np.array_equal(out, expected), f"mismatch: {out} vs {expected}"
    print("ok")
