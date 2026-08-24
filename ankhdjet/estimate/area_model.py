"""Area, power, and throughput estimator for a compiled Ankhdjet pipeline.

Given a ModelIR + PipelineConfig + PDK descriptor YAML, produce a block-
level area report and a throughput estimate. Numbers are first-order:
they assume balanced synthesis and the per-gate / per-bit densities
given in the PDK yaml, whose values carry the per-PDK synthesis-anchor
calibration; the throughput knobs are bracketed separately by
throughput_calibration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ankhdjet.backend.verilog import PipelineConfig, _column_widths
from ankhdjet.frontend.ir import ModelIR, QuantScheme


@dataclass
class PDK:
    name: str
    process_nm: float
    node_scale: float
    bitcell_um2: float
    gate_equivalent_um2: float
    transistors_per_gate: int
    popcount_gates_per_row: int
    between_layer_gates_per_channel: int
    serializer_gates_per_row: int
    sram_um2_per_bit: float
    array_overhead_frac: float
    die_routing_overhead_frac: float
    clock_mhz: float
    vdd_v: float
    synth_calibration: float = 1.0       # multiplier on per-gate area
    # Clock-tree skew derating: effective_fmax = clock_mhz / (1 + alpha*sqrt(area)).
    # alpha=0 means the YAML clock is taken as-is. The relevant area for
    # the sqrt is the synchronous DOMAIN area, not the full die — see
    # clock_domain_area_mm2 below.
    clock_skew_alpha: float = 0.0
    # Cycles added to T_epoch per inter-layer activation transition. Real
    # activation buses crossing mm of silicon need register-to-register
    # pipelining; the synth-ideal model treats hops as combinational.
    wire_hop_cycles: int = 0
    # Cycles added per layer per token for KV-cache SRAM access (read prior
    # K/V, write current). The pipelined epoch can hide some of this in
    # parallel with compute, but the KV macros at large context length are
    # the bottleneck — modeled here as a fixed per-layer cost added to T_epoch.
    kv_access_cycles_per_layer: int = 0
    # Multi-clock-domain partitioning. Production silicon at >100 mm^2 always
    # uses hierarchical clocking: 5-30 mm^2 synchronous "tiles" connected by
    # async/mesochronous crossings. We treat the die as ceil(die_area /
    # clock_domain_area_mm2) domains. Setting this to 0 falls back to the
    # die-wide single-domain assumption (sqrt(die_area)) for backward
    # compatibility with smaller dies. Calibrated defaults (per geometric
    # mean of H100 GPCs / MI300 XCDs / Tensix tiles / Cerebras cores):
    #   advanced nodes (28nm+): 16-20 mm^2
    #   mature nodes:           25-36 mm^2
    clock_domain_area_mm2: float = 0.0
    # Cycles added per token per inter-domain crossing in a serial pipeline.
    # 2-flop async-FIFO synchronizer + push/pop ~= 3 cycles per direction.
    # Setting to 0 disables the crossing penalty.
    crossing_cycles_per_hop: int = 0

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PDK":
        d = yaml.safe_load(Path(path).read_text())
        return cls(**d)

    @classmethod
    def all_from_yaml(cls, path: str | Path) -> list["PDK"]:
        """Load a YAML file containing a list of PDK descriptors."""
        items = yaml.safe_load(Path(path).read_text())
        return [cls(**d) for d in items]


@dataclass
class LayerAreaReport:
    name: str
    input_dim: int
    output_dim: int
    cells_um2: float
    popcount_um2: float
    array_overhead_um2: float
    total_um2: float
    active_cells: int
    total_positions: int

    @property
    def cell_density_mbits_per_mm2(self) -> float:
        if self.total_um2 <= 0:
            return 0.0
        return (self.total_positions * 2 / 1e6) / (self.total_um2 / 1e6)  # 2 bits per ternary


@dataclass
class BetweenLayerReport:
    index: int
    channels: int
    requantize_um2: float
    serializer_um2: float
    total_um2: float


@dataclass
class PipelineAreaReport:
    pdk_name: str
    layer_reports: list[LayerAreaReport] = field(default_factory=list)
    between_reports: list[BetweenLayerReport] = field(default_factory=list)
    kv_cache_um2: float = 0.0
    attention_um2: float = 0.0
    cells_subtotal_um2: float = 0.0
    peripherals_subtotal_um2: float = 0.0
    die_overhead_um2: float = 0.0
    total_um2: float = 0.0
    clock_mhz: float = 0.0          # ideal target fmax from PDK
    cycles_per_token: int = 0
    clock_skew_alpha: float = 0.0   # area-dependent fmax derating
    clock_domain_area_mm2: float = 0.0  # 0 = single-domain; else tile area for sqrt
    off_fabric_params: int = 0      # params excluded from the ternary fabric
    off_fabric_layers: tuple = ()   # their names (e.g. a bf16-tied lm_head)

    @property
    def total_mm2(self) -> float:
        return self.total_um2 / 1_000_000.0

    @property
    def cirom_fraction(self) -> float:
        return self.cells_subtotal_um2 / self.total_um2 if self.total_um2 else 0.0

    @property
    def n_clock_domains(self) -> int:
        if self.clock_domain_area_mm2 <= 0.0:
            return 1
        return max(1, math.ceil(self.total_mm2 / self.clock_domain_area_mm2))

    @property
    def effective_clock_mhz(self) -> float:
        # Multi-domain mode: clock_mhz IS the production-validated per-tile
        # fmax for this node (e.g. 1.5 GHz for 7nm, matching H100/MI300/
        # Wormhole tile clocks). The OpenROAD-derived alpha is dominated by
        # sub-mm^2 design-target effects, not actual skew, so we don't apply
        # it at tile scale.
        if self.clock_domain_area_mm2 > 0.0:
            return self.clock_mhz
        # Single-domain (small SKY130 demo) mode: apply the calibrated skew
        # derating against the full die area.
        if self.clock_skew_alpha <= 0.0:
            return self.clock_mhz
        return self.clock_mhz / (1.0 + self.clock_skew_alpha * math.sqrt(self.total_mm2))

    @property
    def tokens_per_second(self) -> float:
        if self.cycles_per_token <= 0:
            return 0.0
        return self.effective_clock_mhz * 1e6 / self.cycles_per_token

    def summary(self) -> str:
        lines = [f"=== Ankhdjet pipeline area report :: {self.pdk_name} ==="]
        lines.append(f"Total area       : {self.total_mm2:10.3f} mm^2")
        lines.append(f"  CiROM cells    : {self.cells_subtotal_um2 / 1e6:10.3f} mm^2 "
                     f"({self.cirom_fraction*100:.1f}%)")
        lines.append(f"  Peripherals    : {self.peripherals_subtotal_um2 / 1e6:10.3f} mm^2 "
                     f"({self.peripherals_subtotal_um2 / self.total_um2 * 100:.1f}%)")
        lines.append(f"  KV cache SRAM  : {self.kv_cache_um2 / 1e6:10.3f} mm^2 "
                     f"({self.kv_cache_um2 / self.total_um2 * 100:.1f}%)")
        lines.append(f"  Attention eng. : {self.attention_um2 / 1e6:10.3f} mm^2 "
                     f"({self.attention_um2 / self.total_um2 * 100:.1f}%)")
        lines.append(f"  Die overhead   : {self.die_overhead_um2 / 1e6:10.3f} mm^2 "
                     f"({self.die_overhead_um2 / self.total_um2 * 100:.1f}%)")
        if self.off_fabric_params:
            lines.append(
                f"  Off-fabric     : {self.off_fabric_params/1e6:10.1f} M params "
                f"({', '.join(self.off_fabric_layers)}; not ternary, "
                f"excluded from the hardwired die)")
        lines.append("")
        eff = self.effective_clock_mhz
        if eff < self.clock_mhz - 1.0:
            domain_note = (
                f", {self.n_clock_domains} domains x {self.clock_domain_area_mm2:.0f} mm^2"
                if self.clock_domain_area_mm2 > 0 else ", die-wide single domain"
            )
            lines.append(
                f"Clock            : {eff:.0f} MHz effective "
                f"(ideal {self.clock_mhz:.0f} MHz{domain_note})"
            )
        else:
            lines.append(f"Clock            : {self.clock_mhz:.0f} MHz")
        lines.append(f"Cycles / token   : {self.cycles_per_token}")
        lines.append(f"Throughput       : {self.tokens_per_second:,.0f} tokens/s")
        lines.append("")
        lines.append("Per-layer breakdown:")
        lines.append(f"  {'name':<10} {'N':>6} {'M':>6} {'cells mm2':>12} "
                     f"{'periph mm2':>12} {'total mm2':>12}")
        for lr in self.layer_reports:
            periph_um2 = (lr.popcount_um2 + lr.array_overhead_um2)
            lines.append(
                f"  {lr.name:<10} {lr.input_dim:>6} {lr.output_dim:>6} "
                f"{lr.cells_um2/1e6:>12.4f} {periph_um2/1e6:>12.4f} "
                f"{lr.total_um2/1e6:>12.4f}"
            )
        if self.between_reports:
            lines.append("")
            lines.append("Between-layer blocks:")
            for br in self.between_reports:
                lines.append(
                    f"  bl{br.index}  M={br.channels:<4} "
                    f"req={br.requantize_um2/1e6:.4f} mm^2  "
                    f"ser={br.serializer_um2/1e6:.4f} mm^2  "
                    f"total={br.total_um2/1e6:.4f} mm^2"
                )
        return "\n".join(lines)


# FP16 multiplier gate count, NAND2-equivalents. Synthesizing a generic
# 16x16 FP16 mantissa-multiplier + sign/exp logic on sky130hd/asap7
# typically lands in 1500-2500 gates depending on tree/layout choices.
# Use 2000 as a defensible mid-point; user can override per-PDK in YAML.
FP16_MUL_GATES_DEFAULT = 2000


def attention_lanes_from_area(pdk: PDK, area_mm2: float,
                                fp16_mul_gates: int = FP16_MUL_GATES_DEFAULT,
                                packing_overhead: float = 1.4) -> int:
    """How many parallel FP16 multipliers fit in `area_mm2` of `pdk` silicon?

    lanes = floor(area_um2 / (gates_per_mul * gate_um2 * packing_overhead))

    `packing_overhead` accounts for routing channels, register files, and
    softmax LUT around the multiplier array (~40% beyond raw mul logic).
    """
    if area_mm2 <= 0 or pdk.gate_equivalent_um2 <= 0:
        return 0
    area_um2 = area_mm2 * 1_000_000.0
    per_lane_um2 = fp16_mul_gates * pdk.gate_equivalent_um2 * packing_overhead
    return max(1, int(area_um2 / per_lane_um2))


def estimate_layer(
    layer, pdk: PDK, tile_cols: int = 1,
    bit_parallel: bool = False, k_bits: int = 8,
    nor_array: bool = True, subcol_rows: int = 64,
    biroma: bool = False, readout: str = "analog",
) -> LayerAreaReport:
    """Area for one compiled cirom_column array.

    Args:
        tile_cols: how many output columns share a single popcount tree.
            Only meaningful for the legacy parallel-WL architecture
            (nor_array=False), which 1T cells cannot implement; the
            default models the NOR array.
        subcol_rows: rows per bitline (64 = as-built arrays; 256 is the
            production-path geometry, a config choice).
        biroma: if True, model BiROMA 2-weights-per-1T-cell encoding
            (BitROM Sec III-B1). Halves the cell-array area term; the
            wrapper area is unchanged. Viable only in the 28-65 nm
            window (NO-GO at 130 nm); the tools gate it there. Compiler
            reference: ankhdjet/reference_biroma.ternary_matmul_biroma.
        readout: NOR-array readout tier. "analog" = per-sub-column
            clocked StrongARM comparator pairs (the analog tier;
            matches the published SKY130 anchors). "digital" = clocked
            full-swing bitline samplers (capture flop + input buffer;
            the default tier), anchored to the measured
            sampler32 synthesis: 1,081 um^2 / 32 bitlines / 5.0 um^2
            per gate = ~6.8 gate equivalents per bitline at SKY130.
    """
    W = layer.weights["weight"]
    if W.scheme != QuantScheme.TERNARY:
        raise ValueError(f"area model only supports ternary (got {W.scheme})")

    n = layer.input_dim
    m = layer.output_dim

    # NOR-array family counting convention (precedent: WO2025217724A1, BitROM): a transistor
    # is laid out at EVERY position; zero weights customize via-1 to
    # leave the drain floating, but the transistor footprint is still
    # there for layout regularity. So cell area scales with N*M, not
    # with nonzero count. Sparsity savings come from via mask cost, not
    # cell count.
    n_cells = (n * m + 1) // 2 if biroma else n * m
    cells_um2 = n_cells * pdk.bitcell_um2

    # Two popcount trees per TILE group of `tile_cols` columns.
    # Shared tree architecture = fewer trees but each column still needs its own accumulator.
    # Gates per row scale as O(log2(N)) because upper tree ranks are wider:
    #   g(N) = popcount_gates_per_row * log2(N+1) / log2(17)
    # (normalized so popcount_gates_per_row is the value at N=16).
    num_tiles = max(1, (m + tile_cols - 1) // tile_cols)
    log_factor = math.log2(n + 1) / math.log2(17)
    gates_per_row_n = pdk.popcount_gates_per_row * log_factor
    popcount_gates_per_tile = 2 * gates_per_row_n * n
    popcount_gates_total = num_tiles * popcount_gates_per_tile

    _, wacc = _column_widths(n, k_bits)
    acc_gates_per_col = 40 * wacc   # flops + adder for MAC accumulator
    acc_gates_total = m * acc_gates_per_col

    # Bit-parallel: K-wide AND gates per row produce K partial sums in
    # parallel, multiplying popcount tree width (and hence area) by K.
    if bit_parallel:
        popcount_gates_total *= k_bits
        acc_gates_total *= k_bits

    if nor_array:
        # NOR-array peripheral, per readout tier. Both tiers share the
        # row decoder, precharge drivers, and per-column accumulator;
        # they differ in what sits on the bitline pair:
        #   analog:  clocked StrongARM comparator pair (~80 gates each,
        #            gate-equivalent proxy for the custom sense band)
        #   digital: full-swing sampler per bitline (capture flop +
        #            input buffer, ~6.8 gates measured: sampler32
        #            synthesis 1,081 um^2 for 32 bitlines at SKY130)
        # No popcount tree (per-cell digital outputs aren't feasible at 1T).
        if readout not in ("analog", "digital"):
            raise ValueError(f"unknown readout tier {readout!r}")
        n_sub = max(1, (n + subcol_rows - 1) // subcol_rows)
        if readout == "digital":
            bitline_gates_per_subcol = 6.8 * 2   # one sampler per BL+/BL-
        else:
            bitline_gates_per_subcol = 80 * 2    # one comparator per BL+/BL-
        decoder_gates_per_subcol = max(1, math.ceil(math.log2(subcol_rows + 1))) * 4
        precharge_gates_per_subcol = 10
        per_col_periph_gates = (
            n_sub * (bitline_gates_per_subcol + decoder_gates_per_subcol
                      + precharge_gates_per_subcol) + acc_gates_per_col
        )
        popcount_um2 = (
            m * per_col_periph_gates * pdk.gate_equivalent_um2 * pdk.synth_calibration
        )
    else:
        popcount_um2 = (
            (popcount_gates_total + acc_gates_total)
            * pdk.gate_equivalent_um2 * pdk.synth_calibration
        )

    array_overhead_um2 = (cells_um2 + popcount_um2) * pdk.array_overhead_frac
    total_um2 = cells_um2 + popcount_um2 + array_overhead_um2

    return LayerAreaReport(
        name=layer.name,
        input_dim=n,
        output_dim=m,
        cells_um2=cells_um2,
        popcount_um2=popcount_um2,
        array_overhead_um2=array_overhead_um2,
        total_um2=total_um2,
        active_cells=int(W.num_nonzero),
        total_positions=n * m,
    )


def estimate_between(
    idx: int, channels: int, pdk: PDK, include_serializer: bool = True,
) -> BetweenLayerReport:
    """Per-between-layer area. In tiled mode, the serializer is unnecessary
    (between_layer output feeds the next layer's parallel act_flat input
    directly). In per-column mode, the serializer is needed to convert the
    parallel K-bit activations back to a bit-serial stream for the next
    layer's wl input."""
    req_gates = channels * pdk.between_layer_gates_per_channel
    req_um2 = req_gates * pdk.gate_equivalent_um2 * pdk.synth_calibration

    ser_um2 = 0.0
    if include_serializer:
        ser_gates = channels * pdk.serializer_gates_per_row
        ser_um2 = ser_gates * pdk.gate_equivalent_um2 * pdk.synth_calibration

    return BetweenLayerReport(
        index=idx, channels=channels,
        requantize_um2=req_um2,
        serializer_um2=ser_um2,
        total_um2=req_um2 + ser_um2,
    )


def estimate_pipeline(
    model: ModelIR,
    cfg: PipelineConfig,
    pdk: PDK,
    kv_context_tokens: int = 0,
    kv_bytes_per_token: int = 0,
    tile_cols: int = 1,
    pipelined: bool = False,
    head_dim: int = 0,
    n_heads: int = 0,
    n_transformer_blocks: int = 0,
    biroma: bool = False,
    off_fabric_layers: tuple[str, ...] = (),
) -> PipelineAreaReport:
    """Full pipeline area breakdown.

    Args:
        tile_cols: columns sharing one popcount tree (1 = per-column trees,
            current RTL; larger = BitROM-style shared trees at cost of
            sequential column evaluation).
        pipelined: if True, use inter-layer pipelining (lockstep epoch
            scheduler). Steady-state throughput is set by the slowest single
            layer rather than the sum of all layers. Adds per-layer acc
            registers (~WACC*M flops per layer) to the area.
        biroma: if True, model BiROMA 2-weights-per-1T-cell encoding
            (halves cell-array area; wrapper unchanged).
        off_fabric_layers: layer names excluded from the mask-programmed
            ternary accounting (cells, periphery, cycles) because they are
            not ternary in the checkpoint - e.g. a bf16-tied lm_head. Their
            parameter counts are recorded separately in the report, matching
            the compiler emitter's skip_layers so the two agree on what is
            actually hardwired.
    """
    fabric_layers = [l for l in model.layers if l.name not in off_fabric_layers]
    off_fabric_params = sum(
        l.input_dim * l.output_dim
        for l in model.layers if l.name in off_fabric_layers
    )
    layer_reports = [estimate_layer(
        l, pdk, tile_cols=tile_cols,
        bit_parallel=cfg.bit_parallel, k_bits=cfg.k_bits,
        nor_array=getattr(cfg, "nor_array", True),
        subcol_rows=getattr(cfg, "subcol_rows", 64),
        biroma=biroma,
        readout=getattr(cfg, "readout", "analog"),
    ) for l in fabric_layers]
    include_ser = (tile_cols == 1)  # serializer only needed in per-column mode
    between_reports = [
        estimate_between(i, fabric_layers[i].output_dim, pdk,
                         include_serializer=include_ser)
        for i in range(len(fabric_layers) - 1)
    ]

    cells_total = sum(lr.cells_um2 for lr in layer_reports)
    layer_periph = sum(
        lr.popcount_um2 + lr.array_overhead_um2 for lr in layer_reports
    )
    between_total = sum(br.total_um2 for br in between_reports)
    periph_total = layer_periph + between_total

    pipeline_reg_um2 = 0.0
    if pipelined:
        # One acc_reg per layer (WACC * M flops, ~8 gates/flop) holds the
        # signed accumulator stable across the epoch so the combinational
        # between_layer can drive a clean activation into the next stage.
        flops_per_gate = 8.0
        for l, lr in zip(fabric_layers, layer_reports):
            _, wacc = _column_widths(l.input_dim, cfg.k_bits)
            flops = wacc * l.output_dim
            pipeline_reg_um2 += (
                flops * flops_per_gate * pdk.gate_equivalent_um2
                * pdk.synth_calibration
            )
        periph_total += pipeline_reg_um2

    # Per-layer compute window depends on the architecture:
    # - NOR-array (default, 1T/cell, row-sequential): T = K * min(N, SUBCOL_ROWS)
    #   per layer when all sub-columns sense in parallel. This is the only
    #   architecture compatible with mask-programmed 1T cells.
    # - Legacy parallel-WL (cirom_tile.sv): T = K * min(M, tile_cols).
    #   Cannot be implemented with 1T cells; kept for reference/back-compat.
    L = len(fabric_layers)
    serial_factor = 1 if cfg.bit_parallel else cfg.k_bits
    per_layer = []
    if getattr(cfg, "nor_array", False):
        sub = max(1, cfg.subcol_rows)
        for l in fabric_layers:
            n_rows = max(1, l.input_dim)
            per_layer.append(serial_factor * min(n_rows, sub))
    else:
        for l in fabric_layers:
            cols_per_tile = min(l.output_dim, tile_cols) if tile_cols > 0 else l.output_dim
            per_layer.append(serial_factor * cols_per_tile)

    # First-principles attention engine sizing (depends on per_layer above).
    from ankhdjet.estimate.attention_engine import size_attention
    if head_dim > 0 and n_heads > 0 and kv_context_tokens > 0:
        t_matmul = max(per_layer) if pipelined else (sum(per_layer) // max(1, L))
        attn_engine = size_attention(
            head_dim=head_dim, n_heads=n_heads,
            kv_context_tokens=kv_context_tokens,
            t_matmul_cycles=t_matmul,
            gate_um2=pdk.gate_equivalent_um2 * pdk.synth_calibration,
        )
        attn_per_stage = attn_engine.cycles_per_layer_per_token
    else:
        attn_engine = None
        attn_per_stage = 0
    attn_total_seq = attn_per_stage * L

    kv_bits = kv_context_tokens * kv_bytes_per_token * 8
    kv_um2 = kv_bits * pdk.sram_um2_per_bit

    attention_um2 = float(attn_engine.area_um2) if attn_engine is not None else 0.0

    inner = cells_total + periph_total + kv_um2 + attention_um2
    die_overhead = inner * pdk.die_routing_overhead_frac
    total = inner + die_overhead

    # Long-wire pipelining: each inter-layer activation hop adds register-
    # to-register cycles that the synth-ideal model does not capture.
    wire_total_seq = pdk.wire_hop_cycles * (L - 1)
    wire_per_stage = pdk.wire_hop_cycles

    # KV-cache access cycles per layer per token.
    kv_total_seq = pdk.kv_access_cycles_per_layer * L
    kv_per_stage = pdk.kv_access_cycles_per_layer

    if pipelined:
        cycles_per_token = max(per_layer) + 2 + wire_per_stage + kv_per_stage + attn_per_stage
    else:
        cycles_per_token = sum(per_layer) + 2 * (L - 1) + wire_total_seq + kv_total_seq + attn_total_seq

    # Multi-domain partitioning derived from per-layer tile area. The
    # natural synchronous island in our architecture is one tile (cells
    # + popcount tree + accumulators) of one layer; per-tile area is
    # roughly mean(layer_total) / num_tiles_per_layer. Crossings between
    # adjacent layer tiles pay crossing_cycles_per_hop async-FIFO cycles.
    # PDK YAML's clock_domain_area_mm2, if non-zero, overrides the
    # derivation (kept for backward-compat experimentation).
    if pdk.clock_domain_area_mm2 > 0.0:
        derived_domain_um2 = pdk.clock_domain_area_mm2 * 1_000_000.0
    elif n_transformer_blocks > 0:
        # One synchronous domain per transformer block. Real silicon
        # clusters all sub-projections (q/k/v/o + ffn) of a block into
        # one clock domain and crosses async only at block boundaries.
        derived_domain_um2 = total / n_transformer_blocks
    else:
        # Fallback: one domain per IR layer entry.
        per_layer_um2 = [lr.total_um2 for lr in layer_reports]
        derived_domain_um2 = (sum(per_layer_um2) / max(1, len(per_layer_um2))
                              if per_layer_um2 else 0.0)

    if derived_domain_um2 > 0:
        n_domains = max(1, math.ceil(total / derived_domain_um2))
        cycles_per_token += (n_domains - 1) * pdk.crossing_cycles_per_hop
    derived_domain_mm2 = derived_domain_um2 / 1_000_000.0

    return PipelineAreaReport(
        pdk_name=pdk.name,
        layer_reports=layer_reports,
        between_reports=between_reports,
        kv_cache_um2=kv_um2,
        attention_um2=attention_um2,
        cells_subtotal_um2=cells_total,
        peripherals_subtotal_um2=periph_total,
        die_overhead_um2=die_overhead,
        total_um2=total,
        clock_mhz=pdk.clock_mhz,
        cycles_per_token=cycles_per_token,
        clock_skew_alpha=pdk.clock_skew_alpha,
        clock_domain_area_mm2=(pdk.clock_domain_area_mm2
                               if pdk.clock_domain_area_mm2 > 0
                               else derived_domain_mm2),
        off_fabric_params=off_fabric_params,
        off_fabric_layers=tuple(off_fabric_layers),
    )
