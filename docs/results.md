# Results

Reporting record for Ankhdjet silicon and estimator results. The README
carries capability and method; numbers live here.

## SKY130 signoff

| Design | PDK | Size | Signoff |
|---|---|---|---|
| `cirom_chip_digital`: 64×32 ternary array, clocked precharge, full-swing sampler readout (no comparators, no reference pin), read FSM; same die, array placement, and read contract as the banded chip | SKY130 | 0.85 × 0.30 mm @ 25 ns | LVS 0, max-slew/cap/fanout 0, setup +16.3 ns / hold +0.11 ns; KLayout reports 2 items of the licon-enclosure engine-artifact class inside unmodified foundry cells (the signed-off banded GDS scores 17 under the same engine); Magic confined to the same four wide-metal rules as the banded chip; TB reconstructs 64/64 rows on both weight matrices |
| `cirom_chip_analog`: 64×32 ternary array, clocked precharge, 64 single-ended StrongARM comparators (4 bands), external VREF pin, read FSM | SKY130 | 0.85 × 0.30 mm @ 25 ns | DRC 0, LVS 0, max-slew/cap/fanout 0, setup +16.2 ns / hold +0.13 ns worst-corner (min_ff_n40C_1v95; nom-TT hold is +0.36 ns); re-signed after the band latch-up fix |
| Arbitrary-matrix variant; committed seeded sparse matrix (500/513/1035 of +1/−1/0) through the same flow | SKY130 | same | same gates, on the second mask program |
| TinyTapeout test vehicle `tt_um_azara_cirom`: one array macro (`test0` sparse matrix) + 32 single-ended comparators (2 bands, single-strobe, no mux), VREF external on `ua[0]`, column-0 bitline probes on `ua[1]`/`ua[2]` | SKY130 (TTSKY26c shuttle) | 1×2 tile | route DRC 0, shipped-GDS KLayout 0, LVS fully classified (bands match uniquely; residue = the band substrate port + benign extraction classes, verified on the shipped GDS), hosted precheck green, TB reconstructs 64/64 rows |

Any `{+,-,0}` text matrix compiles through mask programming to the same
signoff: the weights are the mask, everything else is fixed.

Verification is per-level and adversarial: every hand-assembled
structure (cell, precharge row, sense band, array macro, chip)
flat-extracts against its own generated transistor-level schematic.
This discipline caught defect classes that chip-level signoff
structurally cannot see; mask-jog abutment shorts, an nwell strip
overlapping latch diffusion, a resizer-inserted buffer digitizing the
analog reference.

## Estimator results (both density anchors)

The SKY130 estimators report two anchors: `sky130_biroma_bound` (the
BiROMA-density bound, 0.325 µm²/weight; BiROMA is NO-GO at SKY130 per
its investigation record, so this anchor brackets what a smaller-node
port recovers) and `sky130_v4` (the silicon-verified as-built cell,
2.21 µm²/weight). The 6.8× per-cell gap
decomposes as 2× encoding (one weight per cell vs BiROMA's two) ×
2.33× column pitch (BL strips, li ground network, mask-jog lanes) ×
1.46× row pitch (gate-top contact stack at L=0.17). Because chip area
is periphery-dominated, the as-built anchor costs ~14% total area at
the 22M reference shape, not 6.8×.

Estimates model the as-built 64-row bitline depth and report the
readout tier explicitly: analog (per-sub-column clocked StrongARM
comparators) or digital (full-swing bitline samplers, anchored to the
measured sampler32 synthesis). Below 28 nm only the digital tier
exists, so the asap7 anchor reports digital readout.

From `ankhdjet compare` (22M-param shape, tile_cols=16, bracketed
throughput):

| anchor | readout | total mm² | cells mm² | periphery mm² | tok/s (mid) |
|---|---|---|---|---|---|
| sky130_v4 (as built) | analog | 458.2 | 48.4 | 334.3 | 190,476 |
| sky130_v4 (as built) | digital | 285.2 | 48.4 | 183.9 | 190,476 |
| sky130_biroma_bound | analog | 401.2 | 7.1 | 326.1 | 190,476 |
| asap7 (anchored) | digital | 4.9 | 1.5 | 2.4 | 1,413,761 |

From `ankhdjet fit --bracketed` at a reticle-class 815 mm² die, largest fitting BitNet-class shape:

| anchor | largest fit | area | tok/s (mid) |
|---|---|---|---|
| sky130_biroma_bound | 41.5M (512×8) | 773 mm² | 303,030 |
| sky130_v4 (as built) | 22.9M (384×6) | 530 mm² | 320,513 |

(fit table at analog readout; the digital tier's smaller periphery
fits more at every anchor)

The asap7 anchor carries a measured synthesis point (2026-07-13): the
digital-tier controller synthesizes to 107.85 µm² against the ORFS
asap7sc7p5t RVT/TT libraries versus 22,207.5 µm² at sky130_fd_sc_hd
through the identical flow (205.9x for the same RTL; 4,441 SKY130
gate-equivalents map to 1,860 ASAP7 NAND2 equivalents), setting the
node's periphery calibration to 0.42.

## Full-model ASAP7 fit (density test, estimates)

The entire microsoft/bitnet-b1.58-2B-4T (2.4B ternary LINEAR weights,
30 blocks, hidden 2560, 4096-token KV context) fits a single
reticle-class die at the anchored ASAP7 density, digital readout:

| bitlines | acts | total mm² | of 815 mm² | tok/s (mid) |
|---|---|---|---|---|
| 256-row | A8 | 300.1 | 36.8% | 357,739 |
| 64-row | A8 | 340.0 | 41.7% | 1,338,091 |
| 64-row | A4 | 339.2 | 41.6% | 2,463,054 |

Breakdown at 256-row/A8: cells 145.9 mm² (2.08B ternary weights x
0.07 µm²/weight), periphery 68.1, KV cache SRAM 50.3, attention
engine 1.7, die overhead 32. The bf16-tied lm_head (328M params) is
off-fabric, matching the emitter, and is excluded from the hardwired
die (a large embedding table accounted separately, not ternary
silicon). The bottom-up bitcell carries a stated 0.05-0.10 µm²
sensitivity band, bounding the total at roughly 250-370 mm². At 7 nm
the bitline-depth tradeoff inverts from the 130 nm analog calculus:
64-row bitlines cost +14% area for 3.7x the throughput, since the
per-pass row window, not the sense periphery, dominates. All numbers
are calibrated model estimates from ankhdjet estimate
(--readout digital), not silicon, and are decode-fabric rates: on-die
periphery cycles (attention, KV access, inter-layer transport) are
charged per token, but the off-fabric lm_head and sampling are the
host's (at 64-row/A4 the head alone implies ~1.6 PFLOP/s of bf16).

The full depth sweep (A4 shown; A8 halves throughput at near-equal
area) has no sharp knee: area asymptotes at the ~325 mm2 cell+KV
floor while throughput halves per depth doubling, so throughput
density favors shallow bitlines monotonically within the model:

| rows | mm2 | tok/s | tok/s per mm2 |
|---|---|---|---|
| 16 | 484 | 6.67M | 13,783 |
| 32 | 390 | 4.21M | 10,801 |
| 64 | 339 | 2.46M | 7,263 |
| 128 | 312 | 1.33M | 4,282 |
| 256 | 297 | 699k | 2,355 |
| 512 | 289 | 358k | 1,237 |

Model risk concentrates at the extremes: deep points assume one row
per 667 ps clock regardless of bitline RC (optimistic at 512), and
shallow points imply macro counts the overhead fraction only crudely
captures (4.7M macros at 16-row x 32-col granularity). The anchored
design point is 64-row (the only silicon-calibrated read geometry);
32-row is a characterization-gated upside.

## Block-scale ASAP7 anchor (placed and clocked, not silicon)

A 2560x256 CiROM block slice (655,360 mask-programmed weights as a
hard macro behind generated LEF/Liberty abstracts, plus the readout
wrapper) runs through the ORFS asap7 flow end to end: synthesis,
floorplan, on-track macro placement, power grid, detailed placement,
then the anchor harness's CTS+STA pass. Result: setup met with
+0.405 ns slack at a 0.7 ns target (achieved fmax 3.39 GHz), 13.9 ps
clock skew, 0.064 mm2 die at 80% utilization
(tools/openroad/run_asap7_block.sh). The point enters the
throughput-calibration evidence as an OpenROAD CTS+STA anchor,
tightening the extrapolated-node brackets; hold shows -0.09 ns before
the standard hold-repair pass and is reported as-is.

## Full-model emission (the mask set, on disk)

ankhdjet.backend.macro_grid compiles every ternary layer of
microsoft/bitnet-b1.58-2B-4T into mask-programmed macro grids at the
anchored 64-row x 256-column geometry: 210 layers tile into 128,400
macros carrying 2,084,044,800 weights with 0.93% edge padding, 2.11 GB
of .wmat mask-program source, each chunk digest-recorded in per-layer
manifests (73 s checkpoint load + 273 s emission). The bf16-tied
lm_head is refused as off-fabric by the frontend's placeholder guard
and recorded as such in the model manifest. An independent content
audit (ankhdjet verify) reassembles every layer from the
chunk files on disk and compares bit-for-bit against the checkpoint:
210/210 layers exact, padding verified all-zero. The grid
readout/accumulation RTL emitter composes the emitted macros into
full-layer reads (bit-exact against numpy on clean, ragged, and
single-macro grids); the per-slice physical story is the block anchor
above.

## Ternary checkpoint coverage

The frontend is checkpoint-agnostic: any HuggingFace release whose
matmul weights decode to {-1, 0, +1} with per-tensor scales compiles,
with the storage format detected per tensor (packed 2-bit,
ternary-valued float, opt-in absmean for QAT master weights; anything
else is refused with a precise diagnosis, never silently quantized).
Coverage measured across five organizations' releases; die area is
the calibrated ASAP7 estimator's minimum-area configuration (digital
tier, mid bracket, 4096-token KV):

| Checkpoint | Storage | Fabric weights | Ingest evidence | ASAP7 die (mm2) |
|---|---|---|---|---|
| SpectraSuite/TriLM_190M_Unpacked | ternary fp16 | 0.113 B | full decode (zero frac 0.407) + compiled bundle: 6,912 macros, audit 112/112 bit-exact, standalone iverilog elaboration | 57 |
| 1bitLLM/bitnet_b1_58-large | f32 QAT master | 0.679 B | config-only (absmean opt-in applies) | 210 |
| tiiuae/Falcon3-1B-Instruct-1.58bit | packed u8 | 1.132 B | full decode (zero frac 0.297) | 213 |
| prism-ml/Ternary-Bonsai-1.7B-unpacked | group-scaled fp16 | 1.409 B | refused with diagnosis: sign mask recoverable, per-group scales exceed the per-tensor requantize contract | 282 |
| tiiuae/Falcon-E-1B-Base | packed u8 | 1.585 B | full decode (zero frac 0.411) | 238 |
| microsoft/bitnet-b1.58-2B-4T | packed u8 | 2.084 B | full decode (zero frac 0.422); emission audit 210/210 bit-exact | 340 |
| tiiuae/Falcon-E-3B-Base | packed u8 | 2.919 B | config-only | 424 |
| 1bitLLM/bitnet_b1_58-3B | f32 QAT master | 3.222 B | config-only | 671 |
| SpectraSuite/TriLM_3.9B_Unpacked | ternary fp16 | 3.681 B | config-only | 759 |
| tiiuae/Falcon3-7B-Instruct-1.58bit | packed u8 | 6.650 B | config-only | 950 |
| prism-ml/Ternary-Bonsai-8B-unpacked | group-scaled fp16 | 6.946 B | config-only | 997 |
| HF1BitLLM/Llama3-8B-1.58-100B-tokens | packed u8 | 6.979 B | full decode, streamed (zero frac 0.357) | 988 |

Everything at 3.9 B fabric weights and below estimates inside one
reticle-class ASAP7 die (~815 mm2); the ~7 B releases estimate just
past one reticle, the multi-die class. The refusal
posture is quantified by a cross-format experiment on the flagship:
applying the absmean transform to the released bf16 master weights
reproduces 98.47% of the packed release's ternary values (31.9 M of
2,084 M positions differ, rounding-boundary flips on
bf16-quantized masters), so coercing a non-ternary checkpoint
produces a near twin of the model, not the model; the strict ladder
therefore decodes exact ternary storage only and quantizes nothing
without an explicit request.

## Architectural twin (token parity)

tools/twin/run_twin.py decodes microsoft/bitnet-b1.58-2B-4T greedily
three ways and demands token-for-token agreement: the transformers
reference (assembled manually around its BitLinear modules, float32
so the integer matmuls are exact), a from-scratch numpy forward pass
with every ternary LINEAR as an exact integer matmul, and the
fabric's own decomposition (bit-serial activation planes over 64-row
subcolumn groups, signed activations offset-encoded onto the unsigned
read fabric, readout-order accumulation, self-checked for integer
equality against the plain matmul). Attention, norms, rotary,
sampling, and the lm_head run as documented behavioral stages; the
checkpoint ties lm_head to its bf16 embedding table, so the ternary
fabric carries 2.08B of the 2.4B weights and the head is accounted
off-fabric. Verdict (run 20260713T093554Z,
8 greedy tokens on a fixed raw prompt): all three decodes are
token-for-token identical, [279, 11, 279, 11, 279, 11, 279, 11], with
every arch-vs-plain integer equality assert passing (reference 44 s,
numpy 250 s, fabric decomposition 2,331 s on CPU). Two independent
weight-loading paths and three independent implementations agreeing
bit-wise is the twin's claim: the machine the compiler emits computes
this model.

Numbers regenerate from the named tools at the calibrated bracket
(`pdk/calibrated.yaml`).
