"""Unit tests for ankhdjet/area_model.estimate_layer.

Pins:
  - cell area scales as N*M * bitcell_um2 (NOR convention: every position
    is a transistor; zero weights are mask-programmed)
  - BiROMA halves the cell count (2 weights per 1T cell, ceil rounding
    for odd totals)
  - NOR-array peripheral formula switches to per-sub-column SA + decoder
    + precharge instead of popcount tree
  - tile_cols > 1 shares popcount trees across output columns
  - active_cells reflects the nonzero weight count (sparsity-independent
    of footprint, per the NOR-array family convention, Taalas/BitROM precedent)

Uses a synthetic PDK so the test doesn't drift if the real sky130.yaml
is retuned.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.package


import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.estimate.area_model import PDK, estimate_layer
from ankhdjet.frontend.ir import Layer, LayerType, QuantScheme, WeightTensor


def synthetic_pdk(**overrides) -> PDK:
    base = dict(
        name="synthetic",
        process_nm=130.0,
        node_scale=1.0,
        bitcell_um2=2.5,
        gate_equivalent_um2=10.0,
        transistors_per_gate=4,
        popcount_gates_per_row=64,
        between_layer_gates_per_channel=200,
        serializer_gates_per_row=20,
        sram_um2_per_bit=1.0,
        array_overhead_frac=0.0,             # disable to make math explicit
        die_routing_overhead_frac=0.0,
        clock_mhz=500.0,
        vdd_v=1.8,
        synth_calibration=1.0,
        clock_skew_alpha=0.0,
        wire_hop_cycles=0,
        kv_access_cycles_per_layer=0,
    )
    base.update(overrides)
    return PDK(**base)


def make_layer(n: int, m: int, sparsity_frac: float = 0.4) -> Layer:
    rng = np.random.default_rng(0xA1)
    w = rng.choice([-1, 0, 1], size=(n, m), p=[sparsity_frac/2, 1 - sparsity_frac, sparsity_frac/2]).astype(np.int8)
    return Layer(
        name="syn",
        layer_type=LayerType.LINEAR,
        weights={"weight": WeightTensor(name="weight", data=w,
                                        scheme=QuantScheme.TERNARY)},
        input_dim=n, output_dim=m,
    )


def case(label: str, ok: bool, detail: str = "") -> bool:
    marker = "ok" if ok else "FAIL"
    print(f"  [{marker}] {label}" + (f"  {detail}" if detail else ""))
    return ok


def test_cell_count_nor_convention() -> bool:
    n, m = 32, 16
    pdk = synthetic_pdk()
    layer = make_layer(n, m)
    rep = estimate_layer(layer, pdk, nor_array=False)
    expected_cells_um2 = n * m * pdk.bitcell_um2
    return case("cell_um2 = N*M * bitcell_um2 (NOR convention)",
                math.isclose(rep.cells_um2, expected_cells_um2, rel_tol=1e-12),
                f"got={rep.cells_um2} exp={expected_cells_um2}")


def test_biroma_halves_cells() -> bool:
    n, m = 32, 16
    pdk = synthetic_pdk()
    layer = make_layer(n, m)
    rep_full   = estimate_layer(layer, pdk, biroma=False)
    rep_biroma = estimate_layer(layer, pdk, biroma=True)
    expected_biroma_cells = (n*m + 1) // 2 * pdk.bitcell_um2
    return case("biroma=True halves cell count (ceil for odd totals)",
                math.isclose(rep_biroma.cells_um2, expected_biroma_cells, rel_tol=1e-12)
                and rep_biroma.cells_um2 < rep_full.cells_um2,
                f"full={rep_full.cells_um2} biroma={rep_biroma.cells_um2}")


def test_active_cells_match_nonzeros() -> bool:
    n, m = 32, 16
    pdk = synthetic_pdk()
    layer = make_layer(n, m, sparsity_frac=0.6)
    nz = int((layer.weights["weight"].data != 0).sum())
    rep = estimate_layer(layer, pdk)
    return case("active_cells = nonzero ternary weight count",
                rep.active_cells == nz,
                f"active={rep.active_cells} nz={nz} positions={rep.total_positions}")


def test_tile_cols_shares_popcount_tree() -> bool:
    n, m = 64, 32
    pdk = synthetic_pdk()
    layer = make_layer(n, m)
    rep_per_col   = estimate_layer(layer, pdk, tile_cols=1, nor_array=False)
    rep_shared    = estimate_layer(layer, pdk, tile_cols=m, nor_array=False)  # one tree shared by all M columns
    return case("tile_cols=M reduces popcount area vs tile_cols=1",
                rep_shared.popcount_um2 < rep_per_col.popcount_um2,
                f"per_col={rep_per_col.popcount_um2:.1f} shared={rep_shared.popcount_um2:.1f}")


def test_nor_array_uses_subcol_periph() -> bool:
    n, m = 256, 32
    pdk = synthetic_pdk()
    layer = make_layer(n, m)
    rep_pop = estimate_layer(layer, pdk, nor_array=False)
    rep_nor = estimate_layer(layer, pdk, nor_array=True, subcol_rows=64)
    # NOR-array peripheral is per-sub-column SA + decoder + precharge,
    # which for typical sizings is much smaller than the popcount tree.
    # Cell area is identical (NOR convention); only popcount differs.
    same_cells = math.isclose(rep_pop.cells_um2, rep_nor.cells_um2, rel_tol=1e-12)
    smaller_periph = rep_nor.popcount_um2 < rep_pop.popcount_um2
    return case("nor_array=True: same cell area, smaller peripheral",
                same_cells and smaller_periph,
                f"cells={rep_nor.cells_um2:.1f}; "
                f"pop={rep_pop.popcount_um2:.1f} -> nor={rep_nor.popcount_um2:.1f}")


def test_digital_readout_smaller_than_analog() -> bool:
    n, m = 256, 32
    pdk = synthetic_pdk()
    layer = make_layer(n, m)
    rep_analog  = estimate_layer(layer, pdk, subcol_rows=64, readout="analog")
    rep_digital = estimate_layer(layer, pdk, subcol_rows=64, readout="digital")
    # Same cells; the digital tier swaps the per-bitline comparator pair
    # (~160 gates) for sampler pairs (~13.6 gates, measured sampler32
    # anchor), so its peripheral must be well below the analog tier's.
    same_cells = math.isclose(rep_analog.cells_um2, rep_digital.cells_um2, rel_tol=1e-12)
    return case("readout='digital' peripheral < analog at same shape",
                same_cells and rep_digital.popcount_um2 < rep_analog.popcount_um2,
                f"analog={rep_analog.popcount_um2:.1f} digital={rep_digital.popcount_um2:.1f}")


def test_array_overhead_frac_applies() -> bool:
    n, m = 32, 16
    pdk_no_ovhd  = synthetic_pdk(array_overhead_frac=0.0)
    pdk_with     = synthetic_pdk(array_overhead_frac=0.2)
    layer = make_layer(n, m)
    rep_a = estimate_layer(layer, pdk_no_ovhd)
    rep_b = estimate_layer(layer, pdk_with)
    expected = (rep_b.cells_um2 + rep_b.popcount_um2) * 0.2
    return case("array_overhead_frac=0.2 contributes (cells+pop)*0.2",
                math.isclose(rep_b.array_overhead_um2, expected, rel_tol=1e-12)
                and math.isclose(rep_a.array_overhead_um2, 0.0, abs_tol=1e-9),
                f"with_ovhd={rep_b.array_overhead_um2:.2f} exp={expected:.2f}")


def main() -> int:
    print("estimate_layer area math:")
    results = [
        test_cell_count_nor_convention(),
        test_biroma_halves_cells(),
        test_active_cells_match_nonzeros(),
        test_tile_cols_shares_popcount_tree(),
        test_nor_array_uses_subcol_periph(),
        test_digital_readout_smaller_than_analog(),
        test_array_overhead_frac_applies(),
    ]
    n_ok = sum(1 for r in results if r)
    if n_ok == len(results):
        print(f"[ok] estimate_layer: {n_ok}/{len(results)} cases pass")
        return 0
    print(f"[FAIL] {n_ok}/{len(results)} cases pass")
    return 1


if __name__ == "__main__":
    sys.exit(main())
