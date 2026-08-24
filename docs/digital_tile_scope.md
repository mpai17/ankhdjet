# Darga: the digital-readout tile

Named Darga (Aramaic: step, degree, tier); the module is
tt_um_darga_cirom. The compiler's fully digital emission (the readout
of record) hardened as a shuttle tile: storage is the mask-programmed
64x32 array macro (the mask-only invariant is the point), readout is
a clocked digital sample of each bitline (precharge, discharge,
strobe into a flop): no comparators, no VREF, no analog pins, no
mismatch signoff. The freed area carries the full ternary MAC on
die, so this is the first vehicle that computes dot products on
silicon. The Azara analog tile (tt_um_azara_cirom) carries the same
test0 mask program with the comparator-variant readout, making the
pair a controlled experiment in readout style alone.

## Readout tradeoff (why the analog variant exists)

Both tiers are the same machine: a mask-programmed array computing
digitally (accumulation is bit-serial add/sub/skip in both). They
differ only in readout style. The analog tile reads with clocked
comparators against a shared reference, at the price of an offset
distribution that needs statistical signoff and a reference subsystem;
clocked sensing of precharged bitlines is standard ROM practice, but
this tile's specific scheme (per-bitline, single-ended, uncancelled,
no mux, shared VDD/2 pin) is not, and was flagged as the questionable
element by the project's own pre-port review. Full-swing sampling
(this tile) is a certainty play: no mismatch surface, no reference, no
analog signoff, at the price of waiting for the bitline to cross the
gate threshold. As built, the two are NOT at parity on read energy:
bitline energy is at parity (hit lines fully discharge either way,
and the wordline holds through the strobe, so no partial-depth saving
occurs on the fabricated design), while total read energy is ~4-5x
higher on the analog tile because the comparators are ~81% of its
19.2 pJ read (signoff-grade energy table). The analog advantage is
PROJECTED to open at production geometry (256-row bitlines strobed at
partial depth), contingent on three undesigned mechanisms: evaluate
terminated at the strobe, replica-timed strobing, and the unfinished
mux-resistance campaign; no artifact demonstrates it. It also reverses
in idle-dominated duty cycles until the reference is
duty-cycled. Ternary made the digital tier viable at every node;
analog is a candidate energy optimization for read-dense, energy-bound
workloads whose win condition is untested. The sensing cost gap is
also a coverage gap on this vehicle pair: the analog tile senses 16
of the array's 32 columns because two comparators per column do not
fit, while the digital tile senses all 32 because samplers do. The analog tier was
originally selected on a necessity premise that ternary invalidated;
tile62's standing justification is as the offset-measurement
instrument that calibrates the statistical methodology.

## Area (synthesis-anchored)

Synthesized with yosys against sky130_fd_sc_hd tt_025C_1v80 (chip
area, pre-P&R; representative RTL, not the final blocks):

| Block | Variant | Area (um2) |
|---|---|---|
| Full digital region (cirom_dig_ctrl: FSM, 64x4b activation store, 16x12b MAC, sense flops, streaming) | direct signed add of the 4-bit activation | 27,476 (measured) |
| MAC bank alone, 16 cols x 16-bit acc | byte-parallel add/sub | 18,689 (measured) |
| MAC bank alone, 16 cols x 16-bit acc | bit-serial inc/dec | 17,129 (measured) |
| Digital readout alone (32 bitline samplers: capture flop + input buffer) | functional replacement for both sense bands (8,656 um2) | 1,081 (measured) |
| Full digital region, streamed activations, 16 sensed columns | STORE_ACTS=0, N_ACC=4 | 7,652 (measured) |
| Full digital region, hardened configuration (all 32 columns sensed, streamed activations) | STORE_ACTS=0, N_ACC=4, N_COLS=32 | 9,311 (measured) |

The flop population dominates: 192 accumulator bits plus the 256-bit
activation store plus capture and pipeline registers. The bit-serial
encoding saves only ~8% at this width, so the RTL uses the simpler
direct signed add (one row sweep per multiply).

## Floorplan verdict

1x2 tile (161 x 225.76 um = 36,367 um2). Array macro keepout ~6,300
um2 (54.6 x 97.9 plus halo); placeable standard-cell area after edge
and PDN margins ~28,000 um2.

| MAC configuration | Std-cell total (um2) | Effective util | Verdict |
|---|---|---|---|
| 16 parallel x 12-bit | 27,476 (measured) | ~98% | will not route |
| 8 accumulators, 2:1 column mux (as-written RTL) | 20,834 (measured) | ~74% | baseline: tight but plausible in a clean std-cell region with no analog obstructions |
| 8-acc mux, activation store removed (host paces rows) | ~15,000 (estimate) | ~54% | comfortable; loses at-speed MVM |

12-bit accumulators are the minimum with guaranteed no-clip (4-bit
activations over 64 rows bound |acc| at 960). A 1x1 tile does not fit
any configuration (placeable ~11,000 um2 after the array keepout).

The binding constraint turned out to be VERTICAL WIRING, not cell
area: with all 43 template pins on the north edge and the array macro
forcing the logic south, the stored-activation configurations exceed
the tile's physical met2+met4 capacity (global routing 20-40% over on
every layer at 70-85% utilization; the activation store's 64:1 read
mux fabric dominates the demand). The hardened tile is therefore the
streamed-activation configuration: cirom_dig_ctrl's STORE_ACTS=0
variant replaces the store with one row-pair register and a wait
state; the host streams each activation byte just in time (re-sent
per column-group pass) and the controller stalls when starved, so any
slower-than-consumption host is safe. Raw-read mode and the pin
contract are unchanged; MVM becomes host-paced (the STORE_ACTS=1
at-speed variant remains the library default for larger dies whose
floorplans have the wiring supply).

## Pin map and protocol

Digital-only template (no ua pins, no analog pin fees).

| Pins | Direction | Function |
|---|---|---|
| ui[7:0] | in | activation byte while streaming (two 4-bit magnitudes, low nibble = even row); row address (ui[5:0]) in raw-read mode |
| uio[0] | in | act_wr (streams the 64-element vector one byte per row pair, re-sent per pass) |
| uio[1] | in | start |
| uio[2] | in | mode: 0 = matrix-vector multiply, 1 = raw row read |
| uio[3] | in | cfg_mode (serial config, same scheme as the analog tile) |
| uio[4] | in | cfg_in |
| uo[7:0] | out | result byte stream (MVM: 32 columns x 2 bytes, low byte first; raw: 8 bytes {neg_hit, pos_hit}) |
| uio[5] | out | result_valid |
| uio[6] | out | busy |
| uio[7] | out | done |
| clk, rst_n, ena | harness | 20 MHz target |

MVM sequence (streamed activations): pulse start, then stream the
64-element activation vector one byte per row pair, re-sent for each
of the 8 column-group passes; the controller stalls when starved, so
any slower-than-consumption host is safe. Per row: precharge,
wordline, strobe-sample, accumulate (sign from the BLP/BLN pair,
magnitude weighting by the streamed activation); after each pass the
group's 4 accumulators stream as bytes with result_valid, 64 result
bytes total in ascending column order. Raw row-read mode reproduces
the tile62 digital readout on the shared 16 columns and extends it to
all 32 (8 bytes per row).
At 20 MHz an MVM is on the order of tens of microseconds; the bench
sweeps the clock to map the read-timing margin.

## Signoff

The compiler-emitted tile (test0 mask program, the same
weight matrix as the analog tile so the two vehicles differ only in
readout style; all 32 columns sensed, N_ACC=4 across 8 passes,
STORE_ACTS=0) is through the full LibreLane flow with the signoff
gates clean:

- KLayout DRC (sky130A_mr, the gate of record): 0 errors
- netgen LVS: circuits match uniquely
- OpenSTA, 9 corners: 0 setup / 0 hold violations (worst setup slack
  +29.4 ns at the 50 ns clock; worst hold +0.11 ns). Flags on record:
  slow-corner max-slew pins confined to deliberate hold-fix
  delay-cell chains (slow edges are their function; same cell class as
  the signed-off chip), and one CTS root-buffer fanout flag.
- Global routing closes with layer usage 12-52% and negligible
  overflow; detailed routing is clean.
- Magic DRC reports 15,738 under exactly four wide-metal
  spacing-to-unrelated rules (met1.3b/met2.3b/met3.3d/met4.5b), the
  known over-fire class on the hand-drawn PDN straps; KLayout's full
  deck is clean, matching the chip-level signoff discipline.
- Routed logic: 10,501 um2 movable cells (~40% of placeable) beside
  the 5,345 um2 array macro on the 1x2 die.

RTL is green in both activation configurations: the self-checking
bench passes a full bit-exact matrix-vector multiply and all-64-row
raw reads on the checker and zero-heavy patterns (stored) and on the
hardened test0 configuration (streamed). The tile is COMPILER-EMITTED:
ankhdjet.backend.tt_digital emits the top and the front-end binding to
a named weight macro per shape (optionally with the macro's .wmat mask
program from the same call), and tests/test_tt_digital_emit.py proves
the emitted tile bit-exact through the same bench (fast regression
tier).

## Verification

The unchanged chain: Python reference and Verilator RTL bit-exact on
real checkpoint slices (the column and pipeline primitives in rtl/ are
already Verilator-proven); the silicon bench streams activation
vectors and compares streamed results against the golden model,
pass/fail per vector, across a clock sweep.

## Flow deltas from tile62

Reuses the tile62 LibreLane recipe minus everything that made it hard:
no sense bands, no VREF broadcast, no ua strip, no analog pin checks.
Keeps the array PDN and pin-template lessons. New physical content is
one standard-cell region and the bitline landing to the sense flops.
