# RTL library

Hand-written SystemVerilog the compiler composes. The emitters in the
`ankhdjet` package generate structure only (module wrappers, weight
parameter literals, instance grids, port bindings); every state
machine, accumulator, and datapath lives here as a static,
individually testable file. That split is what the verification
chain leans on: the Verilator bit-exact suite (`tests/`) and the
functional benches below prove these blocks once, and generated
designs are compositions of them.

The read they implement is the digital tier of the macro contract
(clocked precharge, full-swing bitline capture, synthesized
accumulation); the analog-variant tops exist alongside as the
documented comparator experiment. Contract and readout records:
`docs/macro_contract.md`, `docs/digital_readout.md`; numbers of
record: `docs/results.md`.

## Layout

- **`column/`**: the NOR-array tile primitive the per-layer emitter
  wraps, with the layer's mask program baked in as parameters.
- **`between_layer/`**: the inter-layer chain (shared per-tensor
  Q8.8 requantize scale and saturating quantize) the pipeline
  emitter threads between consecutive layers.
- **`grid/`**: the multi-macro level: a grid controller that sweeps
  a tiled layer's macro grid and accumulates the full matrix-vector
  product, plus the behavioral chunk model that reads per-chunk
  memh views. Bench under `sim/`.
- **`chip/`**: the two signed-off SKY130 chip tops on the same die
  and read contract, `cirom_chip_digital` (full-swing sampler
  readout, the flagship signoff) and `cirom_chip_analog` (banded
  comparator variant), with the shared functional bench and
  behavioral macro models under `sim/`.
- **`tt_digital/`**: the Darga shuttle tile (`tt_um_darga_cirom`):
  read FSM, activation streaming, and the on-die ternary MAC, with
  its bench under `sim/`.
- **`tt_analog/`**: the Azara shuttle tile (`tt_um_azara_cirom`),
  the analog-variant controlled experiment carrying the same mask
  program as Darga, with its benches and lint/synth/power gates
  under `sim/`.

## Running the benches

```bash
TOP=digital ARRAY=test0 rtl/chip/sim/run_sim.sh   # chip functional bench (TOP=digital|bands)
rtl/tt_digital/sim/run_tt_um_digital_tb.sh        # Darga tile bench
rtl/tt_analog/sim/run_tt_um_tb.sh                 # Azara tile bench
tools/run_tests.sh                                # Verilator bit-exact suite over these primitives
```

Benches read their expectations from the generated `.memh` views, so
simulation exercises the same mask program the GDS carries, and every
run persists a timestamped pass/fail log under its `sim/build/`
directory.
