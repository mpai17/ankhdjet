"""Unit tests for ankhdjet/throughput_calibration.py.

Pins:
  load_silicon_points  -> non-empty list with the expected schema fields
  _min_area_for_point  -> documented carve-outs (advanced nodes + CTS+STA tag)
  fit_alpha_from_silicon -> closed-form alpha math + percentile bracketing

Uses synthetic fixtures so the test stays valid even as the curated yaml
evolves; also runs the real loader once as a smoke check.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.package


import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.estimate.throughput_calibration import (
    SiliconPoint,
    _min_area_for_point,
    fit_alpha_from_silicon,
    load_silicon_points,
)


def case(label: str, ok: bool, detail: str = "") -> bool:
    marker = "ok" if ok else "FAIL"
    print(f"  [{marker}] {label}" + (f"  {detail}" if detail else ""))
    return ok


def test_load_silicon_points() -> bool:
    pts = load_silicon_points()
    if not pts:
        return case("load_silicon_points returns >= 1 entry", False, "empty list")
    pt = pts[0]
    # YAML round-trip leaves numeric fields as int when the source has no
    # decimal point (e.g. `process_nm: 130`); the fit code coerces with
    # float() before arithmetic, so accept either numeric type here.
    fields = (isinstance(pt.process_nm, (int, float))
              and isinstance(pt.area_mm2, (int, float))
              and isinstance(pt.achieved_fmax_mhz, (int, float))
              and isinstance(pt.name, str)
              and isinstance(pt.source, str))
    return case(f"load_silicon_points returns {len(pts)} entries with valid schema",
                fields)


def test_min_area_carveouts() -> bool:
    # Advanced node carve-out: 7 nm point under 1 mm^2 should be admitted
    p_advanced = SiliconPoint(process_nm=7.0, area_mm2=0.001,
                              achieved_fmax_mhz=2000.0,
                              name="x", source="some 7nm source")
    ok_adv = _min_area_for_point(p_advanced, 1.0) == 1e-5

    # CTS+STA tag carve-out: small SKY130 point with the magic source string
    p_cts = SiliconPoint(process_nm=130.0, area_mm2=0.05,
                         achieved_fmax_mhz=300.0,
                         name="y", source="OpenROAD CTS+STA local")
    ok_cts = _min_area_for_point(p_cts, 1.0) == 1e-5

    # Default applies otherwise
    p_default = SiliconPoint(process_nm=130.0, area_mm2=0.05,
                             achieved_fmax_mhz=300.0,
                             name="z", source="signoff-not-silicon")
    ok_def = _min_area_for_point(p_default, 1.0) == 1.0

    return case("_min_area_for_point: advanced + CTS+STA carve-outs",
                ok_adv and ok_cts and ok_def,
                f"adv={ok_adv} cts={ok_cts} default={ok_def}")


def test_fit_alpha_synthetic_single() -> bool:
    # Single point, ideal=400, area=4 mm^2, achieved=200 MHz
    # -> alpha = (400/200 - 1) / sqrt(4) = 1.0 / 2 = 0.5
    pt = SiliconPoint(process_nm=130.0, area_mm2=4.0,
                      achieved_fmax_mhz=200.0,
                      name="syn1", source="synthetic")
    out = fit_alpha_from_silicon([pt], target_clock_mhz={130.0: 400.0})
    if 130.0 not in out:
        return case("single-point alpha fit", False, "no node 130 in output")
    knob = out[130.0]
    ok_mid = math.isclose(knob.mid, 0.5, rel_tol=1e-9)
    # Single-point case widens to 0.5x mid / 2.0x mid
    ok_low  = math.isclose(knob.low,  0.25, rel_tol=1e-9)
    ok_high = math.isclose(knob.high, 1.0,  rel_tol=1e-9)
    ok_tag = any("_low_confidence" in s for s in knob.sources)
    return case("single-point alpha = 0.5 with low-confidence widening",
                ok_mid and ok_low and ok_high and ok_tag,
                f"mid={knob.mid} low={knob.low} high={knob.high}")


def test_fit_alpha_synthetic_multi() -> bool:
    # Four synthetic points at the same node with alpha = {0.1, 0.3, 0.5, 0.7}
    # ideal=1000, area=1 mm^2 -> achieved = 1000/(1+alpha)
    target = 1000.0
    alphas = [0.1, 0.3, 0.5, 0.7]
    pts = []
    for i, a in enumerate(alphas):
        achieved = target / (1.0 + a)
        pts.append(SiliconPoint(process_nm=130.0, area_mm2=1.0,
                                 achieved_fmax_mhz=achieved,
                                 name=f"syn_a{i}", source="synthetic"))
    out = fit_alpha_from_silicon(pts, target_clock_mhz={130.0: target})
    knob = out.get(130.0)
    if knob is None:
        return case("multi-point alpha fit", False, "no node 130")
    # n=4 -> 25th=index 1 (0.3), median=index 2 (0.5), 75th=index 3 (0.7)
    ok_mid  = math.isclose(knob.mid,  0.5, rel_tol=1e-9)
    ok_low  = math.isclose(knob.low,  0.3, rel_tol=1e-9)
    ok_high = math.isclose(knob.high, 0.7, rel_tol=1e-9)
    ok_no_tag = not any("_low_confidence" in s for s in knob.sources)
    return case("multi-point alpha bracket = (0.3, 0.5, 0.7)",
                ok_mid and ok_low and ok_high and ok_no_tag,
                f"mid={knob.mid} low={knob.low} high={knob.high}")


def test_fit_alpha_clips_negative() -> bool:
    # Achieved >= ideal -> alpha clips to 0
    pt = SiliconPoint(process_nm=130.0, area_mm2=4.0,
                      achieved_fmax_mhz=500.0,
                      name="fast", source="synthetic")
    out = fit_alpha_from_silicon([pt], target_clock_mhz={130.0: 400.0})
    knob = out.get(130.0)
    if knob is None:
        return case("alpha clips to 0 when achieved>=ideal", False, "no node")
    return case("alpha clips to 0 when achieved>=ideal",
                knob.mid == 0.0,
                f"mid={knob.mid}")


def main() -> int:
    print("throughput_calibration unit tests:")
    results = [
        test_load_silicon_points(),
        test_min_area_carveouts(),
        test_fit_alpha_synthetic_single(),
        test_fit_alpha_synthetic_multi(),
        test_fit_alpha_clips_negative(),
    ]
    n_ok = sum(1 for r in results if r)
    if n_ok == len(results):
        print(f"[ok] throughput_calibration: {n_ok}/{len(results)} cases pass")
        return 0
    print(f"[FAIL] {n_ok}/{len(results)} cases pass")
    return 1


if __name__ == "__main__":
    sys.exit(main())
