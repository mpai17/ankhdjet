"""First-principles sizing for Ankhdjet's hardwired streaming attention engine.

Architecture: a fixed dataflow pipeline, NOT a systolic array, NOT a
programmable GPU lane. For each layer, the engine streams Q, K, V from
the on-die KV SRAM through a known-pattern address generator into a
parallel FP16 multiplier array, log-tree adders, and a softmax LUT.
Nothing is mask-programmable here (Q/K/V are activations); the engine
is sized at compile time to match the workload + matmul throughput.

Sizing rule: the attention engine should be exactly large enough to NOT
bottleneck the matmul pipeline. Larger wastes silicon (matmul is the
bottleneck); smaller bottlenecks the entire forward pass.

  per_layer_attention_macs = 2 * head_dim * n_heads * kv_context
                             (Q*K^T scan + A*V scan)
  required_parallel_mul    = ceil(per_layer_attention_macs / T_matmul)

Then per-layer attention cycles = T_matmul by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

# Per-multiplier gate count. A standalone FP16 multiplier-accumulator
# (mantissa mul + exponent add + rounding) synthesizes at ~1500-2500
# NAND2-equivalents on advanced nodes (synth runs of standalone FP16
# multipliers at sky130hd land in this range). Use 2000 as the
# defensible mid; bracket via {1500, 2500} for sensitivity.
FP16_MUL_GATES = 2000

# Routing + register-file overhead per multiplier in a streaming pipeline.
# This is much smaller than a programmable lane (no instruction stream,
# no register renaming, no cache hierarchy) but larger than the bare
# multiplier (need accumulators + KV-address-gen plumbing).
PIPELINE_OVERHEAD = 1.4

# Softmax LUT size, in NAND2-equivalent gates. Implements
# exp via piecewise-linear LUT + reciprocal for normalization.
SOFTMAX_LUT_GATES = 1500

# Per-element accumulator + control register cost.
ACCUMULATOR_GATES_PER_LANE = 50


@dataclass
class AttentionEngineSizing:
    parallel_mul: int               # parallel FP16 multipliers in the pipeline
    cycles_per_layer_per_token: int # equals T_matmul by sizing
    area_um2: float                 # multiplier array + softmax LUT + accumulators


def size_attention(
    head_dim: int,
    n_heads: int,
    kv_context_tokens: int,
    t_matmul_cycles: int,
    gate_um2: float,
    fp16_mul_gates: int = FP16_MUL_GATES,
    pipeline_overhead: float = PIPELINE_OVERHEAD,
) -> AttentionEngineSizing:
    """Compute the first-principles smallest attention engine that doesn't
    bottleneck the matmul pipeline.

    `t_matmul_cycles` is the per-layer matmul cycle budget (the layer's
    contribution to T_epoch in pipelined mode). The attention engine is
    sized so its per-layer cycle cost equals `t_matmul_cycles`.

    Returns the chosen `parallel_mul` count, the matched per-layer cycle
    count, and the engine area at the requested gate density.
    """
    if t_matmul_cycles <= 0:
        # Degenerate; fall back to one multiplier per head.
        parallel_mul = max(1, n_heads)
    else:
        per_layer_macs = 2 * head_dim * n_heads * max(1, kv_context_tokens)
        parallel_mul = max(1, -(-per_layer_macs // t_matmul_cycles))

    mul_array_gates = parallel_mul * fp16_mul_gates * pipeline_overhead
    accumulator_gates = parallel_mul * ACCUMULATOR_GATES_PER_LANE
    softmax_gates = SOFTMAX_LUT_GATES
    total_gates = mul_array_gates + accumulator_gates + softmax_gates
    area_um2 = total_gates * gate_um2

    return AttentionEngineSizing(
        parallel_mul=parallel_mul,
        cycles_per_layer_per_token=t_matmul_cycles,
        area_um2=area_um2,
    )
