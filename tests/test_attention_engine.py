"""Unit tests for ankhdjet/attention_engine.py size_attention sizing math.

Pins the first-principles formula:
    parallel_mul = ceil(2 * head_dim * n_heads * kv_context / t_matmul)
    area = (parallel_mul * FP16_MUL_GATES * PIPELINE_OVERHEAD
            + parallel_mul * ACCUMULATOR_GATES_PER_LANE
            + SOFTMAX_LUT_GATES) * gate_um2
plus the documented edge cases (t_matmul=0 falls back to one multiplier
per head; kv_context=0 is treated as 1).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.package


import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.estimate.attention_engine import (
    ACCUMULATOR_GATES_PER_LANE,
    FP16_MUL_GATES,
    PIPELINE_OVERHEAD,
    SOFTMAX_LUT_GATES,
    size_attention,
)


def _expected_area(parallel_mul: int, gate_um2: float) -> float:
    mul_gates = parallel_mul * FP16_MUL_GATES * PIPELINE_OVERHEAD
    acc_gates = parallel_mul * ACCUMULATOR_GATES_PER_LANE
    return (mul_gates + acc_gates + SOFTMAX_LUT_GATES) * gate_um2


def case(label: str, *, head_dim: int, n_heads: int, kv: int,
         t_matmul: int, gate_um2: float,
         exp_parallel: int) -> bool:
    s = size_attention(head_dim=head_dim, n_heads=n_heads,
                       kv_context_tokens=kv, t_matmul_cycles=t_matmul,
                       gate_um2=gate_um2)
    ok = (s.parallel_mul == exp_parallel
          and s.cycles_per_layer_per_token == t_matmul
          and math.isclose(s.area_um2, _expected_area(exp_parallel, gate_um2),
                           rel_tol=1e-12))
    marker = "ok" if ok else "FAIL"
    print(f"  [{marker}] {label}: parallel_mul={s.parallel_mul} (exp {exp_parallel}), "
          f"area={s.area_um2:.1f} um^2")
    if not ok:
        print(f"        cycles={s.cycles_per_layer_per_token} (exp {t_matmul})")
        print(f"        area  ={s.area_um2}")
        print(f"        exp   ={_expected_area(exp_parallel, gate_um2)}")
    return ok


def main() -> int:
    print("size_attention sizing math:")
    results: list[bool] = []

    # bitnet b1.58-2B-4T: head_dim=128, n_heads=20, kv=4096
    # macs = 2 * 128 * 20 * 4096 = 20971520
    # at t_matmul = 2151 cyc -> parallel_mul = ceil(20971520 / 2151) = 9750
    results.append(case("bitnet 2B kv4096 t_matmul=2151",
                        head_dim=128, n_heads=20, kv=4096,
                        t_matmul=2151, gate_um2=1.0,
                        exp_parallel=math.ceil(2 * 128 * 20 * 4096 / 2151)))

    # smaller workload
    results.append(case("smolLM-class kv512 t_matmul=512",
                        head_dim=64, n_heads=12, kv=512,
                        t_matmul=512, gate_um2=2.5,
                        exp_parallel=math.ceil(2 * 64 * 12 * 512 / 512)))

    # exact-divide case
    results.append(case("exact-divide t_matmul matches macs",
                        head_dim=8, n_heads=4, kv=10,
                        t_matmul=2 * 8 * 4 * 10,
                        gate_um2=1.0,
                        exp_parallel=1))

    # tiny case
    results.append(case("trivial single-head single-token",
                        head_dim=1, n_heads=1, kv=1,
                        t_matmul=1, gate_um2=1.0,
                        exp_parallel=2))  # macs = 2

    # degenerate t_matmul=0 -> one mul per head
    results.append(case("degenerate t_matmul=0",
                        head_dim=64, n_heads=8, kv=128,
                        t_matmul=0, gate_um2=1.0,
                        exp_parallel=8))

    # kv_context=0 should be coerced to 1 (max(1, kv) inside)
    results.append(case("kv_context=0 (coerced to 1)",
                        head_dim=8, n_heads=2, kv=0,
                        t_matmul=10, gate_um2=1.0,
                        exp_parallel=math.ceil(2 * 8 * 2 * 1 / 10)))

    # area scaling: doubling parallel_mul should add (almost) twice the
    # multiplier+accumulator gates while the softmax LUT stays constant.
    s_small = size_attention(head_dim=8, n_heads=2, kv_context_tokens=10,
                              t_matmul_cycles=20, gate_um2=1.0)
    s_big   = size_attention(head_dim=8, n_heads=2, kv_context_tokens=10,
                              t_matmul_cycles=10, gate_um2=1.0)
    expected_small = _expected_area(s_small.parallel_mul, 1.0)
    expected_big   = _expected_area(s_big.parallel_mul,   1.0)
    diff = s_big.area_um2 - s_small.area_um2
    expected_diff = expected_big - expected_small
    ok = math.isclose(diff, expected_diff, rel_tol=1e-12)
    marker = "ok" if ok else "FAIL"
    print(f"  [{marker}] area scaling halving t_matmul: "
          f"parallel {s_small.parallel_mul} -> {s_big.parallel_mul}, "
          f"d_area={diff:.1f} um^2 (exp {expected_diff:.1f})")
    results.append(ok)

    n_ok = sum(1 for r in results if r)
    if n_ok == len(results):
        print(f"[ok] size_attention: {n_ok}/{len(results)} sizing cases pass")
        return 0
    print(f"[FAIL] {n_ok}/{len(results)} cases pass")
    return 1


if __name__ == "__main__":
    sys.exit(main())
