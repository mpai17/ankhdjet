# Full-array SPICE integration testing

The framework wires the project's hand-laid custom cells
(`bitcell_v4`, `precharge`, `strongarm`) together at the macro
level: weights are mask-programmed into the deck (one device per
`+1`/`-1` cell, drain on the matching BL or VGND), per-BL precharge
PMOSes, per-column StrongARM SAs, full SUBCOL=64 BL capacitance
loading, row-sequential stimulus across all N rows. ngspice solves
the BSIM transient end-to-end; the runner parses per-cycle SA
outputs and BL voltages and checks them against the bit-exact
Python reference (`ankhdjet.reference_nor`).

Module layout (under `macro/sky130/sim/spice_integration/`):

| File | Responsibility |
|---|---|
| `paths.py` | shared path constants |
| `deck.py` | `emit_array_deck` — build a SPICE netlist as a string |
| `patterns.py` | tier-1/2/3 coverage selectors |
| `reference.py` | `expected_per_cell` — Python truth |
| `check.py` | parse `.measure` outputs, diff vs reference, classify failures |
| `runner.py` | `run_pattern` + `main` — write deck, run ngspice, check, dispatch |
| `gen_array_spice.py` | offline deck-only generator (writes `.sp` without running ngspice) |

This is the **electrical** integration test — every transistor on
the sense path is a real SKY130 BSIM model. Complement to:

* per-cell SPICE (bitcell BL discharge / precharge BL recharge /
  StrongARM PVT + Monte Carlo) — verifies each cell in isolation
* behavioral wrapper sim (Verilator vs Python reference) —
  verifies wrapper RTL wiring and latency
* macro Liberty/LEF/synth tests — verifies the abstracts
  downstream tools consume

## Validated baselines

| Run | Shape | Corner | Coverage | Patterns | Outcome | Wall time |
|---|---|---|---|---|---|---|
| smoke pytest | 4×2 | TT | random seed 0 | 1 | PASS | ~30 s |
| 4×2 tier1 | 4×2 | TT | structured | 6 | 6/6 PASS | ~3 min |
| **64×32 tier1** | **64×32** | **TT** | **structured** | **6** | **6/6 PASS** | **~31 min** |

The 64×32 TT tier1 run is the **production-shape baseline** — every
one of the 2048 weight positions resolves correctly through the
full sense path under each of the 6 structured stress patterns:

* `all_pos`: every cell drives BL+ (worst-case BL+ discharge load,
  2048 simultaneous cell pull-downs through 32 SAs)
* `all_neg`: every cell drives BL- (worst-case BL- discharge load)
* `all_zero`: no cell discharges (BL leakage budget — verifies
  off-cell paths don't corrupt the SA decision)
* `checker`: alternating ±1 (mixed-polarity stress, catches
  charge-share or BL-coupling between adjacent columns)
* `stripe_row`: one row hot (decoder collision check — verifies
  unselected WLs stay LOW, no leakage from sibling rows)
* `stripe_col`: one column hot (per-BL leakage — verifies a single
  active discharge stays clean against 31 inactive columns)

## Run command

```bash
cd /home/mohnishp/workspace/Ankhdjet
ANKHDJET_NGSPICE_JOBS=4 uv run macro/sky130/sim/spice_integration/runner.py \
    -N 64 -M 32 --coverage tier1 --corner tt --timeout 7200
```

Result file: `/tmp/spice_64x32_tt_v2.log` (or
`build_array_64x32/log_*.log` for per-pattern ngspice output).

To write a single `.sp` deck to disk for hand inspection, piping to
another simulator, or checking into a fixture:

```bash
python macro/sky130/sim/spice_integration/gen_array_spice.py \
    -N 64 -M 32 --pattern all_pos --corner tt -o /tmp/array_64x32_all_pos_tt.sp
```

## Coverage tiers

Per OpenRAM functional.py + ISSCC CIM 2024 standard:

* **tier1** (structured): all-+1, all--1, all-0, checkerboard,
  stripe row/col. Catches systematic failures.
* **tier2** (random): logged seeds, statistical confidence.
* **tier3** (single-cell-hot exhaustive): one column hot at a time,
  every (r, c) verified across N×M cells.

CLI invocation (`runner.py` flags):

```bash
# Tier 1 only (~30 min wall at 64×32 TT, 4 jobs)
runner.py ... --coverage tier1

# Tier 1 + 3 random seeds
runner.py ... --coverage tier1+random

# Full coverage including 32 col-hot exhaustive (41 patterns total)
runner.py ... --coverage tier1+random+exhaustive
```

## Performance / runtime guidance

ngspice transient on a 64×32 array (~2200 BSIM transistors, 1.28 µs
simulated time) under SS corner with KLU is **CPU-bound**, ~75 min
of CPU time per pattern. With single-threaded ngspice but
internally-parallel KLU (~4 threads per process) and 4 parallel
patterns saturating a 16-core box, each batch of 4 patterns takes
~30 min wall.

Tested per-pattern wall time at TT corner:

| Jobs | Per-pattern wall | Notes |
|---|---|---|
| 6 | ~50+ min | over the 30-min subprocess timeout — too much KLU contention |
| **4** | **~25–30 min** | **sweet spot for a 16-core box** |
| 2 | ~15–20 min | 2x faster wall but uses only 8 cores |

The default in the runner is `min(len(patterns), CPU-2)`. Override
with `ANKHDJET_NGSPICE_JOBS=N` if you need different parallelism.

For SS corner add ~2–3× wall time. Full SS exhaustive coverage
(41 patterns) is realistic at ~6–10 hours overnight; not in the
default regression budget. The cell-level StrongARM Monte Carlo
(`cell/sky130/strongarm/sim/test_mc.py`) already covers SS
mismatch at 200-trial confidence — the SPICE integration test
covers the *sense path composition*, not the SA's offset
distribution.

## Failure modes

The runner classifies failures into 5 categories per ISSCC SRAM-SA
practice:

* `sense_margin` — `|OUTP − OUTM|` at sample edge below `vmargin`
  (default 0.1 V); SA failed to develop a clear decision
* `decision_flip` — SA decided opposite of the reference
* `off_cell_leakage` — for inactive cells, BLP or BLN dropped
  more than `bl_leak_threshold` (default 0.5 V) below VDD;
  off-cell or charge-share path leaking
* `pwl_malformed` — ngspice rejected one or more PWL voltage
  sources as non-increasing (deck emitter bug; surfaced as a
  hard fail rather than silent zero)
* `ngspice_timeout` — subprocess wall-clock budget exceeded

## Pytest integration

The fast smoke test runs in the default `macro/sky130/sim/`
regression as `test_full_array_spice.py::test_smoke_random_4x2_tt`
(~30 s). The slow tier1 test (`test_tier1_structured_4x2_tt`) is
marked `@pytest.mark.slow` and runs only when explicitly invoked.

The 64×32 production-shape runs (this baseline) are CLI-only — the
~30 min wall-clock is too long for a default `pytest` invocation.
Re-run via the CLI command above when validating layout-level
changes that might affect the sense path.

## 256×256 production-shape calibration

The 256×256 array (65,536 BSIM transistors, ~22 MB deck) is
**not viable at 4-job parallelism within an 8-hour per-pattern
wall budget**. A documented run at TT corner with
`ANKHDJET_NGSPICE_JOBS=4 --timeout 28800` saw all six tier-1 patterns
hit the 8-hour ngspice wall ceiling, including the low-activity
stripe patterns (256 active cells out of 65,536). Total runtime
~16 hours; verdict 0/6 PASS, all classified `ngspice_timeout`.

The bottleneck is matrix factorization, not switching activity:
KLU reuses the same 65k-row sparse LU per timestep regardless of
the active-cell count, so the stripe patterns ran nearly as long
as `all_pos`/`all_neg`. Memory-bandwidth contention from four
concurrent ngspice processes amplified per-pattern wall time
~2–3× over the single-job estimate.

Practical paths forward:

* **Sequential at the production shape**: `ANKHDJET_NGSPICE_JOBS=1
  --timeout 86400`. Each pattern gets the full memory bandwidth;
  expect ~6–8 hours per pattern. Tier 1 alone is ~36–48 hours.
* **Two-job parallelism**: `ANKHDJET_NGSPICE_JOBS=2
  --timeout 86400`. Halves wall time over sequential but still
  pays the contention penalty. Tier 1 ~12–24 hours.
* **128×128 reduced shape**: ~16× fewer cells than 256×256 brings
  per-pattern wall to ~30–60 min at 4 jobs. Tier 1 in ~3–6 hours
  is realistic and validates the same composition with adequate
  cell count for sub-array claims.

The 64×32 TT tier 1 baseline remains the validated production-shape
result for sense-path composition. Larger shapes are gated on
overnight wall-time budget rather than methodology.

## Open scaling questions

* **SS corner at 64×32**: ~6–10 hours overnight for full
  tier1+random+exhaustive. The mismatch SA validation is already
  done at the cell level; the value of full-array SS is to confirm
  the slow-corner BL-discharge timing margin. Recommend running
  once before final tape-out, not per-commit.
