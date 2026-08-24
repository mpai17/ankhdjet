#!/usr/bin/env -S uv run python
"""Token-emitting architectural twin of the compiled BitNet fabric.

Runs a short greedy decode of microsoft/bitnet-b1.58-2B-4T three ways
and demands token-for-token agreement:

  ref    the transformers reference model (float32 compute so its
         integer matmuls are exact and comparable)
  numpy  a from-scratch forward pass: every ternary LINEAR as an exact
         integer matmul with BitLinear's per-token int8 activation
         quantization; norms/rotary/attention/relu^2 in float32
  arch   the same forward pass, but every ternary matmul computed in
         the fabric's decomposition: bit-serial activation planes over
         64-row subcolumn groups, signed activations offset-encoded
         onto the unsigned read fabric (W*q = W*(q+128) - 128*W*1),
         partial sums accumulated in readout order

`arch` is the architectural claim: the machine the compiler emits
(mask-programmed rows read group-by-group, bit-plane by bit-plane,
add/sub/skip accumulation) computes the model. Attention, norms,
rotary, sampling, and the bf16-tied lm_head run as documented
behavioral stages: they are the non-ternary 15% whose RTL is the next
project phase, and the checkpoint's lm_head is tied to the bf16
embedding table (NOT ternary), so it is computed off-fabric here and
accounted separately in any area claim.

Results persist to build/twin/<stamp>.log with pass/fail per token.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

MODEL_ID = "microsoft/bitnet-b1.58-2B-4T"
DEFAULT_PROMPT = "The future of computing is"
SUBCOL_ROWS = 64


# ---------------------------------------------------------------------------
# Checkpoint plumbing
# ---------------------------------------------------------------------------

def load_all_tensors():
    """Everything the twin needs, as numpy: ternary weights + scales via
    the compiler frontend, and the non-ternary tensors (embeddings, norm
    gains) straight from the safetensors."""
    import torch
    from safetensors import safe_open
    from huggingface_hub import snapshot_download

    from ankhdjet.frontend.hf import load_weights

    model_ir, arch, scales = load_weights(MODEL_ID, progress=False)
    tern = {l.name: l.weights["weight"].data for l in model_ir.layers}

    snap = Path(snapshot_download(MODEL_ID, allow_patterns=["*.safetensors", "*.json"]))
    extra: dict[str, np.ndarray] = {}
    for sf in sorted(snap.glob("*.safetensors")):
        with safe_open(sf, framework="pt") as f:
            for k in f.keys():
                if ("layernorm" in k or k.endswith("norm.weight")
                        or "sub_norm" in k or k == "model.embed_tokens.weight"):
                    extra[k] = f.get_tensor(k).to(torch.float32).numpy()
    return arch, tern, scales, extra


# ---------------------------------------------------------------------------
# BitLinear pieces (exact per transformers/integrations/bitnet.py)
# ---------------------------------------------------------------------------

def act_quant(x: np.ndarray):
    """Per-token symmetric int8: scale = 127/absmax, round, clamp."""
    scale = 127.0 / np.clip(np.abs(x).max(axis=-1, keepdims=True), 1e-5, None)
    q = np.clip(np.round(x * scale), -128, 127).astype(np.int32)
    return q, scale


def linear_numpy(q: np.ndarray, W: np.ndarray) -> np.ndarray:
    """Exact integer matmul, (tokens, in) @ (in, out)."""
    return q.astype(np.int64) @ W.astype(np.int64)


def linear_arch(q: np.ndarray, W: np.ndarray) -> np.ndarray:
    """The fabric's decomposition, integer-exact:
    offset-encode signed q to unsigned u = q + 128 (8-bit), then for each
    64-row subcolumn group and each activation bit plane, accumulate
    (plane @ Wpos - plane @ Wneg) << k in readout order; finally subtract
    the offset term 128 * (column sums)."""
    n, m = W.shape
    Wpos = (W == 1).astype(np.int64)
    Wneg = (W == -1).astype(np.int64)
    colsum = (Wpos - Wneg).sum(axis=0)          # W^T . 1, per column
    u = (q + 128).astype(np.int64)              # unsigned 8-bit planes
    acc = np.zeros((q.shape[0], m), dtype=np.int64)
    for g0 in range(0, n, SUBCOL_ROWS):
        g1 = min(g0 + SUBCOL_ROWS, n)
        for k in range(8):
            plane = (u[:, g0:g1] >> k) & 1
            acc += (plane @ Wpos[g0:g1] - plane @ Wneg[g0:g1]) << k
    return acc - 128 * colsum[None, :]


# ---------------------------------------------------------------------------
# Model forward (numpy, float32 outside the integer matmuls)
# ---------------------------------------------------------------------------

def rms_norm(x, w, eps):
    v = np.mean(x.astype(np.float32) ** 2, axis=-1, keepdims=True)
    return (x * (1.0 / np.sqrt(v + eps))) * w


def rotate_half(x):
    h = x.shape[-1] // 2
    return np.concatenate([-x[..., h:], x[..., :h]], axis=-1)


def rope(q, k, pos, theta, head_dim):
    inv = 1.0 / (theta ** (np.arange(0, head_dim, 2, dtype=np.float64) / head_dim))
    ang = np.outer(pos, inv)
    cos = np.cos(ang).astype(np.float32)
    sin = np.sin(ang).astype(np.float32)
    cos = np.concatenate([cos, cos], axis=-1)[None, :, None, :]
    sin = np.concatenate([sin, sin], axis=-1)[None, :, None, :]
    # shapes: (1, T, 1, D) applied to (T, H, D) batches broadcast below
    qe = q * cos[0] + rotate_half(q) * sin[0]
    ke = k * cos[0] + rotate_half(k) * sin[0]
    return qe, ke


class Twin:
    def __init__(self, exec_mode: str):
        self.exec_mode = exec_mode
        self.matmul_checks = 0
        (self.arch_cfg, self.tern, self.scales, self.extra) = load_all_tensors()
        self.h = self.arch_cfg.hidden_size
        self.heads = self.arch_cfg.num_attention_heads
        self.kvh = self.arch_cfg.num_key_value_heads
        self.hd = self.arch_cfg.head_dim
        self.blocks = self.arch_cfg.num_hidden_layers
        from transformers import AutoConfig
        cfg = AutoConfig.from_pretrained(MODEL_ID)
        self.eps = cfg.rms_norm_eps
        self.theta = getattr(cfg, "rope_theta", 500000.0)
        self.embed = self.extra["model.embed_tokens.weight"]  # (vocab, h) f32

    def bitlinear(self, x: np.ndarray, name: str) -> np.ndarray:
        W = self.tern[name]                      # (in, out) int8 ternary
        wscale = self.scales[name]               # dequant multiplier
        q, ascale = act_quant(x)
        if self.exec_mode == "arch":
            y = linear_arch(q, W)
            if self.matmul_checks < 4:           # spot-prove arch == plain
                assert np.array_equal(y, linear_numpy(q, W)), name
                self.matmul_checks += 1
        else:
            y = linear_numpy(q, W)
        return y.astype(np.float32) * wscale / ascale

    def block(self, b: int, x: np.ndarray, pos: np.ndarray) -> np.ndarray:
        e = self.extra
        pre = f"model.layers.{b}."
        hin = rms_norm(x, e[pre + "input_layernorm.weight"], self.eps)
        T = x.shape[0]
        qp = self.bitlinear(hin, f"b{b}_q").reshape(T, self.heads, self.hd)
        kp = self.bitlinear(hin, f"b{b}_k").reshape(T, self.kvh, self.hd)
        vp = self.bitlinear(hin, f"b{b}_v").reshape(T, self.kvh, self.hd)
        qp, kp = rope(qp, kp, pos, self.theta, self.hd)
        rep = self.heads // self.kvh
        kf = np.repeat(kp, rep, axis=1)          # (T, H, D)
        vf = np.repeat(vp, rep, axis=1)
        scores = np.einsum("thd,shd->hts", qp, kf) / np.sqrt(self.hd)
        mask = np.triu(np.full((T, T), -np.inf, dtype=np.float32), k=1)
        scores = scores + mask[None, :, :]
        scores -= scores.max(axis=-1, keepdims=True)
        p = np.exp(scores)
        p /= p.sum(axis=-1, keepdims=True)
        attn = np.einsum("hts,shd->thd", p, vf).reshape(T, self.h)
        attn = rms_norm(attn, e[pre + "self_attn.attn_sub_norm.weight"], self.eps)
        x = x + self.bitlinear(attn, f"b{b}_o")

        hin2 = rms_norm(x, e[pre + "post_attention_layernorm.weight"], self.eps)
        g = self.bitlinear(hin2, f"b{b}_gate")
        u = self.bitlinear(hin2, f"b{b}_up")
        act = np.square(np.maximum(g, 0.0)) * u   # relu^2 gate
        act = rms_norm(act, e[pre + "mlp.ffn_sub_norm.weight"], self.eps)
        x = x + self.bitlinear(act, f"b{b}_down")
        return x

    def forward_logits(self, ids: list[int]) -> np.ndarray:
        x = self.embed[np.asarray(ids)]
        pos = np.arange(len(ids))
        for b in range(self.blocks):
            x = self.block(b, x, pos)
        x = rms_norm(x, self.extra["model.norm.weight"], self.eps)
        # lm_head is TIED to the bf16 embedding table in this checkpoint
        # (not ternary): computed off-fabric, accounted separately.
        return x[-1] @ self.embed.T

    def generate(self, prompt_ids: list[int], n_new: int) -> list[int]:
        ids = list(prompt_ids)
        out = []
        for i in range(n_new):
            t0 = time.time()
            nxt = int(np.argmax(self.forward_logits(ids)))
            ids.append(nxt)
            out.append(nxt)
            print(f"  [{self.exec_mode}] token {i+1}/{n_new}: {nxt} "
                  f"({time.time()-t0:.1f}s)", flush=True)
        return out


def run_reference(prompt: str, n_new: int) -> list[int]:
    """Reference decode via transformers' own BitLinear modules,
    assembled manually: transformers 5.13's from_pretrained conversion
    path fails on this checkpoint (BitNetDeserialize errors), so the
    model skeleton is built from config, Linears replaced with the
    integrations' BitLinear, and the raw safetensors loaded directly
    (BitLinear unpacks packed ternary in _load_from_state_dict).
    Float32 activations keep the integer matmuls exact."""
    import torch
    from safetensors import safe_open
    from huggingface_hub import snapshot_download
    from transformers import AutoConfig, AutoTokenizer
    from transformers.models.bitnet.modeling_bitnet import BitNetForCausalLM
    from transformers.integrations.bitnet import replace_with_bitnet_linear

    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    cfg = AutoConfig.from_pretrained(MODEL_ID)
    quant_cfg = cfg.quantization_config
    if not isinstance(quant_cfg, dict):
        quant_cfg = None
    del cfg.quantization_config
    model = BitNetForCausalLM(cfg)
    model = replace_with_bitnet_linear(
        model, modules_to_not_convert=["lm_head"])
    snap = Path(snapshot_download(MODEL_ID,
                                  allow_patterns=["*.safetensors", "*.json"]))
    sd = {}
    for sf in sorted(snap.glob("*.safetensors")):
        with safe_open(sf, framework="pt") as f:
            for k in f.keys():
                sd[k] = f.get_tensor(k)
    missing, unexpected = model.load_state_dict(sd, strict=False)
    missing = [m for m in missing if "rotary" not in m and m != "lm_head.weight"]
    assert not missing, f"missing keys: {missing[:8]}"
    if hasattr(model, "tie_weights"):
        model.tie_weights()
    model = model.float()
    model.eval()
    ids = tok(prompt, return_tensors="pt").input_ids
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=n_new, do_sample=False,
                             use_cache=True)
    return out[0, ids.shape[1]:].tolist()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["ref", "numpy", "arch", "all"],
                    default="all")
    ap.add_argument("--tokens", type=int, default=8)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    args = ap.parse_args()

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    prompt_ids = tok(args.prompt).input_ids

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = REPO / "build" / "twin"
    outdir.mkdir(parents=True, exist_ok=True)
    log = outdir / f"twin_{stamp}.log"
    lines = [f"twin run {stamp}  prompt={args.prompt!r}  n={args.tokens}"]

    results: dict[str, list[int]] = {}
    modes = (["ref", "numpy", "arch"] if args.mode == "all" else [args.mode])
    for m in modes:
        print(f"== {m}", flush=True)
        t0 = time.time()
        if m == "ref":
            results[m] = run_reference(args.prompt, args.tokens)
        else:
            results[m] = Twin(m).generate(prompt_ids, args.tokens)
        dt = time.time() - t0
        text = tok.decode(results[m])
        lines.append(f"{m:6s} {dt:8.1f}s  ids={results[m]}  text={text!r}")
        print(f"   -> {results[m]}  {text!r}", flush=True)

    verdict = "PASS"
    if "ref" in results:
        for m in results:
            if results[m] != results["ref"]:
                verdict = f"FAIL ({m} != ref)"
    lines.append(f"RESULT: {verdict}")
    log.write_text("\n".join(lines) + "\n")
    print(f"RESULT: {verdict}\nlogged -> {log.relative_to(REPO)}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
