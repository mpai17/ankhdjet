# Porting the contract to a new PDK

How-to guide for bringing a new process under the compiler. A port
implements the macro contract's two custom cells, generates the
macro views, and passes the signoff obligations; everything above
the contract (frontend, RTL emitters, verification benches, flow,
estimators) is inherited unchanged. The contract document states
what must exist; this guide gives the working order, with the SKY130
implementation as the worked example and GF180MCU as a partial port
(cells characterized, no chip flow).

## 1. Bitcell

1. Lay out the 1T cell at the target pitch: WL gate strap, drain
   with the three mask-route candidates (BL+, BL−, unconnected),
   source into a grounded per-column strap, body taps per the PDK's
   latch-up rules.
2. Characterize discharge with ngspice against the PDK's device
   models: slow-corner discharge to the sampling threshold at the
   chosen rows-per-bitline depth must fit the evaluate state with
   margin (SKY130 reference: 64 rows, 1.07 ns to 0.3 V at
   ss/100C/1.62 V against 8 ns). Keep the decks and measured
   numbers with the cell.
3. Close cell-level DRC under the PDK's authoritative deck, and
   flat-extraction LVS against the generated schematic, including
   the dangling-drain zero case.

## 2. Precharge cell

1. Lay out one PMOS pull-up per bitline polarity, pitch-matched to
   the cell column, gate on PRE_N. No keeper (the precharge design
   record carries the measured rationale; re-run the leakage-droop
   check if the target node's leakage regime differs from SKY130's).
2. Measure recovery to the sampling margin within the precharge
   state at the slow corner.

## 3. Macro assembly and the LVS ladder

1. Run the array/macro generators for the target shapes and a
   committed test mask program.
2. Pass the per-level flat-extraction ladder in order: cell,
   precharge row, array, macro, each reporting "Circuits match
   uniquely" against its own generated schematic. Do not skip
   levels: the ladder exists because chip-level checks structurally
   miss hand-assembly defect classes (jog-abutment shorts, well
   overlaps onto device diffusion; the LVS forensics record has the
   catalog).
3. `tools/gen_macro.sh <N> <M> <name> [wmat]` (driven per vehicle by
   `tools/rebuild_tt_digital.sh`) is the reference driver at SKY130; a
   port reproduces its per-level structure against the new PDK's decks
   and models.

## 4. Views

Generate the per-program view set the contract specifies: GDS with
via programming, LEF (pins router-reachable and on the PIN datatype;
risers for sub-pitch pins), Liberty from the measured
characterization, blackbox Verilog, LVS schematic, `.memh` sim
views. The LEF/pin failure classes and their fixes are documented in
the LVS forensics record; read it before inventing new pin geometry.

## 5. Functional regression

Run the behavioral bench against the `.memh` views per mask program
(`ARRAY=<name> rtl/chip/sim/run_sim.sh`) and the bit-exact suite
(`tools/run_tests.sh`): Python reference, Verilator RTL, and real
checkpoint slices must agree exactly. Regressions persist
timestamped pass/fail logs under their build directories; a port's
evidence is those logs, not terminal output.

## 6. Chip flow

Point the LibreLane flow at the new macro (config, macro placement,
pin order) and take a chip top through full signoff: DRC clean under
the PDK's authoritative deck, LVS 0, STA clean, functional
regression green. The SKY130 configs under `librelane/` are the
reference; the PDN pattern for custom hard macros (perimeter ring,
via stacks from the chip grid) is recorded in the flow's design
records and failure logs.

## 7. Estimator descriptor

Add a PDK descriptor with a synthesis anchor (the digital wrapper
RTL synthesized against the PDK's standard cells) and throughput
evidence per the calibration methodology, so `ankhdjet compare` and
`ankhdjet fit` report the new node with bracketed values. A
predictive or NDA-bound PDK that cannot publish signoff artifacts is
still estimator-supportable; mark the calibration sources.

## Analog variant addendum

Only within the comparator window (180-28 nm), and only if the
variant's win conditions justify it: add the comparator cell and
replica column, re-run the Monte Carlo offset methodology (SKY130
reference: 250/250 at the realistic bitline signal, per-corner), and
carry the reference subsystem obligations from the VREF record. The
digital tier requires none of this and is the correct first target
for every port.
