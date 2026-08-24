# Ankhdjet CiROM array architecture

## Scope: model + node agnostic at ternary (1.58-bit) precision

Ankhdjet is a compiler that hardwires **ternary (1.58-bit) weights** into
silicon. Within that fixed precision, the compiler is intentionally
model- and node-agnostic: it accepts any HuggingFace BitNet b1.58-class
model and emits CiROM macros + wrapper RTL targeted at any of three
open PDKs (SKY130 130 nm, GF180MCU 180 nm, ASAP7 7 nm).

Other quantization formats (Taalas's custom 3-bit + 6-bit-per-block
([taalas.com](https://taalas.com/the-path-to-ubiquitous-ai/)), INT4 /
GPTQ / AWQ, FP4) are explicitly out of scope for v1. They would
require a different cell encoding (more storage cells per weight, or
multi-level via / multi-threshold storage) and a wider accumulate
datapath, and in the analog variant additionally a different sense
path (multi-comparator flash chain or TDC); i.e. a different
instance of the same architectural family. The fixed-precision scope
keeps the cell + sense + math chain narrow enough to validate
end-to-end against an existing peer paper (BitROM, arXiv 2509.08542).

The headline reference point is **Microsoft `bitnet-b1.58-2B-4T`**
([HuggingFace](https://huggingface.co/microsoft/bitnet-b1.58-2B-4T),
[BitNet b1.58 paper, arXiv 2402.17764](https://arxiv.org/abs/2402.17764),
[BitNet b1.58 2B-4T tech report, arXiv 2504.12285](https://arxiv.org/pdf/2504.12285)).
Taalas's published 17 K tok/s on Llama-3.1-8B is **not** an
apples-to-apples comparison: Taalas runs at 3-bit precision with a
6-bit per-block scale, not at ternary. Ankhdjet's headline tok/s number
is benchmarked against BitROM (the closest open peer at ternary
precision), with the Taalas filing serving as production precedent for the
cell + array structural family only.

This document records the array + wrapper architecture compiled per
N×M ternary weight tensor, and the peripheral blocks the compiler
must produce alongside the cell array. Every architectural claim
below cites a primary source.

The read itself has two tiers. The primary readout is fully digital:
clocked precharge, then full-swing bitline sampling into
standard-cell capture registers, with all accumulation in synthesized
RTL (the digital readout design record carries the design and its
measured basis). An analog comparator readout (clocked
StrongARM-class sense against shared reference levels) exists as a
measured, characterization-gated variant within the 180-28 nm window.
Everything at and below the bitline (cells, mask programming,
precharge, wordlines, decoders) is shared by both tiers; sections
below that describe comparators, reference levels, TriMLA
accumulation, or replica timing describe the analog variant and are
marked as such.

The architecture is intentionally close to BitROM (the closest
published peer at ternary precision) and belongs to the same
structural family the Taalas filing (WO2025217724A1) describes at the
cell + array level; the design differs where the filing claims (see
the commercial-precedent section below). Where Taalas explicitly declines to
disclose post-sense details, the design picks the BitROM-aligned
default.

## The SKY130 implementations versus the production target

The sections below describe the production target architecture. Two
SKY130 chips implement it through full signoff on the same die
footprint, array placement, and read contract, one per readout tier:
`cirom_chip_digital` (full-swing bitline samplers, no comparators and
no reference pin; the flagship signoff) and `cirom_chip_analog`
(banded single-ended comparators with an external VREF pin; the
analog variant). Both close netgen LVS 0, clean STA, and the
functional regression; the results record carries the KLayout DRC
state of each (0 of record on the analog chip; two items of the
documented engine-artifact class on the digital chip against the
same engine's 17 on the signed-off analog GDS). The
implementations deviate from the production target in these ways,
shared items first, then the digital chip, then the analog variant:

- **One ternary weight per cell** (drain to BL+, BL−, or floating),
  W=0.42/L=0.17 at 1.70 × 1.30 µm pitch, 64 rows per bitline. BiROMA
  two-weights-per-cell is generated but NO-GO at this node (see the
  bitcell spec and the BiROMA design record); it stays a smaller-node,
  analog-variant technique.
- **Clocked precharge implemented** exactly as the precharge design
  doc specifies: one W=1.0 pfet per bitline (both polarities), gates
  on an active-low PRE_N from the read FSM, bitlines parked high when
  idle, no keeper.
- **FSM-timed strobe** (precharge → evaluate → strobe → hold states at
  25 ns), not replica-timed; the replica column belongs to the analog
  variant's production geometry. Sense outputs are captured into
  registers on the clock edge ending the strobe state.
- **Verification is per-level**: every hand-assembled structure
  (cell, precharge row, band, macro, chip) flat-extracts against its
  own generated schematic. This discipline caught silent shorts that
  no chip-level check sees (jog abutment, band nwell-over-nfet).
- **The digital chip reads at full swing**: each bitline lands on a
  standard-cell capture register strobed by the read FSM, and the
  accumulate path is synthesized RTL; no sense amplifier, reference
  subsystem, replica column, or offset statistics exist in that tier.
- **In the analog variant, sense is single-ended, per bitline**: each BL+ and BL− is sensed
  by its own clocked StrongARM-derived comparator against a shared
  analog VREF ≈ VDD/2 supplied on an external pin (the VREF design
  doc records the on-chip divider decision; the built analog chip
  uses the external pin): not the 8:1-muxed dual-reference TriMLA scheme.
  At production array geometry (256-row bitlines) the sense scheme is 8:1-muxed single-ended binary; TriMLA-style multi-level sensing is out of scope at SKY130 (its window is 65-16 nm and its BiROMA cell basis is NO-GO here); the
  single-ended scheme is what is validated in layout, extraction, and
  Monte Carlo. The StrongARM resets its outputs when the strobe
  falls, so unregistered comparator outputs are invalid by the time
  a valid flag pulses.
- **Implemented comparator input pair is W=8/L=2** (σ_offset ≈ ±50 mV
  budget, 250/250 Monte Carlo at the realistic signal), with a
  measured output-load-imbalance cliff: decisions flip when the
  routed HIT load exceeds ~150 fF against the internal complement
  node, so the HIT pins carry a 60 fF liberty limit and buffered
  routes.

## Top-level shape

In the digital tier (the readout of record), the `cirom_array` macro
carries the cell array, its column-shared BL+/BL− pair per output,
and the clocked precharge row; row decode and WL drive are
synthesized standard cells driving the macro's WL ports, each
bitline lands on a full-swing standard-cell capture register strobed
by the read FSM, and everything downstream of the captured bits
(accumulation, global summation, scale, quantize) is synthesized
RTL that ports to any node by synthesis. The sense margin is the full
logic swing, so no reference levels, replica timing, or offset
statistics exist in this tier.

In the analog variant at production geometry, each `cirom_array`
macro is a 256×256 cell array (65,536 ternary
weights) wrapped by a row decoder + WL driver bank, a column-shared
BL+/BL− pair per output, a precharge stage, 32 clocked StrongARM
sense-amp groups (one per 8 BLs), 32 TriMLA-style group accumulators,
a single global adder tree, a bit-slice shift-accumulator, and a
small state machine timed by a replica-bias dummy column. Downstream
of the macro, a shared per-tensor requantize scale multiplier
(16-bit Q8.8 as implemented) and a saturating quantize stage feed
the next layer's input register directly; no inter-layer SRAM stage
(the inter-layer fusion and the scale/quantize chain are common to
both tiers).

Storage: **one ternary weight per 1T cell**, the encoding both
signed-off chips carry. The BiROMA-style E/O-side bidirectional read
([BitROM Sec III-B1, arXiv 2509.08542](https://arxiv.org/html/2509.08542))
stores two weights per cell but requires resolving multiple levels
on one line, so it is an analog-variant option at nodes where the
sense margin refunds it: NO-GO at SKY130, and unavailable on the
digital readout at any node, per the BiROMA design record.

Activation precision: **a compile-time parameter K, read
bit-serially (K cycles per dot product)**. K=8 is the reference,
matching Microsoft's W1.58 + A8 checkpoint format
([BitNet b1.58 paper, arXiv 2402.17764](https://arxiv.org/abs/2402.17764),
[BitNet b1.58 2B-4T tech report, arXiv 2504.12285](https://arxiv.org/pdf/2504.12285))
and the bit-exact suite; K=4 is hardened on the Darga tile and
reported in the A4 estimates. A lower K is a co-design option that
requires a matching checkpoint, not a mode of the reference model.
Scale handling as implemented: BitNet's absmean per-tensor weight
scale folds into the static per-stage requantize scale (16-bit Q8.8
fixed point); the absmax per-token activation scale is
runtime-dynamic and lives in the activation path, never folded into
a static mask-time scale. Taalas's published number format (a 3-bit
base with 6-bit per-tile parameters,
[taalas.com; The path to ubiquitous AI](https://taalas.com/the-path-to-ubiquitous-ai/),
[Next Platform interview](https://www.nextplatform.com/compute/2026/02/19/taalas-etches-ai-models-onto-transistors-to-rocket-boost-inference/4092140),
[AI Central; Hardwired](https://aicentral.substack.com/p/hardwired))
is a commercial datapoint for aggressive quantized formats in this
family; no artifact here carries K=3 or a 6-bit per-tile scale.

Column tiling: **256 rows per sub-column at the production geometry**
(grouped 8 bitlines per sense amp in the analog variant, 32 groups
per array). Production mask-ROM at advanced nodes tiles at 128–256 rows
per BL ([Choi et al. A-SSCC 2016 1T ROM, IEEE 7482552](https://ieeexplore.ieee.org/document/7482552);
[Etron 40 nm 16-Mb mask ROM, JSSC 2015 IEEE 7161376](https://ieeexplore.ieee.org/document/7161376/)),
and BitROM uses 2,048 rows × 1,024 columns
([BitROM ASP-DAC 2026](https://www.aspdac.com/aspdac2026/archive/pdf/4B-1.pdf)),
implying ~256 rows per discharge group there too. Sense path closes at
sub-1 ns even at 16 nm.

Inter-layer fusion: **no SRAM stage between layers** (other than the
KV cache). The accumulator/scale/quantize chain feeds directly into
the next layer's input register. This is **novel; no published CiROM
architecture does this**, and it is a deliberate Ankhdjet choice for
density. TOM ([arXiv 2602.20662](https://arxiv.org/html/2602.20662))
buffers between layers in SRAM and power-gates per-layer; BitROM uses
a 6-stage pipeline within an array but does not fuse across arrays.

### Analog variant sense stack

Sense fan-in: **8 bit lines per sense amp + accumulator group**, matching
BitROM's TriMLA exactly ([BitROM Sec III-B2](https://arxiv.org/html/2509.08542)).
Mainstream open-source ROM compilers default to similar 4–16:1 fan-in
([OpenRAM source `compiler/modules/rom_column_mux.py`](https://github.com/VLSIDA/OpenRAM/blob/stable/compiler/modules/rom_column_mux.py),
[OpenRAM thesis (UCSC)](https://escholarship.org/content/qt2vv5q88z/qt2vv5q88z_noSplash_389063a5d89db05d7b42a63b528c7fc2.pdf)).

Sense amplifier: **clocked StrongARM-class** (fully
digital at the latch boundary). The Taalas filing says the readout *"may compare the
voltage on the read line ... to the pre-charge low value"* and
*"sense amplifiers may output the interpreted values to the designated
output lines"* ([WO2025217724A1 paragraphs 0046, 0053](https://patents.google.com/patent/WO2025217724A1/en)),
which is consistent with the same family of clocked sense amps
(the shared element is the clocked-sense family only; the compared
polarity is opposite, per the commercial-precedent section below).
[Choi et al.](https://ieeexplore.ieee.org/document/7482552) demonstrates
a low-swing edge sense at 0.55 ns / 0.85 V at 16 nm; the same topology
applies at 7 nm.

Sense margin: the SA does NOT resolve a per-cycle differential. It
fires once per K-cycle WL burst against a TriMLA-accumulated BL
voltage that has integrated the contributions of multiple cells.
After K cycles, the accumulated BL drop is several hundred mV (vs.
~14 mV per cell at N=128 cells per BL on SKY130). The accumulated
voltage is compared against two TriMLA reference levels (≈ 1/8 VDD
and 3/8 VDD).

Sense-amp sizing at SKY130 130 nm requires explicit attention.
Monte Carlo against `sky130_fd_pr__nfet_01v8__mismatch.corner` with
`mc_mm_switch=1` measures the bare W=2/L=0.3 StrongARM input pair
at σ_offset ≈ 130 mV at the SS corner; too high for any sub-VDD/4
reference comparison even with the end-of-accumulation signal margin.
Two production-silicon options close the gap; SKY130 picks the
oversized-input option for layout simplicity:

- **Oversized input pair** (implemented at SKY130 as W=8 / L=2 µm).
  Pelgrom scaling drops the input-referred offset to a ±50 mV
  budget; Monte Carlo on the implemented comparator passes 250/250
  at the realistic bitline signal. Tradeoff: ~133 fF of gate
  capacitance per input; large enough that the input pair, not the
  wire, dominates the bitline load, and that synchronous strobing of
  many comparators demands local decoupling on VREF (measured ≈3.5 pC
  of kickback for 64 comparators).
- **Auto-zero cap-coupled offset capture** (preferred at advanced
  nodes ≤28 nm). Adds ~6 switches + 2 memory caps per SA; cancels
  σ_offset by ≈10×; SA stays small. Better at nodes where σ_VTH
  per device is already small enough that the residual margin
  from auto-zero is < 5 mV.

Both topologies validate against the same MC test (≥99.9 % correct
at the target signal level on SS); at SKY130 we choose oversized
because it is layout-simpler and the overhead is acceptable at the built shape (comparators are ~7% of the signoff chip area; the muxed production path models a 10-12% sense tax).
The pick can flip at advanced nodes without changing anything
above the SA boundary.

Replica column: **one per array**, providing self-timed sense-strobe
across PVT corners. Standard for any production mask ROM
([OpenRAM architecture docs](https://github.com/VLSIDA/OpenRAM/blob/stable/docs/source/architecture.md)).
The digital tier strobes against a characterized worst-case discharge
instead, since a full-swing sample has no reference-crossing timing
to replicate.

## Why this architecture (silicon precedent)

Every advanced-node mask-ROM macro that has been published with
end-to-end characterization uses the same structural family:
column-shared bit lines, clocked sense amplifiers, replica timing,
column muxing, BL precharge, and a small per-group accumulator.

| Macro | Node | Topology | Source |
|---|---|---|---|
| TSMC 128-kb 1T ROM | 16 nm FinFET | 1T NMOS, column-shared BL, low-swing edge sense amp, 0.55 ns @ 0.85 V | [Choi et al., A-SSCC 2016 (IEEE 7482552)](https://ieeexplore.ieee.org/document/7482552) |
| TSMC 128-kb 1T ROM | sub-16 nm FinFET | 1T NMOS, column-shared BL, sense amp, 0.56 ns | [IEEE 7406972](https://ieeexplore.ieee.org/document/7406972/) |
| Etron 16-Mb mask ROM | 40 nm | Diode bitcell, contact-presence program, column-shared BL, sense amp per column | [Etron JSSC 2015 (IEEE 7161376)](https://ieeexplore.ieee.org/document/7161376/) |
| BitROM | 65 nm | 1T BiROMA cell (2 ternary weights per cell), DEQ + PRE/SUP, TriMLA per 8 BLs (8-bit accumulator + 2 reference comparators), single global adder tree, 6-stage pipeline | [BitROM, arXiv 2509.08542](https://arxiv.org/html/2509.08542); [ASP-DAC 2026](https://www.aspdac.com/aspdac2026/archive/pdf/4B-1.pdf); [BitROM GitHub](https://github.com/Wenlun-Zhang/BitROM) |
| ARM via-programmable ROM compiler | TSMC 40 nm CLN40G | 1T cell, via-1 program, column-shared BL, sense amp | [Arm CLN40G ROM compiler datasheet](https://www.chipestimate.com/Arm/Via-Programmable-ROM-Compiler-High-Density-TSMC-40nm-G-CLN40G/datasheet/ip/24120) |
| OpenRAM ROM compiler | SKY130 (open) | 1T-NAND bitcell, row decoder, WL driver, column mux (default tx_size=8), BL precharge, output inverter buffer | [OpenRAM `rom_*` source](https://github.com/VLSIDA/OpenRAM/tree/stable/compiler/modules); [OpenRAM thesis](https://escholarship.org/content/qt2vv5q88z/qt2vv5q88z_noSplash_389063a5d89db05d7b42a63b528c7fc2.pdf) |
| TinyTapeout SKY130 ROM experiments | SKY130 (open) | OpenRAM ROM compiler outputs, taped out | [TinyTapeout sky130-rom-experiments](https://github.com/TinyTapeout/sky130-rom-experiments) |

## Commercial precedent: the Taalas filing, and where this design differs

The [Taalas WO2025217724A1](https://patents.google.com/patent/WO2025217724A1/en)
filing ([WIPO mirror](https://patentscope.wipo.int/search/en/detail.jsf?docId=WO2025217724),
[Taalas press release](https://www.htsyndication.com/us-fed-news/article/international-patent:-taalas-inc.-files-application-for--mask-programmable-rom-using-shared-connections-/22214122607))
describes a mask-programmable ROM in the same structural family: a 1T
cell with the gate on a wordline and the drain via-customized at
back-end-of-line to one of multiple shared bitlines (¶0007), read by
sense amplifiers that compare the read line against a precharge-low
value and present the detected bit at their outputs (¶0046, ¶0053,
flow steps 406-408), with simultaneous read width scaling with
sense-amplifier count and column connectivity (¶0046), i.e. column
muxing by design. The disclosure deliberately stops at the
sense-amplifier output; Bajic publicly describes the post-sense
fabric as fully digital and explicitly declines to disclose it
([Next Platform](https://www.nextplatform.com/compute/2026/02/19/taalas-etches-ai-models-onto-transistors-to-rocket-boost-inference/4092140);
[EE Times](https://www.eetimes.com/taalas-specializes-to-extremes-for-extraordinary-token-speed/)).

The filing is cited here as commercial confirmation that the
mask-programmed 1T ROM family is production-viable, not as a source
of this design. The design differs where the filing claims:

- **The readout of record performs no comparison at all.** The
  filing's disclosed sense scheme is comparison-based (read line
  against a precharge-low value, ¶0053); Ankhdjet's primary readout
  is full-swing bitline sampling into standard-cell registers, with
  no sense amplifier, no reference, and no comparison. The filing's
  sense disclosure touches only the documented analog comparator
  variant, and that variant compares the opposite polarity
  (precharge-high against VDD/2).
- **One weight per cell, with no shared bit-terminal connections**
  (shared connections are the filing's claimed density mechanism,
  ¶0007).
- **The wrapper side follows BitROM**, the closest open-published
  peer, where the filing is silent.

## Required peripherals per array

The digital tier (the readout of record) is enumerated first; the
analog variant's sense stack follows as its secondary breakdown.

### Digital tier

As signed off, the hard macro carries the two custom-cell structures
(the cell array and the clocked precharge row gated by PRE_N); every
other peripheral is standard-cell RTL synthesized outside the macro,
so it ports to a new node by synthesis:

- **Row decode + WL drive**: one-hot decode of the row index plus
  buffering sized for the row's gate load, driving the macro's WL
  ports.
- **Per-bitline full-swing capture registers**: an input buffer and
  capture flop per BL+ and BL− (the readout; design and measured
  basis in the digital readout record).
- **Accumulate path**: per-column add/sub/skip over the row sweep
  with activation bit-slice weighting, then global summation and the
  bit-slice shift-accumulate.
- **Requantize scale multiplier**: the implemented between-layer
  chain's 16-bit Q8.8 per-tensor scale, shared across the stage's
  output channels.
- **Saturating quantize + bias adder**: quantizes the scaled sum to
  the next layer's activation precision.
- **Read FSM**: sequences precharge, evaluate, strobe, and hold per
  the macro contract and counts rows and bit-slices.

No reference levels, replica timing, or offset statistics exist in
this tier.

### Analog variant breakdown

The variant replaces the capture registers with a sense stack and
moves the array-adjacent periphery inside the hard macro. For each
`cirom_array_NxM` macro at the production geometry (256 × 256
reference, 65,536 ternary weights, 32 sense-amp groups of 8 BLs
each, K-bit-serial activation slicing):

1. **Row decoder**: 8→256 NAND/NOR tree per array. Standard cells.
2. **WL drivers**: per-row inverter chain sized to drive the row's
   gate-capacitance load within one cycle.
3. **BL precharge transistors**: one PMOS per BL gated by the global
   precharge strobe.
4. **Clocked StrongARM sense amplifier**: one per 8-BL group. Per
   [Choi et al. A-SSCC 2016](https://ieeexplore.ieee.org/document/7482552),
   low-swing edge sensing with capacitor-divider reference is feasible
   at 16 nm; the same topology applies at 7 nm.
5. **TriMLA-style group accumulator**: one per 8-BL group: 2 reference
   comparators (1/8 VDD, 3/8 VDD) + 8-bit signed shift-accumulator +
   8:1 column mux. Width validated by
   [BitROM Sec III-B3](https://arxiv.org/html/2509.08542): *"an 8-bit
   output width for TriMLA is sufficient to avoid overflow"*.
6. **Replica-bias / dummy column**: one per array, provides
   self-timed sense-strobe across PVT.
7. **Single global adder tree**: log-depth adder tree across all 32
   group outputs, 13-bit leaf width. Per
   [BitROM Sec III-B3](https://arxiv.org/html/2509.08542): *"a single
   adder tree across the entire array"*.
8. **Bit-slice shift-accumulator**: one per array, 16-bit signed,
   sums K bit-slices (K cycles; K=8 reference).
9. **Requantize scale multiplier**: the per-tensor 16-bit Q8.8 scale
   as implemented, shared across all output channels of the stage.
10. **Saturating quantize + bias adder**: quantizes the scaled sum
    to the next layer's activation precision (A8 reference) for its
    input register.
11. **State machine**: counts (`r_idx`, `k_idx`); generates
    `precharge`, `wl_strobe`, `sense_strobe`, `accumulate_strobe`.

Items 1–7 are the **per-array peripherals** wrapped inside the hard
macro (Liberty + LEF + GDS). Items 8–11 are
standard-cell-synthesizable RTL outside the macro. This boundary
matches the OpenRAM ROM compiler's macro/wrapper split
([OpenRAM rom_bank.py source](https://github.com/VLSIDA/OpenRAM/blob/stable/compiler/modules/rom_bank.py)).

OpenRAM ROM emits decoder + column mux + bitline inverter + output
inverter but **no sense amp and no accumulator** (confirmed by
source-read of `compiler/modules/rom_*.py`). Items 4, 5, 6, 7, 8 must
be added on top of an OpenRAM-style cell-array macro.

Beyond the array macro (either tier), the chip also needs:

- **Activation distribution / async-FIFO crossings** between clock
  domains.
- **Inter-layer epoch scheduler + tick fan-out** providing a global
  lockstep barrier per token.
- **KV-cache SRAM** sized for
  `n_layers × n_kv_heads × 2 × head_dim × kv_context × bytes_per_value`.
- **Attention engine**: fixed-function streaming pipeline of FP16
  multipliers + log-tree adder + softmax LUT, sized at compile time
  per `(head_dim, n_kv_heads, kv_context)`.
- **RoPE + RMSNorm + activation function blocks**: fixed-function
  digital, standard cells. RMSNorm is explicitly fused into the
  next-layer input quantization per Microsoft's `BitLinear` reference
  ([BitNet b1.58 paper, arXiv 2402.17764](https://arxiv.org/abs/2402.17764)).
- **Output sampler / detokenizer interface, top-level clock tree, reset,
  IO pads, ESD**: standard chip-level overhead.

## Per-cycle dataflow

For one input row `r` and one bit-slice `k` (K cycles per dot
product at K-bit activations; K=8 reference, K=4 as hardened on
Darga); steps 4-5 are stated for the digital tier first with the
analog variant's substitution inline (the accumulate math is the
same add/sub/skip either way):

1. **Cycle start.** State machine asserts `precharge` (BL+ and BL−
   both pulled to VDD).
2. **Row decode + WL pulse.** 8-bit `r_idx` decoded to one-hot 256-bit
   WL bus; selected WL driver fires, gates of all 256 cells in row `r`
   go high.
3. **BL evaluate.** Selected cell in each column discharges its drain
   net (BL+ if w=+1, BL− if w=−1, neither if w=0). 256 BLs settle to a
   small differential signal during the WL high half-cycle.
4. **Strobe capture.** Each bitline's full-swing state is captured
   into its register (a discharged line reads as a hit for its
   polarity). Analog variant: 32 clocked StrongARM sense amps fire
   (one per 8-BL group), latching `pos_hit`/`neg_hit` pairs from the
   TriMLA-accumulated BL voltage compared against the two reference
   levels.
5. **Accumulate.** Per-column add/sub/skip on the captured bits,
   weighted by activation bit `k`, in synthesized logic. Analog
   variant: 32 TriMLA group accumulators increment based on the
   2-reference-comparator decisions; an 8-bit signed accumulator
   suffices per BitROM.
6. **Repeat steps 1-5 for K bit-slices** (K cycles total).
7. **Global tree sum.** After K bit-slices, the per-column
   accumulators (digital tier) or the 32 group outputs (analog
   variant) feed the global adder tree. The 13-bit leaf width
   (BitROM's adopted width) covers the 256-cell per-slice worst case
   with sign and margin.
8. **Bit-slice shift-accumulate.** A per-array 16-bit signed register
   accumulates the tree output shifted by `k` for each bit-slice. After
   K cycles this register holds the full dot product.
9. **Scale.** The shared per-tensor Q8.8 requantize multiplier
   scales the sum.
10. **Bias + quantize.** Bias add (per-channel int8) and saturating
    quantize to the next layer's activation precision (A8 reference,
    A4 on Darga). RMSNorm is fused here per Microsoft `BitLinear`.
11. **Stream into next layer.** No SRAM stage; the requantized
    activation flows directly into the next layer's input register.
    This is Ankhdjet's chosen inter-layer fusion strategy.

## Density target

The verified SKY130 cell is **bitcell_v4** (one weight per cell,
W=0.42 / L=0.17, 1.70 × 1.30 µm pitch = 2.21 µm²/weight, 64 rows per
bitline; see the bitcell spec for the implemented numbers and
verification chain); this is the density basis both signed-off chips
carry. **bitcell_v4_biroma** (two weights per cell via
BiROMA bidirectional read, 0.325 µm² per stored weight at its
0.73 × 0.89 µm pre-rework pitch) is generated and regression-covered,
but the investigation closed NO-GO at SKY130 (break-even sense-line
pitch on one fork, driven-rail droop refunding the 2× on the other);
it remains the density option at smaller nodes, in the analog
variant only. The 0.668
µm²/cell array-scale figure belongs to that same pre-rework pitch and
is superseded by the as-built 2.21 µm²/weight.

At the BiROMA bound (2 ternary weights per 1T cell;
[BitROM Sec III-B1](https://arxiv.org/html/2509.08542)), a
representative 256×256 array gives:

- **Stored weights:** 65,536 ternary
- **Cell transistors:** 32,768 (= weights / 2): i.e. **0.5 cell-T per
  stored ternary weight** before any wrapper overhead.

Body tap is a separate tap cell row shared every 8 rows (generator
default) per the SKY130 latch-up rule.

The shape-agnostic macro generator + OpenROAD round-trip flow
validates 64×32 / 128×16 / 256×256 / 512×128 / 1024×64 / 512×256
macros at SKY130 and GF180MCU, in both standard and BiROMA encoding.
Earlier v2 (PCell + body tap) and v3 (W=0.84) cell variants are
superseded.

GF180 BL discharge timing is anchored to a direct ngspice
characterization against the volare-installed gf180mcuD nfet_03v3
BSIM4 model (W=1.16/L=0.28 µm scaled cell, 3.3 V VDD): SS @ N=128 =
1.916 ns vs SKY130's 1.535 ns; a measured **1.25× scale**, not the
1.5× initially assumed. The macro Liberty timing is updated from this
measurement.

The wrapper (the peripheral enumerations above) is the dominant
lever for total T-per-weight. The reference points anchoring the
wrapper budget are:

- [BitROM Sec III-B3](https://arxiv.org/html/2509.08542) reports
  *"TriMLAs, peripheral logic, and adder tree collectively occupy only
  4.8% of the total area"*; the peripheral area fraction we aim to
  approach as array sizes grow.
- Taalas's chip-level ratio (53 B transistors / 8 B parameters ≈ 6.6 T
  per parameter, [taalas.com](https://taalas.com/products/),
  [Next Platform](https://www.nextplatform.com/compute/2026/02/19/taalas-etches-ai-models-onto-transistors-to-rocket-boost-inference/4092140))
  is the chip-scale upper bound when KV SRAM, attention engine,
  RMSNorm, RoPE, scheduler, clock tree, IO pads, and ESD are added on
  top of the array macros.

Per-block transistor counts depend strongly on synthesis library, gate
sizing, and node, and are deliberately not enumerated here: this
document carries measured numbers only.

**Why this beats a naive design.** A naive emitter (one full 24-bit
shift-accumulator per output column with K=8) inflates the wrapper
roughly an order of magnitude over the architecture above. The
load-bearing differences (the first three are the analog variant's
production geometry; K-bit slicing, the shared scale multiplier, and
inter-layer fusion apply to both tiers) are:

- 2 ternary weights per 1T cell (BiROMA): 2× density on the cell side
  itself.
- 8-BL fan-in to one TriMLA group: 8× sharing of the per-group
  accumulator.
- 8-bit TriMLA width (BitROM's overflow-safe choice) vs 24-bit naive:
  3× width reduction.
- Bit-serial K-cycle activation slicing with K a compile-time
  parameter: cycle count scales with activation precision (a
  lower-precision co-designed checkpoint reads proportionally
  faster) without changing the transistor count.
- One shared per-tensor requantize scale multiplier across all
  output channels of the stage: replaces M independent multipliers.
- No inter-layer SRAM stage: removes a per-channel buffer's worth of
  wrapper area.

## Cell vs array boundary, Yosys integration

The single 1-NMOS cell is **not** a synthesizable standard cell that
Yosys/ABC will instantiate from RTL. Yosys does not understand
wired-OR or sense-amp readout; it only emits restoring CMOS gate
trees ([Yosys techmap docs](https://yosyshq.readthedocs.io/projects/yosys/en/latest/using_yosys/synthesis/techmap_synth.html);
[Yosys cell library docs](https://blog.eowyn.net/yosys/CHAPTER_CellLib.html)).

The cell is the **building block of an array hard macro**. The macro
has:

- A Liberty `.lib` characterizing input → digital output paths through
  the array boundary (timing arcs at the macro pins, not at the cell).
- A LEF `.lef` declaring the macro's footprint, perimeter ports, and
  obstruction map.
- A GDS containing every cell instance with its via-1 customization
  for the specific weight matrix, plus the periphery layout.

Yosys + OpenROAD see the array as an opaque hard macro. The array
becomes a `(* blackbox *)` module once the Liberty exists. In the
digital tier everything outside the array + precharge macro is
standard-cell-synthesized; in the analog variant only its
breakdown's items 8–11 (and the chip-level periphery) are.

### Per-PDK custom-cell requirement

The "node-agnostic" claim is honest at the RTL + compiler level: the
same Verilog wraps any PDK's standard-cell library, and the same
compiler emits the same gate-level netlist. But the macro itself
contains custom blocks that no standard-cell library has and that
must be hand-laid out per supported PDK. The digital tier needs
**two**; the analog variant adds two more:

| Block | Tier | Why it must be custom (not stdcell) |
|---|---|---|
| **Bitcell** | both | One transistor with three via candidates per drain (BL+/BL−/VGND_TIE), with custom diffusion sharing for density. Standard cells have minimum logic-gate footprints, ~50× larger than the optimal bitcell. |
| **Precharge transistors** | both | A row of PMOS pull-ups directly on the BL net, pitch-matched to the cell column. Stdcell PMOS won't fit. |
| **Sense amplifier (StrongARM)** | analog variant | 8-transistor analog comparator with sub-mV input-referred σ_offset target. Stdcell flip-flops have σ_offset ~10× too large; the digital tier needs none because it samples at full swing. |
| **Replica / dummy column** | analog variant | Mimics the active column's discharge timing for self-timed sense strobe; geometry must match the bitcell column's RC. The digital tier strobes against a characterized worst-case discharge instead. |

Everything else in the macro (row decoder, WL drivers, column mux,
the accumulate path in either tier, global adder tree, bit-slice
shift-accumulator, state machine, requantize scale multiplier,
saturating quantize) is synthesizable from the PDK's standard cells
via Yosys + OpenROAD with no per-node custom layout.

This asymmetry (compiler portable, silicon not) is the load-bearing
fab-time tax of an open-PDK CIM architecture. Closing it for any new
PDK is a discrete one-time cost, after which all of the macro's
abstract behavior (Liberty, LEF, OpenROAD round-trip, bit-exact
Python reference, area + throughput model) ports automatically.

## Open uncertainties and where this design invents

**Taalas public commercial statements noted but NOT adopted
(interviews and marketing, not the filing):**
- The 3-bit-base + 6-bit-per-tile number format (taalas.com, Next
  Platform, AI Central): a commercial datapoint for aggressive
  quantized formats in this family; no artifact carries it (the
  implemented stack is K-parameterized bit-serial activations, K=8
  reference / K=4 hardened on Darga, with a 16-bit Q8.8 per-tensor
  requantize scale).

**Independent choices whose production viability Taalas's disclosures
corroborate (the design differs where the filing claims, per the
commercial-precedent section above):**
- 1T NMOS via-1 programmed cell (the production mask-ROM family
  precedent above; corroborated by the filing + EE Times)
- Many bitlines per clocked sense amp via column muxing in the analog
  variant's production geometry (ARM and OpenRAM compilers;
  corroborated by filing ¶0046/0053); distinct from the filing's
  claimed cell-level shared bit-terminal connections, which Ankhdjet
  does not use
- Higher effective storage per cell transistor as a smaller-node
  direction (Bajic describes storing four effective bits and the
  multiply in a single transistor; the mechanism is undisclosed):
  the BiROMA 2-ternary-weights-per-cell encoding (BitROM) reaches
  toward this and is NO-GO at SKY130 per the BiROMA record

**Inventions over published prior art:**
- Inter-layer accumulator absorption: layer N's accumulate/scale/
  requantize chain feeds layer N+1's input register directly.
- Bit-streaming of the requantized output between layers, so no
  inter-layer SRAM stage exists (other than the KV cache).

**BitROM values adopted where Taalas is undisclosed (closest open
peer; these model the analog variant's production geometry, whereas
the signed-off SKY130 analog chip senses single-ended binary against
VDD/2 with no mux, and the digital chip samples at full swing):**
- 8-BL fan-in per sense amp + group accumulator
- 8-bit TriMLA width
- 2 reference comparators (1/8 VDD, 3/8 VDD) per group
- Single global adder tree per array
- 6-stage pipeline depth

**Open / paywalled / undisclosed:**
- ARM via-programmable ROM compiler exact column-mux ratio
  (datasheet login-walled; assumed 8:1 by analogy)
- Choi et al. A-SSCC 2016 internals not retrievable (IEEE paywall)
- Taalas 6-bit parameter scope (per-tile vs per-channel) is genuinely
  undisclosed (per-tile is the natural reading: per-channel × 8B
  params = too many scales, per-tensor × 6 bits = too coarse)
- Whether Taalas uses BitROM-style BiROMA encoding or some other
  4-bit-per-1T mechanism (Bajic explicitly declined to disclose)
- BitROM's 4,967 kB/mm² density at 65 nm is layout-extracted, not
  silicon-measured; treat as ±30%

## What this architecture commits to

1. **Single 1T NMOS cell** as the storage primitive, via-1 customized
   at fab time.
2. **Array is a hard macro**: generated per `(N, M, weights)` tuple
   via a layout pass that wraps cells with the clocked precharge row
   (the digital tier's macro as signed off) or with the analog
   breakdown's items 1–7.
3. **Liberty + LEF generation**: characterize the array macro via
   ngspice (corners TT/SS/FF, slew × load grid), emit Liberty;
   generate LEF abstract from the array bbox + perimeter ports.
4. **RTL black-boxing**: the array macro is a `(* blackbox *)`
   module to synthesis. The digital tier synthesizes everything
   outside the macro; the analog variant only its breakdown's items
   8–11 (and the chip-level periphery).
5. **Weight encoding per node**: one ternary weight per 1T cell at
   SKY130 (as signed off in both chips); BiROMA 2-weights-per-cell
   E/O encoding (BitROM convention) halves the cell transistor count
   and re-enters at smaller nodes where the sense margin refunds it,
   in the analog variant only (NO-GO at SKY130, and unavailable on
   the digital readout at any node, per the BiROMA design record).
6. **Via-programming pass**: a post-synth pass takes the layer's
   ternary weight matrix and emits the per-instance via-1 mask
   choices for the array macro's GDS.
7. **Readout is tier-parametric at the bitline boundary**: the
   digital sampler tier is the readout of record and the only tier
   below 28 nm; the analog comparator tier is a
   characterization-gated variant within its 180-28 nm window.
   Everything above the captured/latched bit is identical
   synthesized RTL in both tiers.

## Sources

- [BitROM, arXiv 2509.08542](https://arxiv.org/abs/2509.08542) /
  [BitROM HTML](https://arxiv.org/html/2509.08542) /
  [BitROM ASP-DAC 2026](https://www.aspdac.com/aspdac2026/archive/pdf/4B-1.pdf) /
  [BitROM GitHub](https://github.com/Wenlun-Zhang/BitROM)
- [TOM, arXiv 2602.20662](https://arxiv.org/html/2602.20662)
- [Taalas WO2025217724A1 (Google Patents)](https://patents.google.com/patent/WO2025217724A1/en) /
  [WIPO mirror](https://patentscope.wipo.int/search/en/detail.jsf?docId=WO2025217724) /
  [Taalas press release](https://www.htsyndication.com/us-fed-news/article/international-patent:-taalas-inc.-files-application-for--mask-programmable-rom-using-shared-connections-/22214122607)
- [Taalas; The path to ubiquitous AI](https://taalas.com/the-path-to-ubiquitous-ai/) /
  [Taalas products page](https://taalas.com/products/) /
  [EE Times Taalas interview](https://www.eetimes.com/taalas-specializes-to-extremes-for-extraordinary-token-speed/) /
  [Next Platform Taalas interview](https://www.nextplatform.com/compute/2026/02/19/taalas-etches-ai-models-onto-transistors-to-rocket-boost-inference/4092140) /
  [AI Central; Hardwired](https://aicentral.substack.com/p/hardwired) /
  [Datacenter Dynamics; Taalas HC1 unveil](https://www.datacenterdynamics.com/en/news/ai-chip-startup-taalas-raises-169m-unveils-hc1-processor-optimized-for-llama-31-8b/) /
  [CNX Software HC1 review](https://www.cnx-software.com/2026/02/22/taalas-hc1-hardwired-llama-3-1-8b-ai-accelerator-delivers-up-to-17000-tokens-s/) /
  [Medium HC1 deep dive](https://medium.com/@bmilew/a-look-at-taalas-hc1-chip-reaching-new-heights-in-llm-inference-56cd079f59a3)
- [Choi et al. A-SSCC 2016 16-nm 1T ROM (IEEE 7482552)](https://ieeexplore.ieee.org/document/7482552)
- [TSMC 128-kb 1T ROM 0.56-ns (IEEE 7406972)](https://ieeexplore.ieee.org/document/7406972/)
- [Etron 40-nm 16-Mb mask ROM JSSC 2015 (IEEE 7161376)](https://ieeexplore.ieee.org/document/7161376/)
- [DCiROM ASP-DAC 2025](https://dl.acm.org/doi/10.1145/3658617.3697585) /
  [DCiROM ResearchGate](https://www.researchgate.net/publication/393338930_DCiROM_A_High-Density_Fully-Digital_Compute-in-Read-Only-Memory_Macro_for_Energy-Efficient_Task-Level_DNN_Inference) /
  [DCiROM follow-on](https://www.researchgate.net/publication/389583114_DCiROM_A_Fully_Digital_Compute-in-ROM_Design_Approach_to_High_Energy_Efficiency_of_DNN_Inference_at_Task_Level)
- [ROM-SRAM hybrid CiM survey (Springer)](https://link.springer.com/article/10.1007/s11227-025-08080-2)
- [Arm via-programmable ROM compiler TSMC 40 nm CLN40G](https://www.chipestimate.com/Arm/Via-Programmable-ROM-Compiler-High-Density-TSMC-40nm-G-CLN40G/datasheet/ip/24120)
- [VLSIDA/OpenRAM](https://github.com/VLSIDA/OpenRAM) /
  [OpenRAM architecture docs](https://github.com/VLSIDA/OpenRAM/blob/stable/docs/source/architecture.md) /
  [OpenRAM `rom_*` source](https://github.com/VLSIDA/OpenRAM/tree/stable/compiler/modules) /
  [OpenRAM thesis](https://escholarship.org/content/qt2vv5q88z/qt2vv5q88z_noSplash_389063a5d89db05d7b42a63b528c7fc2.pdf)
- [TinyTapeout SKY130 ROM experiments](https://github.com/TinyTapeout/sky130-rom-experiments)
- [BitNet b1.58 paper, arXiv 2402.17764](https://arxiv.org/abs/2402.17764) /
  [BitNet b1.58 2B-4T tech report, arXiv 2504.12285](https://arxiv.org/pdf/2504.12285) /
  [microsoft/BitNet GitHub](https://github.com/microsoft/BitNet) /
  [bitnet.cpp paper, arXiv 2502.11880](https://arxiv.org/abs/2502.11880) /
  [Microsoft bitnet-b1.58-2B-4T (HuggingFace)](https://huggingface.co/microsoft/bitnet-b1.58-2B-4T)
- [TSMC 7 nm overview](https://www.tsmc.com/english/dedicatedFoundry/technology/logic/l_7nm)
- [Yosys techmap docs](https://yosyshq.readthedocs.io/projects/yosys/en/latest/using_yosys/synthesis/techmap_synth.html) /
  [Yosys cell library docs](https://blog.eowyn.net/yosys/CHAPTER_CellLib.html)
