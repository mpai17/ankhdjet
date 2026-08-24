"""Find the largest BitNet-class transformer that fits a given die area
under the compiler's area model.

For each candidate config (varying hidden dim at fixed depth/heads), try
a range of tile_cols values, pick the one that fits and maximizes
throughput. Output is a table of (die_budget, best_model, best_tile_cols,
throughput).

Usage:
    ankhdjet fit [--bracketed]
"""

from __future__ import annotations

import argparse

from ankhdjet.backend.verilog import PipelineConfig
from ankhdjet.estimate.area_model import PDK, estimate_pipeline
from ankhdjet.estimate.throughput_calibration import (
    apply_bracket, load_calibrated,
)
from ankhdjet.frontend.synthetic import build_transformer_ir
from ankhdjet.pdks import discover_pdks

# Descriptor sweep order: the two SKY130 anchors, then the scaled nodes.
FIT_PDKS = ["sky130_biroma_bound", "sky130_v4", "gf180",
            "generic_65nm", "generic_28nm", "generic_6nm", "asap7"]


def model_size(hidden: int, n_layers: int, heads: int, head_dim: int,
               ffn_mult: int, vocab: int) -> int:
    """Total matmul params for the transformer config."""
    qkv = heads * head_dim
    per_block = (
        hidden * qkv * 3      # Q, K, V
        + qkv * hidden        # output proj
        + hidden * ffn_mult * hidden * 2  # FFN up + down
    )
    return per_block * n_layers + hidden * vocab


def try_fit(
    pdk: PDK,
    die_budget_mm2: float,
    config: dict,
    tile_options: list[int],
    kv_ctx: int = 1024,
    pipelined: bool = False,
    bracket: str | None = None,
    calibrated: dict | None = None,
) -> tuple[int | None, float, float]:
    """Find the tile_cols that fits the model and maximizes throughput.
    Returns (best_tile_cols, used_area_mm2, tokens_per_s). Returns
    (None, 0, 0) if nothing fits.

    pipelined=True uses inter-layer pipelining (lockstep epoch scheduler);
    steady-state throughput is set by the slowest layer, not the sum.

    bracket in {None, "low", "mid", "high"}: if set, override pdk's
    throughput knobs from the calibrated bracket. None means use the
    pdk's YAML values (RTL-ideal upper bound by default).
    """
    pdk_eff = apply_bracket(pdk, calibrated, bracket) if bracket and calibrated else pdk

    model = build_transformer_ir(**config, name="try")
    kv_bytes_per_tok = (
        config.get("layers", config.get("n_layers", 12))
        * config["heads"] * 2 * config["head_dim"]
    )

    best = None
    for tc in tile_options:
        cfg = PipelineConfig(k_bits=8, tile_cols=tc, pipelined=pipelined)
        r = estimate_pipeline(
            model, cfg, pdk_eff,
            kv_context_tokens=kv_ctx,
            kv_bytes_per_token=kv_bytes_per_tok,
            tile_cols=tc,
            pipelined=pipelined,
        )
        area = r.total_mm2
        if area <= die_budget_mm2:
            if best is None or r.tokens_per_second > best[2]:
                best = (tc, area, r.tokens_per_second)
    return best if best else (None, 0.0, 0.0)


# Canonical transformer (hidden, layers) shapes ordered by parameter count.
# Aspect ratios mirror published model families (SmolLM, Pythia, Llama,
# BitNet). Sweeping along this ladder keeps every candidate shape on the
# curve real LLMs actually live on. The largest entry is Llama-70B-class:
# headroom for 6nm-class silicon and beyond.
CANONICAL_SHAPES: list[tuple[int, int]] = [
    (128,   4),   # ~5M
    (256,   4),   # ~11M
    (384,   6),   # ~25M
    (512,   8),   # ~40M
    (768,  12),   # ~110M  (SmolLM-135M class)
    (1024, 16),   # ~250M
    (1024, 24),   # ~350M  (Pythia-410M class)
    (1536, 24),   # ~750M  (Pythia-1B class)
    (2048, 24),   # ~1.5B  (BitNet b1.58-2B)
    (2560, 32),   # ~3B
    (3072, 32),   # ~5B
    (4096, 32),   # ~8B    (Llama 3.1 8B)
    (5120, 40),   # ~13B   (Llama-13B)
    (6656, 60),   # ~33B   (Llama-30B)
    (8192, 80),   # ~70B   (Llama-70B)
]


def sweep_model_sizes(pdk: PDK, die_budget_mm2: float,
                      calibrated: dict | None = None):
    """Walk the canonical shape ladder; report every shape that fits and
    return the largest. Stops as soon as the next shape exceeds the budget.

    If `calibrated` is provided, also reports the bracketed (low-mid-high)
    pipelined throughput. Otherwise reports just the RTL-ideal sequential
    and pipelined numbers.
    """
    print(f"\nDie budget: {die_budget_mm2} mm^2 at {pdk.name}")
    if calibrated:
        print(f"{'hidden':>7} {'layers':>7} {'params':>10} {'tile':>5} "
              f"{'area mm^2':>10} {'pipe tok/s (low - mid - high)':>40}")
        print("-" * 87)
    else:
        print(f"{'hidden':>7} {'layers':>7} {'params':>10} {'tile_cols':>10} "
              f"{'area mm^2':>10} {'seq tok/s':>12} {'pipe tok/s':>13} {'speedup':>8}")
        print("-" * 84)

    tile_opts = [1, 16, 32, 64, 128, 256, 512, 1024, 2048]
    largest = None
    for hidden, n_layers in CANONICAL_SHAPES:
        config = dict(
            hidden=hidden, layers=n_layers, heads=max(1, hidden // 64),
            head_dim=64, ffn_mult=4, vocab=32000,
        )
        params = model_size(hidden, n_layers, config["heads"],
                            config["head_dim"], 4, 32000)

        if calibrated:
            # Pick tile based on the *mid* bracket throughput; report all three.
            tc_p, area_p, tps_mid = try_fit(
                pdk, die_budget_mm2, config, tile_opts,
                pipelined=True, bracket="mid", calibrated=calibrated)
            if tc_p is None:
                print(f"{hidden:>7} {n_layers:>7} {params/1e6:>9.1f}M "
                      f"{'(over budget)':>34}")
                break
            # Re-query at the same tile_cols for low/high so the bracket
            # comes from one physical configuration, not three optima.
            cfg = PipelineConfig(k_bits=8, tile_cols=tc_p, pipelined=True)
            kv_bytes = config["layers"] * config["heads"] * 2 * config["head_dim"]
            tps_low = estimate_pipeline(
                build_transformer_ir(**config, name="x"),
                cfg, apply_bracket(pdk, calibrated, "low"),
                kv_context_tokens=1024, kv_bytes_per_token=kv_bytes,
                tile_cols=tc_p, pipelined=True).tokens_per_second
            tps_high = estimate_pipeline(
                build_transformer_ir(**config, name="x"),
                cfg, apply_bracket(pdk, calibrated, "high"),
                kv_context_tokens=1024, kv_bytes_per_token=kv_bytes,
                tile_cols=tc_p, pipelined=True).tokens_per_second
            # High alpha bracket = pessimistic = low tok/s; sort ascending
            # so the column header (low - mid - high) matches reading order.
            tps_sorted = sorted([tps_low, tps_mid, tps_high])
            band = (f"{tps_sorted[0]:>10,.0f} - {tps_sorted[1]:>10,.0f} - "
                    f"{tps_sorted[2]:>10,.0f}")
            print(f"{hidden:>7} {n_layers:>7} {params/1e6:>9.1f}M "
                  f"{tc_p:>5} {area_p:>10.2f} {band:>40}")
            largest = (hidden, n_layers, params, area_p, *tps_sorted)
        else:
            tc_seq, area_seq, tps_seq = try_fit(
                pdk, die_budget_mm2, config, tile_opts, pipelined=False)
            tc_pipe, area_pipe, tps_pipe = try_fit(
                pdk, die_budget_mm2, config, tile_opts, pipelined=True)
            if tc_seq is None:
                print(f"{hidden:>7} {n_layers:>7} {params/1e6:>9.1f}M "
                      f"{'(over budget)':>34}")
                break
            if tc_pipe is not None:
                speedup = tps_pipe / tps_seq if tps_seq > 0 else 0.0
                print(f"{hidden:>7} {n_layers:>7} {params/1e6:>9.1f}M "
                      f"{tc_pipe:>10} {area_pipe:>10.2f} {tps_seq:>12,.0f} "
                      f"{tps_pipe:>13,.0f} {speedup:>7.1f}x")
                largest = (hidden, n_layers, params, area_pipe, tps_seq,
                           tps_pipe, tps_pipe)
    return largest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ankhdjet fit", description=__doc__)
    ap.add_argument("--bracketed", action="store_true",
                    help="report low-mid-high tokens/sec from the calibrated "
                         "bracket (silicon + IRDS + SRAM anchors) instead of "
                         "the RTL-ideal upper bound")
    ap.add_argument("--die-budget-mm2", type=float, default=815.0)
    args = ap.parse_args(argv)

    pdks = discover_pdks()
    sweep = [pdks[n] for n in FIT_PDKS if n in pdks]
    calibrated = load_calibrated() if args.bracketed else None
    if args.bracketed and not calibrated:
        print("(--bracketed requested but the calibrated bracket is empty; "
              "run the throughput calibration first)")
        return 1
    if args.bracketed:
        print("Calibrated bracket:")
        print("  alpha       <- silicon back-fit on SKY130/GF180 tapeouts "
              "(extrapolated to other nodes)")
        print("  wire cycles <- IRDS 2024 Interconnect / Saraswat EE311 / "
              "Science 2024")
        print("  kv  cycles  <- foundry SRAM datasheets + OpenRAM measurements")

    for pdk in sweep:
        sweep_model_sizes(pdk, args.die_budget_mm2, calibrated=calibrated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
