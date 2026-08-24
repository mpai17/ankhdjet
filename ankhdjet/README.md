# Ankhdjet compiler package

The installable compiler: checkpoint in, mask set out, plus the
calibrated estimators. This package is what `pip install ankhdjet`
ships; the physical flow (custom cells, LibreLane hardening, signoff)
lives in the repository because it needs the open-silicon toolchain.

The command surface (`-h` on any command is the flag reference):

| Command | Purpose |
|---|---|
| `ankhdjet compile <model> -o out/` | checkpoint to a complete design bundle; `--harden` adds the hard-macro view |
| `ankhdjet verify --dir out/` | bit-exact audit of an emitted mask set against its checkpoint |
| `ankhdjet estimate -- --list-pdks` | area + bracketed throughput report for any model shape on any descriptor |
| `ankhdjet compare` | side-by-side area/throughput across the discovered descriptors |
| `ankhdjet fit --bracketed` | largest canonical model shape that fits a die budget |
| `ankhdjet pdk list` / `pdk validate <name>` | discover and conformance-check PDK packs |

Compile's output is a complete design bundle: the mask programs (the
fab handoff) beside a self-contained RTL view of the same design,
with a filelist so `iverilog -g2012 -f out/filelist.f` elaborates on
a machine that has never seen the repository (`--no-rtl` for masks
only). The bundle also carries per-shape hard-macro abstracts under
`macros/` (LEF footprint, anchor-scaled Liberty, blackbox Verilog):
template-grade floorplanning collateral generated from the PDK
descriptor's characterized anchor, with the hardened macro's
extracted views remaining the signoff collateral. Checkpoint to RTL plus mask set is the compiler; GDS hardening
is the repository-side backend toolchain, the way a software compiler
relates to its linker.

`frontend/` turns checkpoints into the ternary IR, `backend/` turns
IR into mask programs and RTL, `reference/` holds the bit-exact
golden models, and `estimate/` is the calibrated estimator chain
behind `ankhdjet estimate`; the top level carries only the entry
point and the PDK pack resolver.

## How a model flows through

**Frontend: checkpoint to IR.** The importer pulls the HuggingFace
config, parses the architecture (hidden size, layer count,
attention/KV heads, FFN width, vocab), and builds the IR: one layer
per matmul-resident projection per block, each carrying its ternary
weight tensor. It then decodes each stored tensor into a plain int8
{-1, 0, +1} matrix with its per-tensor scale, detecting the storage
format per tensor: BitNet-style packed 2-bit lanes, ternary-valued
float (TriLM-class unpacked releases), or, on request, QAT master
weights through the b1.58 absmean transform. A tensor that is none
of these is refused as non-ternary. Two guardrails: the bf16-tied `lm_head` is refused as
off-fabric (an embedding table, not ternary silicon; recorded in the
manifest rather than silently dropped), and a layer whose weights
cannot be loaded keeps correct dimensions but a loudly-flagged
placeholder, so area estimation still works while emission and
verification refuse it.

**Backend, path one: the mask set.** `ankhdjet compile` tiles every
LINEAR layer's N x M matrix into macro-sized chunks (ragged edges
zero-padded, and a padded position is physically a zero weight: a
floating drain). Each chunk becomes a `.wmat` file, literal rows of
`+-0` characters, one per cell. That text format is the handoff to
physical reality: the array generator reads it and places each
cell's via/jog choice, which is the entire per-model mask
difference. Per-layer manifests record grid geometry, padding, and a
content digest per chunk; a model manifest records totals.

**Backend, path two: the RTL beside it.** The emitters produce
SystemVerilog structure that composes the hand-written library in
`rtl/`, never logic: a per-layer wrap of the tile primitive with the
weights baked in as parameters (the test-scale path the Verilator
suite chews on), a multi-layer pipeline chained through the Q8.8
requantize with a valid/start handshake, a grid top that sweeps a
whole tiled layer's macro grid and accumulates every output column in
parallel, and the Darga shuttle-tile top. The library files the
bundle composes ship inside the wheel and are copied into every
compiled output beside the generated tops, with the behavioral memh
views of the same mask programs and the parameterized smoke bench, so
the bundle stands alone; a digest manifest records all of it. Every
name crossing into RTL is legalized and collision-checked at the
emission boundary.

**The trust chain.** The reference modules are pure-math oracles
(the bit-serial ternary MAC, the NOR readout ordering, the
requantize, the BiROMA encoding), and the Verilator suite demands
bit-exactness between them and every emitted design, including on
real checkpoint slices. The same weights travel three independent
routes (parameter bitmasks, memh views, `.wmat` to GDS) that are
cross-checked against each other; the emission audit reassembles
mask programs from disk and compares them bit-for-bit against the
checkpoint, and the architectural twin decodes the model three
independent ways and demands token-for-token agreement. A compiler
bug has to survive all of that to ship.

**Estimators.** The area model takes IR + config + a PDK descriptor
YAML and produces block-level area (cells from the anchored
um2/weight, periphery from synthesis-anchored gate counts, KV SRAM,
attention engine, overhead) plus a cycle model for tok/s, per
readout tier. The throughput calibration back-fits the derating
knobs (clock skew vs area, wire hops, KV access cycles) from
independent evidence classes (silicon back-fits of open-PDK
tapeouts, IRDS interconnect scaling, SRAM datasheets) into the
low/mid/high brackets everything downstream reports.

In one sentence: the frontend proves it understood the model, the
backend re-expresses it as masks plus structure over pre-verified
RTL, and the verification chain proves both re-expressions compute
the same integers the checkpoint does; that is why "the weights are
the mask, everything else is fixed" holds from a HuggingFace repo id
to signed-off GDS.

## PDK packs and numbers

A PDK plugs into the compiler as a pack: a data-only directory whose
manifest declares its capability tiers (estimator descriptors,
macro-abstract constants with an anchor LEF, physical collateral).
Packs are discovered from `ANKHDJET_PDK_PATH`, from installed
packages exposing the `ankhdjet.pdks` entry-point group, and from the
copy bundled inside the wheel, in that order, so commercial packs
plug in from private repositories or indexes without touching this
package. `ankhdjet pdk list` shows what is reachable and `ankhdjet
pdk validate <name>` checks a pack's conformance, including that its
abstract constants regenerate its anchor's extracted LEF. All
throughput output is bracketed low/mid/high per the calibration
evidence; the numbers of record live in
[`docs/results.md`](../docs/results.md), and the interface the
emitted silicon implements is specified in
[`docs/macro_contract.md`](../docs/macro_contract.md).

## Verification

The `package`-marked pytest tier runs on core dependencies only and
gates the pip artifact; `tools/run_tests.sh` runs the full bit-exact
chain (Python references vs Verilator vs PyTorch on real checkpoint
slices); `ankhdjet verify` audits emitted mask programs
bit-for-bit against the checkpoint.
