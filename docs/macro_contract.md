# The standard macro contract

Reference specification for the boundary between the node-agnostic
compiler stack and any PDK's physical implementation. A PDK that
implements this contract inherits the entire stack unchanged: the
PyTorch/HuggingFace frontend, the SystemVerilog backend, the
bit-exact verification chain, the LibreLane physical flow, and the
area/throughput estimators. The porting guide walks the
implementation order; this document states what must exist and what
it must satisfy.

## The two custom cells

The digital tier (the readout of record) requires exactly two
hand-laid-out cells per PDK. The analog comparator variant adds two
more (comparator, replica column), specified in the array
architecture record and required only within its 180-28 nm window.

**Bitcell.** One NMOS storing one ternary weight:

- Gate on the row wordline; source on a grounded per-column
  source/read network; drain mask-routed per weight to the column's
  BL+ strip (+1), BL− strip (−1), or left unconnected (0).
- The mask program is the only per-model geometry: one via/jog
  finishing choice per cell instance, written from a `{+,-,0}` text
  matrix. Zero-weight cells are mask-absent (floating drain stub,
  modeled as a dangling net in the LVS schematic).
- Discharge at the slow corner must complete within the read
  contract's evaluate state at the chosen rows-per-bitline depth
  (the SKY130 reference: 64 rows, measured 0.54/1.07 ns to
  0.9/0.3 V at ss/100C/1.62 V against an 8 ns evaluate state).
- Laid out at a custom array pitch and assembled as a hard macro;
  no standard-cell row sharing. Body taps per the PDK's latch-up
  rules (SKY130 reference: a tap cell row every 8 rows).

The implemented SKY130 cell is specified in the bitcell spec
(`bitcell_v4`, W=0.42/L=0.17, 1.70 × 1.30 µm).

**Precharge cell.** One PMOS pull-up per bitline (both polarities):

- Source/body to VDD, drain on the bitline, gate on an active-low
  PRE_N; no keeper, no equalizer (the precharge design record
  carries the measured rationale).
- Recovery to the sampling margin within the precharge state at the
  slow corner (SKY130 reference: 1.63 ns to 95% VDD against a
  cycle-state budget of several ns).
- Pitch-matched to the cell column and assembled into the same hard
  macro.

## The macro interface

The macro generator produces, per `(N rows, M columns, weight
matrix)` tuple, a hard macro named for its mask program (the SKY130
reference generator emits `macro_array_pc_<N>x<M>_<program>`)
containing the cell array and the precharge row. Its boundary:

- **Ports**: one wordline input per row (`WL_r`, one-hot per read);
  one BL+/BL− pair per column (`BLP_c`, `BLN_c`); the active-low
  precharge control (`PRE_N`); power (`VPWR`, `VGND`). Sense,
  capture, and accumulation live outside the macro in the digital
  tier.
- **Views**, one set per mask program:
  - GDS with every cell's via programming applied.
  - LEF abstract: footprint, perimeter/riser-accessible pins,
    obstruction map. Pins must be presented so the chip router can
    reach them and so extraction binds them (pin labels on the PIN
    datatype; buried sub-pitch pins need risers to the macro
    boundary: the LVS forensics record documents the failure
    classes).
  - Liberty characterized from measured simulation (corner set,
    slew × load grid) so the chip flow's STA is grounded in the
    PDK's device models.
  - Blackbox Verilog (`.bb.v`) declaring the port list for
    synthesis; the macro is `(* blackbox *)` to Yosys.
  - LVS schematic (`.lvs.spice`): the generated transistor-level
    netlist including mask-programmed connectivity and dangling
    zero-weight drains, the reference every extraction is compared
    against.
  - `.memh` simulation views (per-program `wpos`/`wneg` row images)
    so behavioral RTL simulation reads the same mask program the
    GDS carries.

## The read contract

One row read, timed by the wrapper FSM (states as implemented in the
signed-off chips):

1. **Precharge**: PRE_N low, no WL asserted, both bitline polarities
   pull to VDD (bitlines also park high in idle).
2. **Evaluate**: PRE_N high, one WL asserted; the programmed cell
   discharges BL+ (+1) or BL− (−1) or neither (0).
3. **Strobe**: WL held high; the readout captures the bitline state
   (digital tier: full-swing sample into standard-cell registers).
4. **Hold/valid**: captured outputs are registered and flagged
   valid; WL and PRE_N return for the next cycle.

Break-before-make between precharge and evaluate comes from the
decoder/driver delay; the discharged bitline stays driven through
the strobe. Accumulation over rows and activation bit-slices,
scaling, and requantization are synthesized RTL above this contract
and are identical at every node.

## Signoff obligations

A conforming port demonstrates, with artifacts:

1. **DRC**: cell, macro, and chip clean under the PDK's
   authoritative deck (at SKY130: KLayout `sky130A_mr.drc` with full
   options; engine and deck versions recorded with the run).
2. **LVS**: flat extraction against the generated LVS schematic
   reporting "Circuits match uniquely" at every hand-assembled
   level (cell, precharge row, array, macro, chip). Per-level LVS
   is load-bearing: it catches silent shorts chip-level checks
   structurally cannot see.
3. **Characterization**: measured discharge/recovery transients at
   corners from the PDK's device models, feeding the Liberty views.
4. **Functional regression**: the behavioral bench reading the
   `.memh` views bit-exact against the Python reference, per mask
   program, with timestamped pass/fail logs.
5. **Chip flow**: the LibreLane flow consuming GDS + LEF + Liberty
   through DRC/LVS/STA signoff with the macro in place.

## Reference implementations

SKY130 implements the full contract through chip signoff in both
readout tiers on the same die and read contract (`cirom_chip_digital`
and `cirom_chip_analog`; numbers in the results record). GF180MCU
implements the bitcell with measured discharge characterization
(1.25× SKY130 at its scaled cell). ASAP7 consumes the contract
through the estimators and the OpenROAD block anchor; below 28 nm
only the digital tier exists, so an advanced-node port is the two
custom cells plus synthesis.
