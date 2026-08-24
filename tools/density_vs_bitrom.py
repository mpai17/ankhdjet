"""Density comparison: Ankhdjet SKY130 baseline vs BitROM (closest open peer).

BitROM (arXiv 2509.08542 / ASP-DAC 2026) is the closest published open
peer at ternary precision. Their 65 nm prototype reports a per-bit
density of 4967 kB/mm^2, which on a ternary basis (1.58 bits/weight via
BiROMA's 2-weights-per-1T-cell encoding) maps to ~0.04 um^2/weight at
65 nm. Node-shrinking that to SKY130 130 nm via (130/65)^2 = 4x
suggests BitROM-equivalent silicon at SKY130 would be ~0.16 um^2/weight.

This tool prints each cell variant's density side-by-side with the
BitROM-extrapolated peer.

Usage:
    uv run tools/density_vs_bitrom.py
"""

from __future__ import annotations

import sys

# BitROM published density at 65 nm
BITROM_KB_PER_MM2_65NM = 4967.0
BITROM_NODE_NM = 65

# Cell-variant density ladder at SKY130 130 nm (um^2/weight per stop)
SKY130_NM = 130
DENSITY_STOPS = [
    ("v2 (PCell + built-in body tap, superseded)",         6.20),
    ("v3 (W=0.84, superseded)",                            0.80),
    ("v3_biroma (superseded)",                             0.40),
    ("v4 (W=0.42 minimum, SUBCOL=64, production)",         0.50),
    ("v4_biroma (density bound; closed at SKY130)",        0.25),
]


def bitrom_per_weight_um2_at_node(target_nm: int) -> float:
    """BitROM's 4967 kB/mm^2 at 65 nm, scaled to target node by (target/65)^2."""
    # 4967 kB/mm^2 = 4967 * 1024 bytes / mm^2 = 4967 * 1024 * 8 bits / mm^2
    bits_per_mm2_65nm = BITROM_KB_PER_MM2_65NM * 1024 * 8
    # On a ternary encoding via BiROMA: 1.58 bits / weight effectively,
    # but for an apples-to-apples per-weight comparison we use 1 stored
    # ternary value per cell area unit (matching how we report).
    # BitROM: ~0.025 um^2/bit at 65 nm ⇒ ~0.04 um^2/weight (1.58 bits)
    um2_per_bit_65nm = 1e6 / bits_per_mm2_65nm
    um2_per_weight_65nm = um2_per_bit_65nm * 1.58
    # Linear scale by (target_nm / 65)^2
    return um2_per_weight_65nm * (target_nm / BITROM_NODE_NM) ** 2


PER_PDK_NM = {
    "SKY130": 130,
    "GF180":  180,
    "ASAP7":    7,
}

# Macro-level wrapper area as a fraction of cell-array area. Covers
# row decoder, WL drivers, precharge stage, sense amps, TriMLA
# accumulators, global adder tree, bit-slice shift-accumulator, FSM,
# and replica column. Matches macro/sky130/gen_anchor_abstracts.py.
ANKHDJET_WRAPPER_FRAC = 0.30
# BitROM Sec III-B3 reports their wrapper at 4.8% of the array area;
# their published 4,967 kB/mm^2 already includes that wrapper, so the
# ratio comparison must compare Ankhdjet WITH wrapper to BitROM WITH
# wrapper (= the 4,967 number).


def main() -> int:
    bitrom_sky130 = bitrom_per_weight_um2_at_node(SKY130_NM)

    print("Density vs BitROM (ternary weights, with-wrapper for fair comparison)")
    print("=" * 70)
    print(f"BitROM 65 nm headline: {bitrom_per_weight_um2_at_node(BITROM_NODE_NM):.3f} um^2/weight")
    print(f"  (= {BITROM_KB_PER_MM2_65NM:.0f} kB/mm^2; INCLUDES BitROM's 4.8% wrapper)")
    print(f"Ankhdjet wrapper overhead modeled at {ANKHDJET_WRAPPER_FRAC*100:.0f}% of cell-array area")
    print(f"  (decoder + WL drivers + SAs + accumulators + adder + FSM)")
    print()
    for pdk, nm in PER_PDK_NM.items():
        scale = (nm / SKY130_NM) ** 2
        bitrom_node = bitrom_per_weight_um2_at_node(nm)
        print(f"\n--- {pdk} {nm} nm ---")
        print(f"BitROM extrapolated to {pdk}: {bitrom_node:.3f} um^2/weight (with wrapper)")
        print(f"{'Ankhdjet cell stage':<41} {'cell':>8} {'+wrap':>8}  {'vs BitROM':>10}")
        print("-" * 71)
        for label, area_sky130 in DENSITY_STOPS:
            cell_area = area_sky130 * scale
            stack_area = cell_area * (1 + ANKHDJET_WRAPPER_FRAC)
            print(f"{label:<41} {cell_area:>8.3f} {stack_area:>8.3f}   "
                  f"{stack_area / bitrom_node:>7.1f}x")
    print()

    production = next(a for label, a in DENSITY_STOPS if "production" in label)
    bound = next(a for label, a in DENSITY_STOPS if "bound" in label)
    production *= 1 + ANKHDJET_WRAPPER_FRAC
    bound *= 1 + ANKHDJET_WRAPPER_FRAC
    print(f"With-wrapper per-weight area / BitROM (node-independent ratio):")
    print(f"  v4 production cell: {production / bitrom_sky130:.1f}x worse than BitROM.")
    print(f"  BiROMA 2-weights/cell bound (closed at SKY130): "
          f"{bound / bitrom_sky130:.1f}x worse")
    print(f"  (open-PDK + open-tool ceiling vs aggressive custom mask ROM).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
