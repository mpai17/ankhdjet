# VREF design: on-chip divider + decap, pad kept as override

Design record for the analog comparator readout variant only: the
digital sampler readout has no reference, so this subsystem does not
exist in the digital tier.

Decision record for sourcing the sense-amp reference (VREF ≈ VDD/2,
pure DC at idle, ~8.6 pF of comparator gate load; continuous reads draw order-100 uA of rectified current per the energy analysis, which a 91 kOhm divider cannot source, so the on-die reference as designed supports burst reads only). Adopted:
**B-hybrid**: an on-chip resistor divider with local decoupling, and
the existing `vref` pin kept bonded as a high-impedance override and
characterization instrument.

The divider macro is not instantiated in any signed-off assembly:
both the analog chip and the TinyTapeout tile take `vref` as an
external input pin (the sub-pitch macro trips pdngen during
hardening). The B-hybrid scheme applies to a pad-ring assembly that
wants the reference on-die.

## The scheme

- **Divider**: 2 × 180 kΩ `sky130_fd_pr__res_xhigh_po` legs
  (P− poly, 2000 Ω/sq), each built as 9 series 20 kΩ units,
  the legs interdigitated ABAB. ≈4.9 µA / 8.9 µW from 1.8 V;
  Thevenin impedance ≈ 91 kΩ; ~1,500 µm² with guard ring.
- **Decoupling**: ≥150 pF MiM split ~75 pF to each rail (VREF tracks
  both rails at mid-point), ~0.04 mm² stacked CAPM+CAP2M; placed
  beside the sense band; MiM cannot sit over the array's dense met4.
- **Override**: the `vref` pad stays bonded behind an ESD'd analog
  path. A 91 kΩ source is trivially overdriven (≤10 µA contention);
  the production REFIO pattern. Optional mask option: the divider's
  top strap as a single-via jumper, disconnectable on a metal respin.
- **Startup**: τ ≈ 15 µs (91 kΩ × ~160 pF): gate the first strobe
  ≥75 µs after power-good.

## Why

- **Kickback is the binding constraint, not accuracy.** All 64
  StrongARMs strobing synchronously draw ≈1.0 pC out of the VREF
  gates at tail turn-on; the very instant regeneration starts. On
  the bare 8.6 pF net that is a ≈120 mV dip; only *local* charge can
  support the node at t=0 (an external source behind ≥500 Ω of pad
  path recovers ~17 ns later; after the decision). The decap is
  therefore mandatory under every option; once it exists, the divider
  is essentially free for burst operation; for read-dense operation the divider is undersized by >=10x and the hybrid is NOT a strict superset of the
  external-pad option. With 150 pF the dip is ≈6 mV, 5× inside the
  ±50 mV comparator-offset budget.
- **Ratiometric is correct, not a compromise**: bitlines precharge to
  VDD, so the threshold should track VDD (BitROM specifies its
  comparator references as VDD fractions). An absolute reference
  would un-track the precharge rail at the supply corners.
- **Bring-up**: the chip works day-1 with the pad floating; sweeping
  the pad ramp-converts every column's bitline voltage through the 64
  comparators; the single most valuable first-silicon measurement
  (validates the Monte Carlo offset model and the 0.25–1.1 V window).
- `res_xhigh_po` over `res_high_po`: 6.7× less area per ohm and
  measured 260 ppm tempco (vs ±5% for P+ poly); its "e-test TBD"
  status is neutralized by ratiometric use (sheet-ρ shifts move the
  current, not the VDD/2 ratio).

Rejected: R-string DAC (trim dominated by the pad during bring-up and
by a mask-jumper on respins; switch leakage on a 91 kΩ node), replica
column (correlates the reference with the device under test; wrong
for first silicon; right direction for production when windows
shrink), bandgap (absolute where the system is ratiometric;
trim-hungry analog subsystem against a ±400 mV window).

## Validated on the extracted macro

`cell/sky130/sense_se/sim_vref/run_vref.py` drives the C-extracted
array with **all 64 comparators strobing synchronously** against the
divider (±30% sheet-ρ corners) + 150 pF split decap, at tt/ss/ff:

| case | ramp@75µs | kick dip | verdicts |
|---|---|---|---|
| tt 27C 1.8V | 0.900 | 20.2 mV | correct |
| ss 100C 1.62V (R×1.3) | 0.809 | 18.1 mV | correct |
| ff −40C 1.95V (R×0.7) | 0.975 | 22.3 mV | correct |

The measured synchronous kick is ≈3.5 pC (the 1 pC charge estimate
undercounted drain-transition coupling): dips stay under half the
±50 mV offset budget. Scaling note for reduced vehicles: the kick is
proportional to the number of comparators strobing, so a 2–4-SA
TinyTapeout test chip needs only ~10–20 pF for the same ripple.

## Accuracy stack-up

leg mismatch <±10 mV + tempco <±1 mV + kick ripple ≈±22 mV (measured)
≪ comparator offset ±50 mV ≪ window half-width ≈±400 mV.

## Sources

- SkyWater PDK device details (resistor flavors, MiM 2 fF/µm²,
  CAPM/CAP2M stacking): https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html
- xorbit sky130 resistor silicon measurements (sheet ρ, tempco):
  https://github.com/xorbit/sky130-power-blocks/blob/master/primitive-test/resistors.md
- Razavi, "The StrongARM Latch," IEEE SSCM 2015 (parallel-comparator
  kickback at tail turn-on): https://www.seas.ucla.edu/brweb/papers/Journals/BR_Magzine4.pdf
- BitROM (VDD-fraction references): https://arxiv.org/abs/2509.08542
- AD9708 REFIO (override pattern):
  https://www.analog.com/media/en/technical-documentation/data-sheets/AD9708.pdf
- TinyTapeout analog specs (ua pins <500 Ω/<5 pF):
  https://tinytapeout.com/specs/analog/
- IIC-JKU SAR-ADC (on-chip reference precedent, OpenMPW-8):
  https://github.com/iic-jku/SKY130_SAR-ADC1
