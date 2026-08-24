# Azara: the analog-readout tile

The module is tt_um_azara_cirom, on a TinyTapeout 1x2 analog tile.
It is the comparator-variant vehicle: the same mask-programmed test0
array as the Darga digital tile, read through clocked single-ended
comparators against a shared external reference instead of full-swing
samplers, so the pair is a controlled experiment in readout style
alone. The readout tradeoff itself (energy, coverage, and why the
digital tier is the readout of record) is recorded in
digital_tile_scope.md; this tile's standing justification is as the
offset-measurement instrument: it puts the comparator sense scheme on
silicon with a tunable sense window, so the offset distribution the
statistical signoff models can be measured on the real thing.

## Read architecture

The sense mirrors the signed-off analog chip, scaled to the tile:
full-parallel single-strobe read, no analog mux. A one-hot wordline
asserts, every bitline develops against its precharge, and one shared
STROBE latches every comparator at once, capturing the whole row's
ternary values in a single cycle. The tile senses 16 of the array's
32 columns (32 comparators as two 16-comparator bands: one senses
BLP into pos_hit, one senses BLN into neg_hit); two comparators per
column do not fit the tile width, which is itself one of the
measured coverage facts of the comparison. Per-HIT buffers isolate
the comparator outputs from the routed load.

The controller (cirom_tt_ctrl) runs the signoff read sequence:
precharge (PRE_N low), evaluate for a configured develop time,
strobe, hold, then a purely digital serialization of the 32 captured
hits as four bytes on the output pins, off the analog sense path. A
16-bit serial config register (clocked in on cfg_in while cfg_mode is
high, MSB first) sets strobe_delay, precharge width, and a
precharge-bypass bit, so the silicon can sweep the sense window: the
instrument function.

The AFE (cirom_tt_afe) has three intentional views with one module
name: a blackbox for synthesis, the structural implementation
(array macro + two sense bands + HIT buffers) for hardening, and a
behavioral model for the bench. One top serves both worlds: without
power pins it is the digital-only verification view; with power pins
it wires the tile rails, the reference, and the probe pins for
hardening.

## Reference and probes

There is no on-die reference. ua[0] is a required analog input
(nominally VDD/2) netted directly to all 32 band VREF pins; nothing
reads until it is driven, so bring-up starts by sourcing it (0.9 V).
The on-die divider design that was validated but not integrated (a
sub-pitch macro the power generator cannot bind) is recorded in
vref_design.md. ua[1] and ua[2] are direct analog probes on column
0's BLP and BLN bitlines, for observing develop waveforms against
the strobe timing.

## Floorplan

1x2 analog tile, 161 x 225.76 um, three placed macros. The array
sits at the top, flipped so its 64 wordline pins face the east logic
region (a west wordline column cannot work: 64 wordlines do not fit
the ~30 available met2 tracks). The two bands sit at the bottom,
flipped so their bitline and HIT pins face the routing corridor
between array and bands while VREF and STROBE face the analog-pin
strip on the bottom edge. The controller's standard cells occupy the
top strip with the template's digital pins; analog pins are on the
bottom edge.

Power is met4-only (the tile template forbids met5): vertical met4
straps at the template's minimum width, with a scripted power patch
drawing the exact straps, rail via stacks, and band-belt bars,
because the automatic generator places only followpin rails on this
macro-dominated floorplan and silently relocates straps it cannot
place. Routing obstructions with narrow entry skirts confine the
router to the intended band pin faces, and cosmetic geometry (tip
fills, power labels) is painted into the shipped GDS by the export
script, which gates on a full PDK-deck re-run.

## Pin map and protocol

| Pins | Direction | Function |
|---|---|---|
| ui[5:0] | in | row address |
| ui[6] | in | start |
| ui[7] | in | cfg_mode (serial config load) |
| uio[0] | in | cfg_in |
| uo[7:0] | out | result byte stream (4 bytes: the 32 captured {neg_hit, pos_hit}) |
| uio[2:1] | out | result byte index |
| uio[3] | out | result_valid |
| uio[4] | out | busy |
| uio[5] | out | done |
| ua[0] | analog | VREF, required input (~VDD/2), broadcast to all 32 comparators |
| ua[1], ua[2] | analog | column-0 BLP / BLN bitline probes |
| clk, rst_n, ena | harness | 20 MHz target |

A read: load the config register once (or accept the reset
defaults), drive the row address, pulse start, and collect four
result bytes as result_valid flags them. Raw row reads on this tile
are the same operation the Darga tile reproduces digitally on the
shared 16 columns, which is what makes the two result streams
directly comparable.

## Signoff

The hardened tile (test0 mask program) meets the same gates as the
chips, with the analog-flow dispositions on record:

- Routing is violation-free and the shipped GDS is clean under the
  full KLayout PDK deck (the export regenerates it and gates on a
  full-deck re-run).
- netgen on the shipped GDS: device counts equal (4,850 = 4,850) and
  both bands match uniquely; the residue is fully classified (the
  band's substrate exported as an anonymous port landing on ground
  is designed behavior, since the band carries no taps and the tile
  tap network ties substrate to ground; the rest is parallel-device
  symmetry noise). The classification catalog is lvs_root_cause.md.
- Magic DRC residue is confined to the wide-metal spacing family
  measured as fab-accepted on already-shipped shuttle silicon, with
  the gating classes (latch-up, FEOL, tap spacing) at zero: the same
  calibration discipline as the chip signoff.
- The shuttle's hosted gds, precheck, and docs workflows all pass on
  the submission repository.

The band that ships is the one the per-level LVS discipline exists
for: a predecessor build's band tied all comparator outputs to the
supply through a latch-up tap's local-interconnect bridge, fully
DRC-legal and invisible to tile-level signoff, and its LVS signature
had initially been misclassified as benign label residue. Band
builds publish only at KLayout-clean plus netgen match uniquely, and
every LVS mismatch is classified to a named net before disposition.

## Verification

The self-checking bench drives the full pin protocol and
reconstructs all 64 rows through the serialized bytes, on the
checker and zero-heavy patterns; the behavioral AFE model makes the
controller pattern-agnostic, and the test0 array's mask-level
correctness is proven separately by LVS against the weight-derived
schematic. The comparator's statistical basis (Monte Carlo offset
distribution, extracted-netlist read validation across corners)
lives with the cell records; this tile is the silicon instrument
those models are calibrated against.
