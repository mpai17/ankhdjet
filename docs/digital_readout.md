# Digital readout: full-swing bitline sampling

Design record for the readout of record: clocked precharge, then a
full-swing digital sample of each bitline into standard-cell capture
registers, with all accumulation in synthesized RTL. No comparators,
no reference subsystem, no replica timing, no mismatch statistics.
This is the readout the compiler emits at every node; the analog
comparator variant (a characterization-gated density/energy option
within the 180-28 nm window) is recorded in the array architecture
and Darga records.

## The design

The read follows the macro contract's four states. During strobe,
each bitline lands on an input buffer plus capture flop; the
captured value is the inverted bitline (a discharged line means the
addressed cell drives that polarity):

- `sa_out_pos[c]` captures `~BLP_c` (weight +1 discharged BL+)
- `sa_out_neg[c]` captures `~BLN_c` (weight −1 discharged BL−)
- neither set means weight 0 (no discharge path)

Everything above the captured bit is ordinary synchronous logic:
per-column add/sub/skip accumulation over the row sweep, activation
bit-slice weighting, the shared scale multiplier, and saturating
requantize, all synthesized from the PDK's standard cells. The
signed-off implementations of this wrapper are `cirom_chip_digital`
(chip scale) and the Darga tile's `cirom_dig_ctrl` (tile scale, with
the full ternary MAC on die).

## Why ternary makes this readout sufficient

The array encodes a weight in WHICH line discharges, never in how
much: reading it is two independent binary presence detections per
column, and a binary decision at full logic swing needs no analog
discrimination. Multi-level cell encodings are what force
comparators and references into ROM readout; the ternary
one-of-two-lines encoding removes that requirement, which is what
makes a comparator-free readout correct rather than merely cheaper.

## The margin argument

The sampler decides after the bitline has crossed the input
threshold of a standard gate, so the decision margin is the full
logic swing rather than a small-signal differential:

- No offset distribution: nothing to Monte Carlo, no statistical
  signoff, no per-instance mismatch surface.
- No reference: no VREF pin, divider, decap, or kickback budget
  (the entire VREF design record applies only to the analog
  variant).
- No replica timing: the strobe is FSM-timed against the measured
  worst-case discharge (SKY130: SS-corner 64-row discharge 1.07 ns
  to 0.3 V inside an 8 ns evaluate state; the bitcell spec carries
  the characterization).

The price is time: the sampler waits for a full swing where a
comparator decides on a few hundred mV. At the signed-off SKY130
geometry that wait is absorbed entirely by the evaluate state, so
the tiers close at the same cycle time and the certainty is free at
this node; the analog variant's projected advantage opens only at
deeper bitlines strobed at partial swing, and its win conditions are
recorded with the Darga tradeoff analysis.

## Measured basis

From the synthesis-anchored and signed-off artifacts (the results
record is canonical for full tables):

- **Readout area**: 32 bitline samplers (capture flop + input
  buffer) synthesize to 1,081 µm² against 8,656 µm² for the two
  sense bands they functionally replace: an ~8× readout-area
  reduction at equal column count.
- **Read energy**: bitline energy is identical across tiers (hit
  lines fully discharge either way as built), while comparators are
  ~81% of the analog tile's 19.2 pJ read, so total read energy is
  ~4-5× lower on the digital tile as built.
- **Coverage**: the digital tile senses all 32 columns where the
  analog tile fits comparators for 16; samplers fit where
  comparator pairs do not.
- **Chip signoff**: `cirom_chip_digital` closes LVS 0, max
  slew/cap/fanout 0, setup +16.3 ns / hold +0.11 ns at the 25 ns
  clock, with KLayout reporting 2 items of the engine-artifact
  class against 17 for the signed-off analog chip under the same
  engine, and the functional bench reconstructing 64/64 rows on
  both mask programs.
- **Portability**: the same emission synthesizes against ASAP7
  libraries at a 205.9× area ratio for identical RTL, the anchor
  the advanced-node estimates stand on; below 28 nm the digital
  tier is the only readout.

## Boundary characteristics to respect

- The capture flop's input buffer sets the sampling threshold;
  characterize the worst-case discharge against the slowest input
  threshold corner, not the typical one.
- The discharged line is driven through the strobe (WL held), so
  only the floating-high polarity is exposed to coupling; the
  grounded source straps between BL+ and BL− shield the pair (the
  precharge record carries the measured coupling and victim
  margins).
- Sampling is per-bitline with no mux in the signed-off geometry;
  a muxed digital readout at deeper arrays re-times the strobe but
  does not change the contract above the captured bit.
