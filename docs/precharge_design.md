# Bitline precharge design: clocked PMOS, no keeper

Decision record for the CiROM bitline pull-up scheme (the precharge
rework that also adds the missing BL− pull-ups and fixes the floating
gates). Backed by production/academic precedent and by SKY130
silicon-model measurements (ngspice decks under
`cell/sky130/precharge/research_sims/`). The precharge cell and its
control contract are shared by both readout tiers; the margin
analyses below that reference VREF or the StrongARM were measured in
the analog variant's context, and the digital sampler's
threshold-crossing margins are covered in the digital readout record.

**Implemented and signed off** (KLayout DRC 0, netgen LVS 0, functional
regression 396/396): W=1.0 cell with a real gate-top contact, stacked
pull-up rows (A→BL−, B→BL+) with merged per-column gate caps on a met2
PRE_N backbone, a PRE_N met3 riser pin, and the read FSM driving PRE_N
high only during evaluate/strobe. The sense outputs are captured into
chip registers on the clock edge ending the strobe state; the
StrongARM's reset PMOS drags HIT high once STROBE falls, so unregistered
outputs read all-ones by the time valid pulses.

## The scheme

One `pfet_01v8` **W/L = 1.0/0.15 per bitline** (both BL+ and BL−),
source/body to VDD, drain to the bitline, gate driven by an active-low
**PRECHG_N**. No half-latch keeper. No equalizer.

Control contract (per read cycle):

- `PRECHG_N` is **low in the precharge state and in every idle/reset
  state** (bitlines park high, matching OpenRAM's deselected-bank
  behavior), **high only during evaluate and strobe**.
- WL rises after `PRECHG_N` deasserts (the decoder/driver delay gives
  natural break-before-make) and **stays high through the strobe**, so
  the discharged bitline is actively driven at the sample instant and
  only the high bitline floats.
- The strobe may fire any time ≥1.1 ns after WL rises; once the sense
  latch has regenerated, `PRECHG_N` and WL can fall in either order.
- Driver: ~64-gate load (~100 fF) per rail pair; a 2-stage buffer.

Every timing constraint clears by ≥4× at ss/100C/1.62V: precharge needs
≥2 ns of the ~8 ns state, discharge needs ≤1.1 ns.

## Why clocked (and not a static pseudo-NMOS pull-up)

The decisive measurement: a pull-up weak enough for tolerable static
power **cannot re-charge the bitline within the 25 ns cycle at the slow
corner**: 21.7–43.3 ns to 90% VDD (L=1/L=2 pull-ups, ss/100C) against
a 25 ns budget. Sizing it strong enough to recover puts the read path
back at ~1 mW static and ~150 mV VOL. The clocked PMOS at full gate
drive recovers the same bitline in 1.6 ns worst-case. Ratioed margin
and static power were survivable; recovery time is the unfixable
failure, which is why no cited production design uses static pull-ups
beyond textbook toy arrays.

Precedent, all clocked: BitROM (ASP-DAC 2026) precharge+equalize with
comparator sensing; YOLoC (DAC 2022) precharged dynamic bitlines;
production mask-ROM patents US6252813B1 (clocked PMOS + optional static
trickle + grounded unselected bitlines) and US6002858A (self-timed ROM
compiler gating bitline precharge); OpenRAM's ROM compiler
(`rom_precharge_cell.py`: PMOS with the gate as a control input, driven
by `CS AND clk`).

## Why no keeper

Worst measured leakage on a dynamically-held bitline (64 off cells,
ff/100C) is 1.06 nA → 0.88 mV droop over a full 25 ns cycle on the
minimum 30 fF; 0.1% of the ~0.8 V margin to VREF, and the off
precharge PMOS trickles 22 nA back *into* the line. Keepers are for
sub-130 nm wide-OR domino leakage regimes (Alvandpour, JSSC 2002);
SKY130's 1.8 V FETs are not in it. Neither OpenRAM's ROM nor the cited
chips use one.

## Hazards and the mitigations adopted

- **Precharge/evaluate overlap (crowbar):** prevented by the FSM
  ordering above; optionally add OpenRAM's structural fix; a footer
  NMOS row between the bitline chain and ground gated by the precharge
  net ("acts to prevent shorting bl to ground when precharging"): if
  crowbar-safety-by-construction is preferred over by-timing.
- **Floating-high bitline disturbance (the real dynamic hazard):**
  ternary coding makes a falling aggressor next to a floating-high
  victim the common case. Estimated coupling + StrongARM kickback
  (Razavi, SSCM 2015) ≈ 0.3 V against ≥0.7 V upward margin: passes, but
  guard it in layout; the grounded source/read lines between BL+ and
  BL− act as shields, and holding WL through the strobe keeps the low
  line driven. Re-check the margin from extracted parasitics.
- **Metal-option fallback:** a parallel always-on trickle PMOS
  (0.42/8, ~5 mV VOL shift) per US6252813B1's dynamic+static pair;
  not included by default; reserve the footprint only if extraction
  shows >20% inter-bitline coupling.
- **Charge sharing:** absent; a 1T NOR cell has no internal stack
  node, and there is no column mux.

## Measured numbers (ngspice, sky130A models, cell = nfet_01v8 0.42/0.17)

| Quantity | tt/27C/1.8V | ss/100C/1.62V | ff/100C |
|---|---|---|---|
| Cell Ion (Vds=0.9) | 164 µA | 84 µA | 178 µA |
| Discharge 65 fF to 0.9 V / 0.3 V | 0.34 / 0.61 ns | 0.54 / 1.07 ns | – |
| 64-cell off-leakage per BL | 0.12 nA | – | 1.06 nA |
| Droop on 30 fF over 25 ns | 0.1 mV | – | 0.88 mV |
| Clocked precharge to 95% VDD (1.0/0.15) | 1.07 ns | 1.63 ns | – |
| Pseudo-NMOS recovery to 90% VDD (L=1 / L=2) | 12.2 / 24.5 ns | 21.7 / 43.3 ns | 8.5 / 17.2 ns |

## Extracted-netlist validation

The C-extracted macro (Magic `extract do capacitance/coupling`, the
full 2048-cell + 64-pull-up netlist with every wire and coupling cap)
was driven by the validated sa_se schematic pair through two
FSM-timed reads (w=+1 then w=−1) at tt/27C/1.8V and ss/100C/1.62V,
with the ground return lumped as a swept series resistance. Runner:
`cell/sky130/macro/sim_a2/run_a2.py` (timestamped logs under its
`build/`).

Extracted values: C_BL = 27–37 fF (wire-only; junctions add ~5 fF);
the design-point 30–65 fF estimate was conservative. Dominant
coupling: BLP↔BLN within a column = 7.27 fF (~25% of C_BL); the
grounded source lines hold every other pairing below 0.8 fF.

All cases pass; every read decision correct at both corners and all
ground-return values:

| Quantity | tt/27C/1.8V | ss/100C/1.62V |
|---|---|---|
| Discharged BL at strobe | 0.00 V | 0.00 V |
| Floating victim, pre-strobe (after the 0.31 V coupling dip) | 1.49 V | 1.35 V |
| Victim margin above VREF=VDD/2 | 0.59 V | 0.54 V |
| Recovery after PRE_N falls (sampled +4.8 ns) | full rail | full rail |
| Ground-return sensitivity (0 → 10 kΩ; analytic bound ~1.15 kΩ) | none | none |

One characteristic to carry forward: the sa_se input pair (W/L = 8/2,
sized for offset) presents ~140 fF of gate capacitance against the
~34 fF bitline, so once the latch fires, kickback pulls the floating
victim to 0.75–0.82 V. The decision is taken before the kickback
develops (all verdicts correct), and the next precharge erases the
disturbance; but any scheme that samples a bitline *after*
the strobe edge, or shares a bitline between sense amps, must
re-examine this.

## Signal-integrity signoff (STA clean)

The flow signs off with **zero max-slew / max-cap / max-fanout
violations alongside DRC 0 and LVS 0**. Three issues were found and fixed at the
root; all three would have been silicon bugs:

- **The flow digitized VREF.** The default SDC models every input with
  a logic driving cell, so the resizer "repaired" the overloaded
  reference by inserting a `clkbuf_16`: the comparators would have
  received a rail, not 0.9 V. Fix: a custom SDC excludes `vref` from
  driving-cell and input-delay modeling, and `RSZ_DONT_TOUCH_RX` keeps
  every optimizer off the net. The final netlist has zero gates on it.
- **Placeholder liberty caps starved the buffering.** The band lib
  claimed 4 fF per STROBE pin against ~130 fF of real tail+reset gate
  (BL/VREF similar at ~135 fF), so every band-bound tree was
  under-buffered. The lib is now generated by
  `cell/sky130/sense_se/author_band_lib.py` with device-derived caps,
  NLDM arcs on HIT (an arc-less output is invisible to
  `repair_design`), and no slew checks on the analog pins.
- **StrongARM output-load imbalance flips decisions.** The latch races
  its two output nodes; with HIT routed and HITB internal (~0 fF), the
  measured cliff on the C-extracted macro (ss/100C, 1 ns strobe
  edges): correct at 100 fF imbalance, the floating-victim side flips
  at 150 fF, everything flips at 200 fF (balanced loads fine to
  250+). Unbuffered band-to-core routes reached 105 fF; 1.4× margin.
  Fix: `max_capacitance : 60 fF` on HIT pins plus a kept `buf_4` per
  HIT net in RTL, manually placed directly under its band pin
  (`MANUAL_GLOBAL_PLACEMENTS`): the pin now sees a short hop and the
  buffer input restores balance.

Flow lessons recorded for reuse: OpenSTA enforces the *minimum* of
design-wide and liberty limits, so blanket SDC constraints condemn
analog pins no matter what the lib says (drop the design-wide DRV
constraints; keep per-pin liberty limits). `RUN_POST_GRT_DESIGN_REPAIR`
is off by default, and GRT wire estimates ran ~3× under extraction for
the long band-to-core climbs; repair margins of 40–60% bridge the
gap. One m4.2 came from a STROBE wire end landing 5 nm off the
off-grid VGND PDN stripe edge: different nets, so the ECO cure is a
0.30 µm notch in the (1.6 µm) stripe over the conflict window; never
a bridge (a first-attempt bridge shorted strobe to ground; LVS caught
it).

## Sources

- BitROM: https://arxiv.org/abs/2509.08542
- YOLoC: https://arxiv.org/abs/2206.00379
- OpenRAM ROM compiler: https://github.com/VLSIDA/OpenRAM/blob/stable/compiler/modules/rom_precharge_cell.py
  (also rom_precharge_array.py, rom_control_logic.py, rom_base_array.py)
- US6252813B1: https://patents.google.com/patent/US6252813B1/en
- US6002858A: https://patents.google.com/patent/US6002858A/en
- Harris, CMOS VLSI Design lect. 14/19: https://pages.hmc.edu/harris/class/e158/04/lect14.pdf
- Alvandpour et al., JSSC 37(5) 2002 (keeper regime)
- Razavi, "The StrongARM Latch," IEEE SSCM 2015: https://www.seas.ucla.edu/brweb/papers/Journals/BR_Magzine4.pdf
