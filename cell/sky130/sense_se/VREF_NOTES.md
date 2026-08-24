# VREF sizing for the single-ended CiROM sense

VREF is the "did this bit-line discharge?" threshold for `sa_se`.

## Window (from BL discharge sweep, SS corner, 2 ns strobe)
- Worst-case **discharged** BL (SS, N=128 rows/BL): **0.594 V** at 2 ns (not 0 V —
  the column RC + weak SS drive leave it partway).
- **Quiet** BL (weight=0, stayed precharged): **~1.79 V**.
- **VREF = VDD/2 = 0.9 V** sits between: 306 mV margin to discharged, 890 mV to quiet.
  Both >> the ~10 mV comparator offset.

## Validated
Realistic-level Monte Carlo (SS + mismatch, BL driven to 0.594 V vs 1.79 V, VREF=0.9 V):
- discharged -> HIT=1: 60/60
- quiet (w=0) -> HIT=0: 60/60

So the sense resolves at the **real** array signal levels, not just at the rails.

## Constraints on the rest of the design
- **Strobe timing**: fire after the discharged BL crosses VDD/2 (t_50pct = 1.74 ns @ SS).
  A fixed ~2 ns strobe delay covers SS; FF is faster so also covered.
- **VREF generation (decided -- docs/vref_design.md)**: on-chip res_xhigh_po divider with decap, pad kept as override; the original sizing question:
  ~VDD/2. The 306 mV margin tolerates a loose VREF (±100 mV is fine), so this is not
  margin-critical — a simple divider suffices. Replica-bitline tracks PVT better and is
  the production-preferred option if area allows.

## VREF tolerance (validated, dynamic SS)
Swept VREF 0.70-1.30 V on the dynamic harness at SS (worst discharge). The
sense decodes correctly (w=1->HIT=1, w=0->HIT=0) across the ENTIRE range:
usable window >= 600 mV (between the 0.594 V discharged level and 1.79 V quiet).
=> a plain VDD/2 resistor divider (±~90 mV over process, ratiometric so it
tracks VDD) sits comfortably inside. No replica/trim needed. VREF is low-risk.

## Strobe kickback (corrected measurement)
The concrete resistor-divider test (test_vref_divider.sp, DELIBERATELY high-Z
500k/leg + 50 fF decap as a worst case) shows the comparator's switching
kicks VREF during the strobe by **up to 252 mV** (tt/ss/ff, serial run, all
6 corners still decode correctly). VREF dips from 0.900 V to ~0.65 V transiently
but recovers, and the decision still resolves because the signal margin is large
(discharged BL ~0.13 V vs quiet ~1.8 V at strobe).
NOTE: this corrects commit 5743687, whose message erroneously stated kickback
"<=2.3 mV" (that figure came from a temp file corrupted by concurrent runs; the
real worst-case is 252 mV). 252 mV is tolerable here only because of the wide
margin; a production divider should be lower-impedance (e.g. 10-50k/leg) and/or
carry more VREF decap to cut kickback well below 100 mV. So VREF is still
low-risk, but "no decap needed" would be wrong -- size the decap for the kickback.
