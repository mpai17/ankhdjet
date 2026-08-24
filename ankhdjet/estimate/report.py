"""Compile any HuggingFace BitNet-class ternary model to any PDK in
pdk/*.yaml: area + bracketed throughput report.

First-principles derivation: every architectural decision (tile_cols,
attention engine size, clock domains) is computed from the workload +
PDK; the user supplies only the model + node + die budget. The only
sweep is over the physical-uncertainty bracket (low/mid/high alpha
from OpenROAD CTS+STA) at fixed architecture.

Usage:
    ankhdjet estimate -- --pdk asap7
    ankhdjet estimate -- --pdk generic_6nm \\
        --repo-id microsoft/bitnet-b1.58-2B-4T --kv-context 4096
    ankhdjet estimate -- --list-pdks
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ankhdjet.estimate.area_model import PDK, estimate_pipeline
from ankhdjet.backend.verilog import PipelineConfig
from ankhdjet.frontend.hf import load_config
from ankhdjet.estimate.throughput_calibration import apply_bracket, load_calibrated


from ankhdjet.pdks import discover_pdks


def main(argv: list[str] | None = None) -> int:
    pdks = discover_pdks()

    ap = argparse.ArgumentParser(
        prog="ankhdjet estimate",
        description="Compile any HF ternary model to any PDK; report area + bracketed throughput.")
    ap.add_argument("--pdk", default="asap7",
                    help=f"PDK name (one of: {', '.join(sorted(pdks))})")
    ap.add_argument("--repo-id", default="microsoft/bitnet-b1.58-2B-4T")
    ap.add_argument("--kv-context", type=int, default=1024)
    ap.add_argument("--die-budget-mm2", type=float, default=815.0)
    ap.add_argument("--list-pdks", action="store_true")
    ap.add_argument("--biroma", action="store_true",
                    help="Model BiROMA 2-weights-per-1T-cell encoding "
                         "(halves cell-array area term). Applies only inside "
                         "its 28-65 nm viability window; NO-GO at 130 nm.")
    ap.add_argument("--readout", choices=["analog", "digital"], default="digital",
                    help="NOR-array readout tier to model (digital is the "
                         "only tier below 28 nm).")
    ap.add_argument("--subcol-rows", type=int, default=64,
                    help="Rows per bitline (64 = as-built; 256 = "
                         "production-path geometry).")
    ap.add_argument("--k-bits", type=int, default=8,
                    help="Activation precision in bits (Microsoft BitNet "
                         "b1.58 reference is A8; some derivatives use A4 "
                         "for ~2x throughput on the same hardware).")
    args = ap.parse_args(argv)

    if args.list_pdks:
        print(f"{'name':<18} {'process':>8}   notes")
        print("-" * 60)
        for name, p in sorted(pdks.items()):
            print(f"{name:<18} {p.process_nm:>6.0f}nm   "
                  f"clock_mhz={p.clock_mhz:.0f} cell_um2={p.bitcell_um2:.4f}")
        return 0

    if args.pdk not in pdks:
        print(f"unknown PDK '{args.pdk}'. Available: {', '.join(sorted(pdks))}",
              file=sys.stderr)
        return 2
    pdk = pdks[args.pdk]
    if args.biroma:
        from ankhdjet.estimate.compare import biroma_applies
        args.biroma = biroma_applies(pdk, args.biroma)
    cal = load_calibrated()

    print(f"Loading {args.repo_id} config from HuggingFace ...")
    model, arch = load_config(args.repo_id)
    n_params = sum(L.input_dim * L.output_dim for L in model.layers)
    fabric_params = sum(L.input_dim * L.output_dim for L in model.layers
                        if L.name != "lm_head")
    print(f"\nModel: {arch.name}")
    print(f"  hidden_size       = {arch.hidden_size}")
    print(f"  num_hidden_layers = {arch.num_hidden_layers}")
    print(f"  num_attention_heads = {arch.num_attention_heads} "
          f"(KV {arch.num_key_value_heads})")
    print(f"  head_dim          = {arch.head_dim}")
    print(f"  intermediate_size = {arch.intermediate_size}")
    print(f"  vocab_size        = {arch.vocab_size}")
    print(f"  ternary fabric weights = {fabric_params/1e9:.3f} B (mask-programmed on CiROM)")

    kv_bytes_per_tok = (
        arch.num_hidden_layers * arch.num_key_value_heads * 2 * arch.head_dim * 1
    )

    print(f"\nTarget: {pdk.name} {pdk.process_nm:.0f} nm, "
          f"die budget {args.die_budget_mm2:.0f} mm^2, "
          f"KV context {args.kv_context} tokens "
          f"({kv_bytes_per_tok * args.kv_context / 1e6:.1f} MB)")

    # First-principles tile_cols selection: pick the smallest that fits
    # the die budget at the mid alpha bracket (more tiles = more
    # parallelism = higher throughput; area constraint sets the floor).
    candidates = [16, 32, 64, 128, 256, 512, 1024, 2048]
    p_mid = apply_bracket(pdk, cal, "mid")
    # BitNet ties lm_head to the bf16 embedding table (not ternary), so it
    # is off the hardwired fabric - matching ankhdjet.backend.macro_grid's
    # skip_layers, so the estimate and the emitted mask set agree on what is
    # actually mask-programmed.
    off_fabric = ("lm_head",)
    chosen_tc = None
    chosen_r = None
    for tc in candidates:
        cfg = PipelineConfig(k_bits=args.k_bits, tile_cols=tc, pipelined=True,
                             readout=args.readout, subcol_rows=args.subcol_rows)
        r = estimate_pipeline(
            model, cfg, p_mid,
            kv_context_tokens=args.kv_context,
            kv_bytes_per_token=kv_bytes_per_tok,
            tile_cols=tc, pipelined=True,
            head_dim=arch.head_dim,
            n_heads=arch.num_attention_heads,
            n_transformer_blocks=arch.num_hidden_layers,
            biroma=args.biroma,
            off_fabric_layers=off_fabric,
        )
        if chosen_r is None:
            chosen_tc, chosen_r = tc, r  # minimum-area configuration
        if r.total_mm2 <= args.die_budget_mm2:
            chosen_tc, chosen_r = tc, r
            break

    # Bracket throughput over alpha low/mid/high at the chosen architecture.
    cfg = PipelineConfig(k_bits=args.k_bits, tile_cols=chosen_tc, pipelined=True,
                         readout=args.readout, subcol_rows=args.subcol_rows)
    rs = []
    for b in ("low", "mid", "high"):
        rs.append(estimate_pipeline(
            model, cfg, apply_bracket(pdk, cal, b),
            kv_context_tokens=args.kv_context,
            kv_bytes_per_token=kv_bytes_per_tok,
            tile_cols=chosen_tc, pipelined=True,
            off_fabric_layers=off_fabric,
            head_dim=arch.head_dim,
            n_heads=arch.num_attention_heads,
            n_transformer_blocks=arch.num_hidden_layers,
            biroma=args.biroma,
        ))
    tps_sorted = sorted(r.tokens_per_second for r in rs)
    r_mid = rs[1]

    print()
    print("=" * 70)
    print(f"Compiled architecture (first-principles, no sweep parameters):")
    print(f"  tile_cols              : {chosen_tc} (minimum-area configuration)")
    print(f"  clock domains          : {r_mid.n_clock_domains} x "
          f"{r_mid.clock_domain_area_mm2:.2f} mm^2 (one per layer)")
    print()
    print("Area breakdown (mm^2):")
    print(f"  CiROM cells            : {r_mid.cells_subtotal_um2/1e6:>8.2f}  "
          f"({100*r_mid.cells_subtotal_um2/r_mid.total_um2:.1f}%)")
    print(f"  Peripherals            : {r_mid.peripherals_subtotal_um2/1e6:>8.2f}  "
          f"({100*r_mid.peripherals_subtotal_um2/r_mid.total_um2:.1f}%)")
    print(f"  KV cache SRAM          : {r_mid.kv_cache_um2/1e6:>8.2f}  "
          f"({100*r_mid.kv_cache_um2/r_mid.total_um2:.1f}%)")
    print(f"  Attention engine       : {r_mid.attention_um2/1e6:>8.2f}  "
          f"({100*r_mid.attention_um2/r_mid.total_um2:.1f}%)")
    print(f"  Die overhead           : {r_mid.die_overhead_um2/1e6:>8.2f}  "
          f"({100*r_mid.die_overhead_um2/r_mid.total_um2:.1f}%)")
    over = ("; exceeds the stated die budget"
            if r_mid.total_mm2 > args.die_budget_mm2 else "")
    print(f"  TOTAL                  : {r_mid.total_mm2:>8.2f} mm^2 "
          f"({100*r_mid.total_mm2/args.die_budget_mm2:.1f}% of "
          f"{args.die_budget_mm2:.0f} mm^2 die{over})")
    if r_mid.off_fabric_params:
        print(f"  (off-fabric            : {r_mid.off_fabric_params/1e6:>7.1f} M params "
              f"[{', '.join(r_mid.off_fabric_layers)}] not ternary; "
              f"excluded from the hardwired die above)")
    print()
    print("Throughput:")
    print(f"  Effective clock        : {r_mid.effective_clock_mhz:>6.0f} MHz "
          f"(ideal {r_mid.clock_mhz:.0f} MHz)")
    print(f"  Cycles / token         : {r_mid.cycles_per_token}")
    print(f"  Tokens/sec (low/mid/high alpha bracket): "
          f"{tps_sorted[0]:,.0f} / {tps_sorted[1]:,.0f} / {tps_sorted[2]:,.0f}")
    print()
    print("All architectural choices (tile_cols, attention engine, clock domains)")
    print("derived from workload + PDK. Bracket reflects only physical uncertainty")
    print("(alpha from OpenROAD CTS+STA on 13 ORFS designs).")
    print()
    print("CAVEATS:")
    print("  * Pre-routing area + throughput. OpenROAD anchor goes through")
    print("    floorplan + place + CTS + STA but NOT global+detailed routing")
    print("    or power analysis; real silicon will see additional fmax loss")
    print("    from routing congestion + IR drop on a 815 mm^2 die.")
    if args.pdk in ("gf180", "asap7"):
        print(f"  * {args.pdk} parameters are scaled from SKY130 measurements,")
        print(f"    not directly characterized at the target node. Per-PDK")
        print(f"    re-characterization (BL discharge, SA mismatch, OpenROAD STA")
        print(f"    on real {args.pdk} libs) would tighten these numbers.")
    if args.biroma:
        print("  * BiROMA cell-array area halving requires a bidirectional")
        print("    bitcell. v3_biroma is built + DRC-clean at SKY130 only;")
        print("    GF180 / ASAP7 BiROMA is a forward-looking projection.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
