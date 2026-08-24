"""Bit-serial ternary MAC reference model.

Pure-math oracle: models the ternary dot product with no WL ordering or
array structure, which makes it the independent bridge to PyTorch (the
HF unpack + ternary_matmul are validated against torch F.linear). The
hardware readout-order ground truth is reference_nor.ternary_matmul_nor.

Semantics:
    Weights: ternary {-1, 0, +1}, shape (N,)
    Activations: unsigned K-bit integer, shape (N,), values in [0, 2^K - 1]
    Dot product: sum_i (W[i] * A[i]) in regular integer arithmetic.

Bit-serial execution:
    For cycle k = 0 .. K-1 (LSB first):
        a_bit[i, k] = (A[i] >> k) & 1
        plus_count = sum_i  [W[i] == +1 AND a_bit[i, k] == 1]
        minus_count = sum_i [W[i] == -1 AND a_bit[i, k] == 1]
        partial[k] = plus_count - minus_count
    Accumulator: acc = sum_k (partial[k] << k)

This is bit-exact: the sum is an integer, no rounding anywhere.
"""

from __future__ import annotations

import numpy as np


def ternary_dot(
    weights: np.ndarray,
    activations: np.ndarray,
    k_bits: int = 8,
) -> int:
    """Bit-exact bit-serial ternary dot product.

    Args:
        weights: shape (N,) integer array with values in {-1, 0, +1}.
        activations: shape (N,) integer array with values in [0, 2**k_bits - 1].
        k_bits: activation bit width.

    Returns:
        Signed integer dot product.
    """
    w = np.asarray(weights, dtype=np.int64)
    a = np.asarray(activations, dtype=np.int64)

    if w.shape != a.shape:
        raise ValueError(f"weights {w.shape} vs activations {a.shape}")
    if w.ndim != 1:
        raise ValueError("reference model is per-column (1-D)")
    if np.any(a < 0) or np.any(a >= (1 << k_bits)):
        raise ValueError("activations must fit in k_bits unsigned")

    # Ground truth: just do integer matmul; bit-serial decomposition must match.
    return int(np.sum(w * a))


def ternary_dot_bit_serial(
    weights: np.ndarray,
    activations: np.ndarray,
    k_bits: int = 8,
) -> tuple[int, list[int]]:
    """Same dot product, but computed by the bit-serial algorithm the
    hardware will use. Returns (dot_product, per_cycle_partial_sums).

    The per-cycle partial sums are useful for RTL comparison - you can
    dump them from a testbench and compare cycle-by-cycle.
    """
    w = np.asarray(weights, dtype=np.int64)
    a = np.asarray(activations, dtype=np.int64)

    plus_mask = (w == 1)
    minus_mask = (w == -1)

    acc = 0
    partials: list[int] = []
    for k in range(k_bits):
        a_bit = (a >> k) & 1
        plus_count = int(np.sum(plus_mask & (a_bit == 1)))
        minus_count = int(np.sum(minus_mask & (a_bit == 1)))
        partial = plus_count - minus_count
        partials.append(partial)
        acc += partial << k
    return acc, partials


def ternary_matmul(
    weights: np.ndarray,
    activations: np.ndarray,
    k_bits: int = 8,
) -> np.ndarray:
    """Matmul reference: weights (N, M) @ activations (N,) -> (M,) output.

    Each column independently runs ternary_dot.
    """
    W = np.asarray(weights, dtype=np.int64)
    a = np.asarray(activations, dtype=np.int64)
    N, M = W.shape
    out = np.zeros(M, dtype=np.int64)
    for j in range(M):
        out[j] = ternary_dot(W[:, j], a, k_bits=k_bits)
    return out


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    for trial in range(5):
        N = rng.integers(4, 1025)
        K = int(rng.choice([4, 8, 12]))
        w = rng.choice([-1, 0, 1], size=N, p=[0.35, 0.3, 0.35])
        a = rng.integers(0, 1 << K, size=N)

        direct = ternary_dot(w, a, k_bits=K)
        serial, _ = ternary_dot_bit_serial(w, a, k_bits=K)
        assert direct == serial, f"mismatch: {direct} vs {serial}"
        print(f"N={N:4d} K={K:2d}  dot={direct}")
