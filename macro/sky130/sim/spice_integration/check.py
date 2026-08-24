"""Parse ngspice .measure outputs and diff against the Python reference.

Five failure modes per ISSCC SRAM-SA / CIM regression practice
(Solido HSV docs, Toh/Pun 28nm 2009, ISSCC 2024 Session 34 CIM):

  sense_margin       |OUTP - OUTM| < vmargin at sample edge
  decision_flip      SA decided opposite of reference
  off_cell_leakage   for inactive cells, BLP/BLN dropped > bl_leak_threshold
                     below VDD (true leakage probe via BL voltage)
  measurement_missing  ngspice produced no .measure result for this cell
  ngspice_timeout    handled in runner.run_pattern (subprocess timeout)
  pwl_malformed      handled in runner.run_pattern (deck emitter bug)
"""

from __future__ import annotations

import re
import numpy as np

from reference import expected_per_cell

# Failure-mode tags (string-typed so they survive across modules / pickling).
FAIL_SENSE_MARGIN  = "sense_margin"
FAIL_DECISION_FLIP = "decision_flip"
FAIL_LEAKAGE       = "off_cell_leakage"
FAIL_MEAS_MISSING  = "measurement_missing"
# Runner-level failure modes (defined here so the taxonomy is in one place).
FAIL_TIMEOUT       = "ngspice_timeout"
FAIL_PWL_MALFORMED = "pwl_malformed"


def parse_results(log_text: str, N: int, M: int) -> dict[str, np.ndarray]:
    """Pull per-(row, col) v_outp / v_outm / v_blp / v_bln measurements
    out of an ngspice batch log into 4 (N, M) NumPy arrays."""
    out = {k: np.full((N, M), np.nan) for k in ("outp", "outm", "blp", "bln")}
    pat = re.compile(r"\s*v_(outp|outm|blp|bln)_r(\d+)_c(\d+)\s*=\s*([\d.eE+-]+)")
    for line in log_text.splitlines():
        m = pat.match(line)
        if m:
            out[m.group(1)][int(m.group(2)), int(m.group(3))] = float(m.group(4))
    return out


def check(W: np.ndarray, act_seq: np.ndarray, results: dict[str, np.ndarray],
          vdd: float = 1.8, vmargin: float = 0.1,
          bl_leak_threshold: float = 0.5) -> list[dict]:
    """Per-cell pass/fail with margin and failure taxonomy.

    For each (r, c):
      * Compute the SA decision from |OUTP - OUTM| with vmargin dead-band:
            +1 if OUTP - OUTM > +vmargin
            -1 if OUTM - OUTP > +vmargin
             0 otherwise (metastable / no margin)
      * Compute the reference from W and act_seq.
      * Pass if active (ref=+/-1): decision matches AND margin satisfied.
      * Pass if inactive (ref=0): BLP and BLN both within bl_leak_threshold
        of VDD at strobe-rise (SA's own decision is don't-care; metastable
        resolution is allowed).

    Returns list of failure dicts (empty on full pass). Each dict has at
    least: r, c, kind, msg.
    """
    bl_pos_exp, bl_neg_exp = expected_per_cell(W, act_seq)
    outp = results["outp"]
    outm = results["outm"]
    blp  = results["blp"]
    bln  = results["bln"]

    fails: list[dict] = []
    N, M = W.shape
    for r in range(N):
        for c in range(M):
            vp, vm = outp[r, c], outm[r, c]
            v_blp, v_bln = blp[r, c], bln[r, c]

            if np.isnan(vp) or np.isnan(vm):
                fails.append(dict(
                    r=r, c=c, kind=FAIL_MEAS_MISSING,
                    msg=f"r={r} c={c}: missing measurement (vp={vp}, vm={vm})"
                ))
                continue

            diff = vp - vm
            decision = 1 if diff > vmargin else (-1 if diff < -vmargin else 0)
            ref = +1 if bl_pos_exp[r, c] else (-1 if bl_neg_exp[r, c] else 0)

            if ref == 0:
                # Inactive cell -- the SA's binary decision is metastable
                # so we don't check it. But the BLs MUST stay near VDD at
                # strobe-rise; if either dropped > bl_leak_threshold, an
                # off-cell or charge-share path is leaking BL to ground.
                if not np.isnan(v_blp) and (vdd - v_blp) > bl_leak_threshold:
                    fails.append(dict(
                        r=r, c=c, kind=FAIL_LEAKAGE, decision=decision, ref=ref,
                        outp=vp, outm=vm, blp=v_blp, bln=v_bln,
                        msg=(f"r={r} c={c} W={int(W[r,c])} act={act_seq[r]}: "
                             f"BLP dropped to {v_blp:.3f} V at strobe-rise "
                             f"(VDD={vdd}, threshold={bl_leak_threshold}); "
                             f"off-cell or charge-share leakage on BLP[{c}]")
                    ))
                if not np.isnan(v_bln) and (vdd - v_bln) > bl_leak_threshold:
                    fails.append(dict(
                        r=r, c=c, kind=FAIL_LEAKAGE, decision=decision, ref=ref,
                        outp=vp, outm=vm, blp=v_blp, bln=v_bln,
                        msg=(f"r={r} c={c} W={int(W[r,c])} act={act_seq[r]}: "
                             f"BLN dropped to {v_bln:.3f} V at strobe-rise; "
                             f"off-cell or charge-share leakage on BLN[{c}]")
                    ))
                continue

            if decision == 0:
                fails.append(dict(
                    r=r, c=c, kind=FAIL_SENSE_MARGIN, decision=0, ref=ref,
                    outp=vp, outm=vm,
                    msg=(f"r={r} c={c} W={int(W[r,c])} act={act_seq[r]}: "
                         f"|OUTP-OUTM|={abs(diff):.3f} < vmargin={vmargin:.3f} "
                         f"(OUTP={vp:.3f} OUTM={vm:.3f}); insufficient sense margin")
                ))
            elif decision != ref:
                fails.append(dict(
                    r=r, c=c, kind=FAIL_DECISION_FLIP, decision=decision, ref=ref,
                    outp=vp, outm=vm,
                    msg=(f"r={r} c={c} W={int(W[r,c])} act={act_seq[r]}: "
                         f"expected decision {ref:+d}, got {decision:+d} "
                         f"(OUTP={vp:.3f} OUTM={vm:.3f})")
                ))
    return fails
