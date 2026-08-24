"""Validate our HF unpack + ternary_matmul against PyTorch's BitLinear.

Independence proof for the correctness chain. Without this, the existing
RTL <-> ankhdjet.reference.ternary_matmul test only proves both halves
of OUR code agree. Here we compare our unpack + integer matmul to
transformers.integrations.bitnet.unpack_weights + F.linear on the actual
Microsoft BitNet weights, on a single tensor that lands deterministically
on disk after `python -m ankhdjet.frontend.hf weights`.

Skipped (with a clear message) if the safetensors cache isn't populated.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.frontend.hf import load_weights


def _hf_cache_has_repo(repo_id: str) -> bool:
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    target = cache / "hub" / ("models--" + repo_id.replace("/", "--"))
    return target.exists() and any(target.rglob("*.safetensors"))


def main() -> int:
    repo_id = "microsoft/bitnet-b1.58-2B-4T"
    if not _hf_cache_has_repo(repo_id):
        print(f"[skip] {repo_id} not in HF cache; "
              f"run `uv run python -m ankhdjet.frontend.hf weights` first.")
        return 0

    import torch
    from transformers.integrations.bitnet import unpack_weights as ref_unpack
    from safetensors import safe_open

    # Locate the safetensors file fresh, do a direct apples-to-apples comparison
    # against PyTorch's reference unpack + F.linear on a single layer.
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    snapshot_dir = next(
        (cache / "hub" / ("models--" + repo_id.replace("/", "--"))).rglob("model.safetensors")
    ).parent

    # Pick layer 0's q_proj for the comparison.
    weight_key = "model.layers.0.self_attn.q_proj.weight"
    with safe_open(snapshot_dir / "model.safetensors", framework="pt") as f:
        packed_t = f.get_tensor(weight_key)
    pt_unpacked = ref_unpack(packed_t, dtype=torch.int8).cpu().numpy()

    # Our load_weights goes through the full IR + unpack path; pull the
    # corresponding layer ("b0_q") and compare its matrix to PyTorch's.
    print(f"Loading {repo_id} via our HF loader ...", flush=True)
    model, arch, scales = load_weights(repo_id, progress=False)
    ours = next(L for L in model.layers if L.name == "b0_q").weights["weight"].data
    # Our IR stores (in, out) = (hidden, qkv_dim). PyTorch stores (out, in).
    ours_oi = ours.T.astype(np.int8)

    if ours_oi.shape != pt_unpacked.shape:
        print(f"[FAIL] shape mismatch: ours={ours_oi.shape} pt={pt_unpacked.shape}")
        return 1

    if not np.array_equal(ours_oi, pt_unpacked):
        n_diff = int(np.sum(ours_oi != pt_unpacked))
        print(f"[FAIL] unpacked weight matrices disagree in {n_diff:,} positions "
              f"(out of {ours_oi.size:,})")
        return 1
    print(f"  unpacked matrices agree on {ours_oi.size:,} positions "
          f"(b0_q: {arch.hidden_size} x {arch.qkv_dim})")

    # Now drive an identical activation through PyTorch's F.linear and our
    # ternary_matmul. Skip BitLinear's RMSNorm + activation_quant + scale
    # (those are independent ops we don't claim to model in the matmul step);
    # the comparison is on the linear matmul ONLY.
    from ankhdjet.reference.mac import ternary_matmul

    rng = np.random.default_rng(0x123)
    k_bits = 8
    x = rng.integers(0, 1 << k_bits, size=arch.hidden_size, dtype=np.int64)
    expected = ternary_matmul(ours, x, k_bits=k_bits)

    # PyTorch path: w_quant @ x via F.linear (out = w @ x for 1D x)
    w_quant_t = torch.from_numpy(pt_unpacked.astype(np.int64))
    x_t = torch.from_numpy(x.astype(np.int64))
    pt_y = (w_quant_t.to(torch.int64) @ x_t).cpu().numpy()

    if not np.array_equal(expected, pt_y):
        n_diff = int(np.sum(expected != pt_y))
        print(f"[FAIL] our ternary_matmul disagrees with PyTorch F.linear "
              f"in {n_diff} of {expected.size} outputs; "
              f"first three: ours={expected[:3]} pt={pt_y[:3]}")
        return 1
    print(f"  ternary_matmul output matches PyTorch F.linear "
          f"on all {expected.size} positions")
    print("[ok] microsoft/bitnet-b1.58-2B-4T b0_q: HF unpack + "
          "ternary_matmul bit-exact vs transformers + torch.F.linear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
