"""Side-by-side area + throughput across the discovered PDK descriptors for one model.

Same compiler input, same first-principles architectural derivation, three
physical substrates. Each row is independently produced by the area model;
no inter-PDK extrapolation. The point is the agnostic-node comparison the
project exists to enable.

Usage:
    ankhdjet compare
    ankhdjet compare --repo-id microsoft/bitnet-b1.58-2B-4T \\
        --kv-context 4096 --die-budget-mm2 815
"""

from __future__ import annotations

import argparse
from ankhdjet.estimate.area_model import PDK, estimate_pipeline
from ankhdjet.backend.verilog import PipelineConfig
from ankhdjet.frontend.hf import load_config
from ankhdjet.estimate.throughput_calibration import apply_bracket, load_calibrated


COMPARE_PDKS = ["sky130_v4", "sky130_biroma_bound", "gf180", "asap7"]


from ankhdjet.pdks import discover_pdks


BIROMA_WINDOW_NM = (28.0, 65.0)  # viability window per the BiROMA investigation


def biroma_applies(pdk: PDK, requested: bool) -> bool:
    """BiROMA encoding only inside its 28-65 nm viability window (NO-GO
    at 130 nm per the investigation record; below 28 nm the analog tier
    itself ends). Outside the window the request is ignored per node."""
    if not requested:
        return False
    lo, hi = BIROMA_WINDOW_NM
    ok = lo <= pdk.process_nm <= hi
    if not ok:
        print(f"[note] {pdk.name}: --biroma ignored at {pdk.process_nm:g} nm "
              f"(viability window {lo:g}-{hi:g} nm)")
    return ok


def compile_for_pdk(pdk: PDK, model, arch, kv_context: int,
                     die_budget_mm2: float, cal: dict,
                     biroma: bool = False, readout: str = "analog") -> dict | None:
    biroma = biroma_applies(pdk, biroma)
    kv_bytes_per_tok = (
        arch.num_hidden_layers * arch.num_key_value_heads * 2 * arch.head_dim
    )
    p_mid = apply_bracket(pdk, cal, "mid")

    chosen_tc = None
    for tc in [16, 32, 64, 128, 256, 512, 1024, 2048]:
        cfg = PipelineConfig(k_bits=8, tile_cols=tc, pipelined=True, readout=readout)
        r = estimate_pipeline(
            model, cfg, p_mid,
            kv_context_tokens=kv_context, kv_bytes_per_token=kv_bytes_per_tok,
            tile_cols=tc, pipelined=True,
            head_dim=arch.head_dim, n_heads=arch.num_attention_heads,
            n_transformer_blocks=arch.num_hidden_layers,
            biroma=biroma,
        )
        if r.total_mm2 <= die_budget_mm2:
            chosen_tc = tc
            break
    if chosen_tc is None:
        return None

    cfg = PipelineConfig(k_bits=8, tile_cols=chosen_tc, pipelined=True, readout=readout)
    rs = []
    for b in ("low", "mid", "high"):
        rs.append(estimate_pipeline(
            model, cfg, apply_bracket(pdk, cal, b),
            kv_context_tokens=kv_context, kv_bytes_per_token=kv_bytes_per_tok,
            tile_cols=chosen_tc, pipelined=True,
            head_dim=arch.head_dim, n_heads=arch.num_attention_heads,
            n_transformer_blocks=arch.num_hidden_layers,
            biroma=biroma,
        ))
    tps = sorted(r.tokens_per_second for r in rs)
    r_mid = rs[1]
    return {
        "pdk_name": pdk.name,
        "process_nm": pdk.process_nm,
        "tile_cols": chosen_tc,
        "total_mm2": r_mid.total_mm2,
        "die_pct": 100.0 * r_mid.total_mm2 / die_budget_mm2,
        "cells_mm2": r_mid.cells_subtotal_um2 / 1e6,
        "periph_mm2": r_mid.peripherals_subtotal_um2 / 1e6,
        "kv_mm2": r_mid.kv_cache_um2 / 1e6,
        "attn_mm2": r_mid.attention_um2 / 1e6,
        "n_domains": r_mid.n_clock_domains,
        "domain_mm2": r_mid.clock_domain_area_mm2,
        "eff_mhz": r_mid.effective_clock_mhz,
        "cycles_per_token": r_mid.cycles_per_token,
        "tps_low": tps[0], "tps_mid": tps[1], "tps_high": tps[2],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ankhdjet compare", description=__doc__)
    ap.add_argument("--repo-id", default=None,
                    help="HF repo to load; if omitted, uses a synthetic "
                         "20M-param BitNet that fits all three open PDKs")
    ap.add_argument("--kv-context", type=int, default=512)
    ap.add_argument("--die-budget-mm2", type=float, default=815.0)
    ap.add_argument("--readout", choices=["analog", "digital"], default="digital",
                    help="NOR-array readout tier to model: analog StrongARM "
                         "comparators (published anchors) or digital "
                         "full-swing samplers (the default tier).")
    ap.add_argument("--biroma", action="store_true",
                    help="Model BiROMA 2-weights-per-1T-cell encoding "
                         "(halves cell-array area). Applies only inside its "
                         "28-65 nm viability window; NO-GO at 130 nm per the "
                         "investigation record.")
    args = ap.parse_args(argv)

    pdks = discover_pdks()
    cal = load_calibrated()

    if args.repo_id:
        print(f"Loading {args.repo_id} ...")
        model, arch = load_config(args.repo_id)
    else:
        from ankhdjet.frontend.hf import TransformerArch, build_ir_from_arch
        arch = TransformerArch(
            hidden_size=512, num_hidden_layers=8, num_attention_heads=8,
            head_dim=64, num_key_value_heads=2, intermediate_size=1024,
            vocab_size=8000, max_position_embeddings=1024,
            name="bitnet_22M_demo",
        )
        model = build_ir_from_arch(arch)
        print(f"Synthetic demo shape: {arch.name} (fits all three open PDKs)")
    n_params = sum(L.input_dim * L.output_dim for L in model.layers)
    print(f"Model: {arch.name}, {n_params/1e9:.3f} B LINEAR weights, "
          f"{arch.num_hidden_layers} blocks, hidden={arch.hidden_size}, "
          f"head_dim={arch.head_dim}, n_heads={arch.num_attention_heads} "
          f"(KV {arch.num_key_value_heads})")
    print(f"Die budget: {args.die_budget_mm2:.0f} mm^2  KV context: {args.kv_context} tokens\n")

    results = []
    for name in COMPARE_PDKS:
        if name not in pdks:
            print(f"[skip] {name}: not in pdk/*.yaml")
            continue
        r = compile_for_pdk(pdks[name], model, arch, args.kv_context,
                            args.die_budget_mm2, cal, biroma=args.biroma,
                            readout=args.readout)
        if r is None:
            print(f"[over] {name}: model does not fit die budget")
            continue
        results.append(r)

    print(f"{'pdk':<10} {'process':>8} {'tile':>5} {'area mm^2':>10} {'die%':>6} "
          f"{'cells':>7} {'periph':>7} {'KV':>6} {'attn':>5} "
          f"{'domains':>9} {'eff MHz':>9} {'cyc/tok':>9} "
          f"{'tok/s (low - mid - high)':>34}")
    print("-" * 145)
    for r in results:
        band = f"{r['tps_low']:>9,.0f} - {r['tps_mid']:>9,.0f} - {r['tps_high']:>9,.0f}"
        domains = f"{r['n_domains']}x{r['domain_mm2']:.1f}"
        print(f"{r['pdk_name']:<10} {r['process_nm']:>6.0f}nm "
              f"{r['tile_cols']:>5} {r['total_mm2']:>10.1f} {r['die_pct']:>5.1f}% "
              f"{r['cells_mm2']:>7.1f} {r['periph_mm2']:>7.1f} "
              f"{r['kv_mm2']:>6.2f} {r['attn_mm2']:>5.2f} "
              f"{domains:>9} {r['eff_mhz']:>9.0f} {r['cycles_per_token']:>9}  "
              f"{band:>34}")

    print()
    print("All architectural decisions derived from workload + PDK; bracket")
    print("reflects only physical uncertainty (alpha from OpenROAD CTS+STA).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
