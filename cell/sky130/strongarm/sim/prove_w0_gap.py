"""Quantify the MAC corruption from the weight=0 sense gap.

The implemented per-column differential StrongARM resolves sign(BLP-BLN)
with complementary OUTP/OUTM, so it can only emit (pos,neg) = (1,0) or
(0,1) -- never (0,0). For a weight-0 cell (drain->VGND, both BLs stay
precharged, ~0 differential) it therefore resolves RANDOMLY -> a spurious
+/-1. The golden model (ankhdjet.reference.nor) treats w=0 as 0.

This script computes, for a representative BitNet ternary layer, the
true MAC (W in {-1,0,+1}) vs the "hardware" MAC where every w=0 read
becomes a random +/-1, and reports the error vs signal. Pure numpy;
matches reference_nor semantics: y[c] = sum_i W[i,c] * act[i].
"""

from __future__ import annotations

import numpy as np


def ternary_layer(n, m, zero_frac, rng):
    """Random BitNet-style ternary weights with a given zero fraction.
    Non-zero entries are +/-1 with equal probability."""
    u = rng.random((n, m))
    W = np.zeros((n, m), dtype=np.int8)
    nz = u >= zero_frac
    signs = rng.integers(0, 2, size=(n, m)) * 2 - 1   # +/-1
    W[nz] = signs[nz]
    return W


def corrupt_w0(W, rng):
    """Hardware read: w=0 -> random +/-1 (the differential-SA gap)."""
    Wc = W.copy()
    zmask = (W == 0)
    Wc[zmask] = rng.integers(0, 2, size=int(zmask.sum())) * 2 - 1
    return Wc


def run(n=2048, m=512, k_bits=8, seeds=8):
    print(f"\nBitNet layer N={n} (in) x M={m} (out), {k_bits}-bit activations")
    print(f"{'zero%':>6} {'RMS_err/RMS_signal':>20} {'corr(true,hw)':>16} "
          f"{'eff.bits_lost':>14} {'outputs >10% off':>18}")
    print("-" * 78)
    for zf in (0.30, 0.50, 0.70):
        ratios, corrs, lost, badfrac = [], [], [], []
        for s in range(seeds):
            rng = np.random.default_rng(1000 + s)
            W = ternary_layer(n, m, zf, rng)
            act = rng.integers(0, 2 ** k_bits, size=n).astype(np.int64)
            y_true = act @ W.astype(np.int64)          # (M,)
            y_hw = act @ corrupt_w0(W, rng).astype(np.int64)
            err = y_hw - y_true
            rms_err = np.sqrt(np.mean(err ** 2))
            rms_sig = np.sqrt(np.mean(y_true ** 2))
            ratios.append(rms_err / rms_sig)
            corrs.append(np.corrcoef(y_true, y_hw)[0, 1])
            # effective bits lost ~ log2(signal/error)
            lost.append(np.log2(max(rms_sig / rms_err, 1.0)))
            badfrac.append(np.mean(np.abs(err) > 0.10 * (np.abs(y_true) + 1e-9)))
        print(f"{zf*100:>5.0f}% {np.mean(ratios):>19.2f}x {np.mean(corrs):>16.3f} "
              f"{np.mean(lost):>14.1f} {np.mean(badfrac)*100:>16.0f}%")
    print("\n(RMS_err/RMS_signal >= ~1.0 means the corruption is as large as the"
          "\n signal -> the MAC is effectively destroyed. corr->0 = output"
          "\n uncorrelated with truth.)")


if __name__ == "__main__":
    run()
