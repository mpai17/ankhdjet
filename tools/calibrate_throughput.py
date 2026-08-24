"""Run all available throughput-knob anchors and emit pdk/calibrated.yaml.

Usage:
    uv run tools/calibrate_throughput.py
    uv run tools/calibrate_throughput.py --bus-mm 8 --kv-bank-kb 256

Anchors:
    silicon  measured (process, area, fmax) tuples from open tapeouts
    irds     per-mm global wire delay from IRDS Interconnect roadmap
    sram     KV-cache SRAM access bounds from foundry datasheets + OpenRAM

Each anchor is independent; missing data files just skip that contribution.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ankhdjet.estimate.throughput_calibration import (
    CalibratedKnob, CalibratedNode,
    emit_calibrated_yaml, extrapolate_alpha,
    fit_alpha_from_silicon, fit_kv_cycles, fit_wire_hop_cycles,
    load_irds_wire_points, load_silicon_points, load_sram_bounds,
)


# Per-node ideal small-design fmax (MHz). Used as the "no-skew" reference
# clock that achieved silicon fmax is compared against. Sources cited
# inline in pdk/calibration_data/*.yaml.
TARGET_CLOCK_MHZ: dict[float, float] = {
    180.0:  150.0,    # GF180MCU small-design typical
    130.0:  200.0,    # SKY130 small-design typical (sky130_fd_sc_hd)
    65.0:   400.0,    # generic 65nm bulk
    28.0:  1000.0,    # generic 28nm HKMG
    7.0:   2400.0,    # ASAP7 OpenROAD CTS+STA: aes hits 2322 MHz at 0.0026 mm^2
    6.0:   2500.0,    # TSMC N6/N5 small-block reference
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bus-mm", type=float, default=10.0,
                   help="typical inter-layer activation bus length on an 815 mm^2 die")
    p.add_argument("--kv-bank-kb", type=float, default=256.0,
                   help="target KV-cache SRAM bank size for the headline shape")
    p.add_argument("--accesses-per-layer", type=int, default=2,
                   help="SRAM accesses per layer per token (read K + read V)")
    p.add_argument("--out", type=Path, default=REPO / "pdk" / "calibrated.yaml")
    args = p.parse_args()

    silicon = load_silicon_points()
    irds    = load_irds_wire_points()
    sram    = load_sram_bounds()

    print(f"Loaded anchors:")
    print(f"  silicon:  {len(silicon):>3d} measured (process, area, fmax) points")
    print(f"  irds:     {len(irds):>3d} per-mm wire-delay entries")
    print(f"  sram:     {len(sram):>3d} (process, bank_kb) latency bounds")
    print()

    alpha    = fit_alpha_from_silicon(silicon, TARGET_CLOCK_MHZ)
    wire_cyc = fit_wire_hop_cycles(irds, args.bus_mm, TARGET_CLOCK_MHZ)
    kv_cyc   = fit_kv_cycles(sram, args.kv_bank_kb, args.accesses_per_layer, TARGET_CLOCK_MHZ)

    # All nodes mentioned by any anchor + the standard set we want headlines for
    all_nodes = sorted(
        set(alpha) | set(wire_cyc) | set(kv_cyc) | set(TARGET_CLOCK_MHZ)
    )

    # Project alpha to nodes that have wire/sram coverage but no silicon anchor
    alpha = extrapolate_alpha(alpha, all_nodes, anchor_node=130.0)
    if not all_nodes:
        print("No data available - populate pdk/calibration_data/*.yaml and re-run.")
        return 1

    nodes: dict[float, CalibratedNode] = {}
    for n in all_nodes:
        nodes[n] = CalibratedNode(
            process_nm=n,
            clock_skew_alpha=alpha.get(n, CalibratedKnob(0.0, 0.0, 0.0, ["_no_silicon_anchor"])),
            wire_hop_cycles=wire_cyc.get(n, CalibratedKnob(0.0, 0.0, 0.0, ["_no_irds_anchor"])),
            kv_access_cycles_per_layer=kv_cyc.get(n, CalibratedKnob(0.0, 0.0, 0.0, ["_no_sram_anchor"])),
        )

    emit_calibrated_yaml(nodes, args.out)
    print(f"Wrote {args.out.relative_to(REPO)}")

    print()
    print(f"{'node':>8} {'alpha (lo/mid/hi)':>26} {'wire cyc':>14} {'kv cyc':>14}")
    print("-" * 70)
    for n in all_nodes:
        c = nodes[n]
        print(f"{n:>6g}nm "
              f"{c.clock_skew_alpha.low:>7.3f} / {c.clock_skew_alpha.mid:>5.3f} / {c.clock_skew_alpha.high:>5.3f}  "
              f"{int(c.wire_hop_cycles.low):>3d} / {int(c.wire_hop_cycles.mid):>3d} / {int(c.wire_hop_cycles.high):>3d}    "
              f"{int(c.kv_access_cycles_per_layer.low):>3d} / {int(c.kv_access_cycles_per_layer.mid):>3d} / {int(c.kv_access_cycles_per_layer.high):>3d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
