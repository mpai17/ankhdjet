# Bitcell specification

This document specifies the physical bitcell the array architecture
consumes; the implemented, silicon-verified `bitcell_v4` as built and
signed off in both SKY130 chips (`cirom_chip_digital` and
`cirom_chip_analog`; the cell and its mask programming are identical
in both readout tiers), and the BiROMA variant kept as
the closed investigation's generator (a smaller-node technique, NO-GO
at SKY130 per the BiROMA design record).

## Purpose

A single bitcell stores **one ternary weight** in a mask-programmable
1T footprint, supporting:

- Column-shared BL+ / BL− with one-hot WL per cycle
- Mask programming on the via/metal jog per cell: drain routed to BL+
  (weight +1), BL− (weight −1), or left unconnected (weight 0)
- Clocked-precharge read (bitlines park at VDD between evaluates; see
  the precharge design doc)
- SS-corner BL discharge within the evaluate state at 64 rows per
  bitline
- A custom array pitch placed as a hard macro (no standard-cell row
  sharing)

## Electrical schematic

One NMOS per cell:

```
                  WL_r ──┐
                         │
     BL+ / BL− / (none) ─D
                         │
                         M
                         │
                         S──── source/read line (li) ──→ pwell/VGND
```

- Gate = the row wordline (met2-accessible WL strap).
- Drain = mask-routed per weight: a met1/via jog to the column's BL+
  met4 strip (+1), to the BL− met3 strip (−1), or no connection (0:
  the drain stub floats; the schematic models it as a dangling net,
  which flat extraction matches).
- Source = the per-column li strap network, tied through tap-row li
  buses and substrate taps so sources, pwell, and VGND extract as one
  net.

Adjacent-cell jog abutment is a known silent-short class: a +1 jog and
the neighbor column's −1 jog must never abut at the cell boundary
(caught by flat-extraction LVS, fixed in the mask-programming
generator).

## Implemented sizing

- Channel **W = 0.42 µm, L = 0.17 µm** (`sky130_fd_pr__nfet_01v8`).
  L = 0.17 (one step above minimum) came out of the gate-contact
  rework; the discharge target moved from a 1.5 ns budget at 128 rows
  to **64 rows per bitline**, where the measured discharge is
  0.54/1.07 ns to 0.9/0.3 V at ss/100C/1.62 V; well inside the 8 ns
  evaluate state of the 25 ns cycle.
- **Cell pitch 1.70 × 1.30 µm.** The 1.70 column pitch carries the
  BL− met3 strip, BL+ met4 strip, the li source strap, and the mask
  jog lanes with DRC margin; 1.30 row pitch closes poly and li rules
  against the gate-top contact stack.
- Body taps: a separate tap cell shared every 8 rows
  (`ANKHDJET_TAP_EVERY=8`), plus tap-row li buses that carry the source
  network to substrate.

## Mask programming

Per cell instance, one choice from {BL+, BL−, none}, written by the
mask-programming generator from a `{+,-,0}` weights file (one
character per cell). The entire model maps to the jog/via finishing
step; one mask change per fabricated variant. Zero-weight cells are
mask-absent: no via, drain stub floating, verified by flat-extraction
LVS against dangling-net schematics (1,035 zero cells in the committed
test matrix).

## Verification chain (all green on the implemented cell)

1. Magic DRC clean at cell, subcolumn, array, and macro levels;
   KLayout `sky130A_mr.drc` (full options) clean at macro and chip.
2. Flat-extraction netgen against the generated transistor-level
   schematic: "Circuits match uniquely" at the macro (2,048 cells +
   the clocked precharge pair per column), for both the checker and
   the arbitrary sparse test matrix.
3. ngspice transients on the C-extracted macro: discharge, coupling
   (BLP↔BLN 7.27 fF measured), precharge recovery, and read decisions
   across corners and ground-return sweeps.
4. The chip-level flow consumes the macro as GDS + authored LEF +
   Liberty; full signoff DRC 0 / LVS 0 / STA clean.

## BiROMA variant (smaller-node option; NO-GO at SKY130)

A BiROMA variant (two ternary weights per 1T footprint via E/O-side
reads, per BitROM) exists as a generator with DRC/LVS/replay
regression coverage. The investigation concluded NO-GO at SKY130:
the discharge-domain fork breaks even on sense-line pitch, and the
voltage-domain fork's driven-rail droop refunds the 2× (full record
in the BiROMA design doc). The verified SKY130 chips use the
one-weight cell above; BiROMA re-enters only at nodes where sense
margin and BEOL pitch refund the density, through the same per-level
LVS discipline that validated v4.
