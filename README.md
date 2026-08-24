<h1 align="center">☥ Ankhdjet</h1>

<p align="center"><strong>A model is a mask set.</strong></p>

<p align="center">
  <a href="https://github.com/mpai17/ankhdjet/actions/workflows/fast-check.yml"><img alt="fast-check" src="https://img.shields.io/github/actions/workflow/status/mpai17/ankhdjet/fast-check.yml?branch=master&style=for-the-badge&label=fast-check"></a>
  <a href="LICENSE"><img alt="License Apache 2.0" src="https://img.shields.io/badge/license-Apache_2.0-blue?style=for-the-badge"></a>
</p>

**Ankhdjet is node-agnostic compiler infrastructure for hardwiring
ternary LLMs into mask-programmed silicon.** Each weight becomes one
transistor's drain metallization ({+1, −1, 0}), read by clocked
full-swing bitline sampling and accumulated in synthesized RTL: a
fully digital datapath around a mask-programmed core.

<p align="center">
  <a href="#how-it-works">How it works</a> &nbsp;·&nbsp;
  <a href="#quick-start">Quick start</a> &nbsp;·&nbsp;
  <a href="#pdk-support">PDK support</a> &nbsp;·&nbsp;
  <a href="#verification">Verification</a> &nbsp;·&nbsp;
  <a href="docs/">Design records</a> &nbsp;·&nbsp;
  <a href="docs/results.md">Results</a>
</p>

The architecture is defined against a
**[standard macro contract](docs/macro_contract.md)**, not
a process: any PDK that implements the contract's two custom cells
(bitcell, precharge) and its macro interface (LEF/Liberty/blackbox/LVS
views) inherits the entire stack: the PyTorch/HuggingFace frontend,
the SystemVerilog backend, bit-exact verification, the physical flow,
and the area/throughput estimators. The readout is standard-cell
sampling, so the digital emission is the read at every node and
advanced nodes port by synthesis. An analog comparator readout exists
as a measured, characterization-gated variant within the 180-28 nm
window (see the design records).

- **Weights:** ternary (1.58-bit); any HuggingFace checkpoint whose
  matmul weights decode to {−1, 0, +1} with per-tensor scales. The
  frontend detects the storage per tensor: BitNet-style packed 2-bit,
  ternary-valued float (TriLM-class unpacked releases), or QAT master
  weights through the opt-in absmean transform
- **Output:** CiROM array hard macros + wrapper RTL + a full
  physical-implementation flow (Magic/KLayout/netgen/ngspice/Yosys/
  OpenROAD via LibreLane; PDKs managed by ciel)
- **Proof of concept:** a complete SKY130 implementation of the
  contract taken through full signoff in both readout styles on the
  same die and read contract, the digital sampler chip leading
  (results in [docs/results.md](docs/results.md))
- **GF180MCU and ASAP7:** calibrated area/throughput estimators
  (GF180MCU also with measured bitcell timing); a port is the
  contract's custom cells plus signoff collateral
  ([docs/porting.md](docs/porting.md))

## How it works

![Ankhdjet pipeline](https://raw.githubusercontent.com/mpai17/ankhdjet/master/docs/figures/ankhdjet_pipeline.png)

The frontend imports a ternary checkpoint into the compiler IR. The
backend re-expresses it twice: as mask programs (one via choice per
cell, the only per-model geometry) and as SystemVerilog composing the
verified RTL library (grid readout, between-layer requantize), with
per-shape macro abstracts beside them. Every emitted design is proven
bit-exact against the Python reference before anything physical
happens.

Physical realization consumes that bundle through the macro contract:
the mask-programmed array and its clocked precharge harden as a
custom macro, read by full-swing bitline sampling in standard cells,
and the LibreLane flow carries the assembly to signoff. The SKY130
reference implementation's cell is `bitcell_v4` (one NMOS per ternary
weight, 64 rows per bitline; the bitcell spec carries the geometry).

Design records live in [`docs/`](docs/): the
[macro contract](docs/macro_contract.md) any PDK implements to
inherit the stack, the
[digital readout record](docs/digital_readout.md), the array
architecture and its production precedent, the bitcell spec, the
measured decision records (precharge, VREF), and the DRC/LVS
forensics catalogs.

## Quick start

The compiler and calibrated estimators install from PyPI; the silicon
flow (custom cells, LibreLane hardening, signoff) lives in this repo:

```bash
pip install ankhdjet
ankhdjet estimate -- --list-pdks                      # bundled PDK descriptors
ankhdjet compile microsoft/bitnet-b1.58-2B-4T -o out/     # checkpoint -> design bundle (masks + standalone RTL)
```

Full repo environment:

```bash
uv sync                            # Python 3.11 + pinned deps into .venv (uv.lock)
bash tools/apply_env_patches.sh    # re-apply the librelane sign-off ECO hook (required)

# Bit-exact validation: Python reference vs Verilator vs PyTorch on
# real Microsoft BitNet b1.58-2B-4T weight slices.
tools/run_tests.sh

# Rebuild + re-verify the entire silicon stack from generators:
# cells, arrays, mask programming, macros, bands, per-level LVS,
# functional regressions. Ends with:
#   [band16] Circuits match uniquely.
#   [test0] PASS: 396 checks, 0 errors
tools/rebuild_all.sh checker test0

# Chip flow to full signoff (LibreLane: ~15 min):
bash librelane/cirom_chip_digital/run_librelane.sh   # banded analog variant: librelane/cirom_chip_analog/
```

Compile your own weights: drop `weights/<name>.wmat` (rows of `+-0`
characters), run the array/macro generators with `ANKHDJET_WEIGHTS=<name>
ANKHDJET_WEIGHTS_FILE=...`, point the flow config at the new macro; the
functional bench reads its expectations from the generated `.memh`
views (`ARRAY=<name> rtl/chip/sim/run_sim.sh`).

## PDK support

| PDK | Custom cells | Array → chip flow | Estimators |
|---|---|---|---|
| SKY130 (130 nm) | bitcell, precharge (comparator bands for the analog variant) | full, signed off in both readout styles | calibrated |
| GF180MCU (180 nm) | bitcell timing characterized (ngspice, measured 1.25× SKY130) | – | calibrated |
| ASAP7 (7 nm) | – | – | calibrated |

The estimator chain (the area model and throughput calibration in
the `ankhdjet` package) is anchored to Yosys synthesis per
PDK and three independent throughput evidence sources (silicon
back-fit of open-PDK tapeouts, IRDS 2024 interconnect scaling, foundry
SRAM datasheets), emitted as bracketed low/mid/high values. Example:

```bash
uv run ankhdjet compare                   # area + tok/s across the PDK anchors
uv run ankhdjet fit --bracketed           # largest ternary transformer per die size
```

## Verification

| Layer | Check | Receipt |
|---|---|---|
| Compiler/RTL | bit-exact vs Python reference (Verilator), incl. Microsoft b1.58-2B-4T slices | `tools/run_tests.sh` |
| Cell/row/band/macro | Magic + KLayout DRC; flat-extraction netgen vs generated schematics | `tools/rebuild_all.sh` → "Circuits match uniquely" per level |
| Analog variant | 250-trial Monte Carlo comparator offset; extracted-netlist read validation (discharge, coupling, kickback, VREF) across corners | `cell/sky130/*/sim*/` timestamped logs |
| Chip | KLayout `sky130A_mr.drc` (full options), netgen LVS, OpenSTA, functional regression per weight matrix | `librelane/cirom_chip_*/runs/<tag>/final/metrics.json` |
| Silicon vehicles | TinyTapeout's hosted gds / precheck / docs workflows (third-party infrastructure) | [tt_um_azara_cirom](https://github.com/mpai17/tt_um_azara_cirom/actions) · [tt_um_darga_cirom](https://github.com/mpai17/tt_um_darga_cirom/actions) |

Regression runs persist timestamped pass/fail logs under their build
directories; signoff metrics of record are reported in
[docs/results.md](docs/results.md).

## Repository layout

```
cell/sky130/        bitcell_v4, precharge pair, sa_se comparator, sense
                    bands; generators + per-cell DRC/LVS/SPICE suites
macro/sky130/       array-macro abstracts (LEF/Liberty/blackbox/LVS
                    schematic/.memh sim views) + estimator-path generator
librelane/          chip + TinyTapeout tile hardening flows, digital
                    and analog variants of each
rtl/                chip top + functional bench; column/between-layer/
                    pipeline primitives the compiler instantiates
ankhdjet/           PyTorch frontend, Verilog backend, bit-exact
                    references, area/throughput model
weights/            committed {+,-,0} matrices (the mask source format)
tools/              rebuild_all.sh, ECO fill generator, GDS renderer,
                    cross-PDK analysis, OpenROAD anchor harness
docs/               design records + figures/
tests/              Verilator bit-exact suite
```

## Acknowledgements

Ankhdjet stands on the open-silicon toolchain: [Magic](http://opencircuitdesign.com/magic/),
[KLayout](https://www.klayout.de/), [netgen](http://opencircuitdesign.com/netgen/),
[ngspice](https://ngspice.sourceforge.io/), [Yosys](https://github.com/YosysHQ/yosys),
[OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD),
[LibreLane](https://github.com/librelane/librelane), the
[SkyWater SKY130 PDK](https://github.com/google/skywater-pdk), and
[ciel](https://github.com/fossi-foundation/ciel). The architecture is
grounded in published peers; BitROM
([arXiv:2509.08542](https://arxiv.org/abs/2509.08542)) foremost; with
the full citation chain in the design records.

## License

[Apache License 2.0](LICENSE).
