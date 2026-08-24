"""Coverage patterns for the SPICE integration test.

Three tiers per OpenRAM functional.py + ISSCC CIM 2024 standard:
  tier 1 -- structured: catches systematic failures (decoder collisions,
            BL-droop, leakage-summing).
  tier 2 -- random with logged seed: statistical confidence.
  tier 3 -- single-cell-hot exhaustive: every (r, c) verified.

Each function returns `(W, act_seq)` where W is (N, M) int8 in {-1, 0, +1}
and act_seq is (N,) uint8 in {0, 1}.
"""

from __future__ import annotations

import numpy as np

# ---------- tier 1: structured ----------

def pattern_all_pos(N: int, M: int) -> tuple[np.ndarray, np.ndarray]:
    """Worst-case BL+ load: every cell drives BL+."""
    return np.ones((N, M), dtype=np.int8), np.ones(N, dtype=np.uint8)


def pattern_all_neg(N: int, M: int) -> tuple[np.ndarray, np.ndarray]:
    """Worst-case BL- load: every cell drives BL-."""
    return -np.ones((N, M), dtype=np.int8), np.ones(N, dtype=np.uint8)


def pattern_all_zero(N: int, M: int) -> tuple[np.ndarray, np.ndarray]:
    """No cell discharges. Verifies BL leakage budget (off-cell paths
    should not corrupt the SA decision)."""
    return np.zeros((N, M), dtype=np.int8), np.ones(N, dtype=np.uint8)


def pattern_checkerboard(N: int, M: int) -> tuple[np.ndarray, np.ndarray]:
    """Alternating ±1. Mixed-polarity stress, catches charge-share or
    BL-coupling between adjacent columns."""
    W = np.zeros((N, M), dtype=np.int8)
    for r in range(N):
        for c in range(M):
            W[r, c] = 1 if (r + c) % 2 == 0 else -1
    return W, np.ones(N, dtype=np.uint8)


def pattern_stripe_row(N: int, M: int, hot_row: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Single hot row -- weight=+1 across all cols, all other rows zero.
    Catches row-decoder collision / WL leakage."""
    W = np.zeros((N, M), dtype=np.int8)
    W[hot_row, :] = 1
    return W, np.ones(N, dtype=np.uint8)


def pattern_stripe_col(N: int, M: int, hot_col: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Single hot column. Tests per-BL leakage with N-1 zeros and one one."""
    W = np.zeros((N, M), dtype=np.int8)
    W[:, hot_col] = 1
    return W, np.ones(N, dtype=np.uint8)


# ---------- tier 2: random ----------

def pattern_random(N: int, M: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Random ternary weights with a logged seed for reproducibility."""
    rng = np.random.default_rng(seed)
    W = rng.choice([-1, 0, 1], size=(N, M), p=[0.30, 0.40, 0.30]).astype(np.int8)
    act = rng.integers(0, 2, size=N, dtype=np.uint8)
    return W, act


# ---------- tier 3: single-cell-hot exhaustive ----------

def patterns_single_cell_hot(N: int, M: int) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """One pattern per column with weight=+1 at every row of that column,
    all other cols zero. Run across all M patterns -- exhaustively
    verifies every (r, c) cell over M*N total cycles."""
    out = []
    for hot_col in range(M):
        W = np.zeros((N, M), dtype=np.int8)
        W[:, hot_col] = 1
        out.append((f"col_hot_{hot_col}", W, np.ones(N, dtype=np.uint8)))
    return out


# ---------- coverage selection (used by runner.main) ----------

def select_patterns(N: int, M: int, coverage: str, n_random: int = 3
                    ) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """Build the (name, W, act_seq) list for a coverage spec string.

    coverage in {smoke, tier1, random, tier1+random, tier1+random+exhaustive}
    """
    patterns: list[tuple[str, np.ndarray, np.ndarray]] = []
    if coverage == "smoke":
        patterns.append(("random_seed0", *pattern_random(N, M, 0)))
    if coverage in ("tier1", "tier1+random", "tier1+random+exhaustive"):
        patterns += [
            ("all_pos",    *pattern_all_pos(N, M)),
            ("all_neg",    *pattern_all_neg(N, M)),
            ("all_zero",   *pattern_all_zero(N, M)),
            ("checker",    *pattern_checkerboard(N, M)),
            ("stripe_row", *pattern_stripe_row(N, M, hot_row=N // 2)),
            ("stripe_col", *pattern_stripe_col(N, M, hot_col=M // 2)),
        ]
    if coverage in ("random", "tier1+random", "tier1+random+exhaustive"):
        for s in range(n_random):
            patterns.append((f"random_seed{s}", *pattern_random(N, M, s)))
    if coverage == "tier1+random+exhaustive":
        patterns.extend(patterns_single_cell_hot(N, M))
    return patterns
