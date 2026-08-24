"""HuggingFace ternary-checkpoint loader.

Ingests any HuggingFace transformer checkpoint whose matmul weights are
ternary; BitNet b1.58 is the headline family, not a requirement. Two
entry points:
    load_config(repo_id)  -> ModelIR built from the published architecture
                             (config.json only, ~2 KB download)
    load_weights(repo_id) -> ModelIR with real ternary weights decoded
                             from the safetensors payload

The config-only path is enough for area + throughput reports, since the
area model reads only layer.input_dim / layer.output_dim. The full weight
path is needed for emission and bit-exact validation.

Weight storage formats, detected per tensor:
  - packed uint8 (the transformers bitnet convention): four ternary
    values per byte, lane i at bits [2i, 2i+1], encoded {0,1,2} - 1,
    with the per-tensor scale in a sibling ".weight_scale" tensor
  - ternary-valued float (bf16/fp16/fp32 storing exactly {-s, 0, +s},
    the unpacked convention of TriLM-class releases): sign() recovers
    the weights and s is the embedded scale
  - anything else is refused as non-ternary; for checkpoints that store
    QAT master weights (quantized at inference time), pass
    quantize="absmean" to apply the b1.58 transform
    (scale = mean|W|, W = clip(round(W/scale), -1, 1)) at load

The matmul-resident layers captured per transformer block use the
llama-family module naming shared by the known ternary releases
(BitNet, TriLM, Falcon-E, ternarized Llama):
  q_proj, k_proj, v_proj, o_proj                 (attention projections)
  gate_proj, up_proj, down_proj                  (SwiGLU/ReLU^2 MLP)
Plus a final lm_head (vocab projection). Attention compute itself
(softmax(QK^T/sqrt(d))V) is NOT a LINEAR layer and is handled separately
by a fixed-function ATTENTION_BLOCK in the area model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ankhdjet.frontend.ir import (
    Layer, LayerType, ModelIR, QuantScheme, WeightTensor,
)


@dataclass
class TransformerArch:
    """Subset of llama-family config.json fields used to build the IR."""
    hidden_size: int
    num_hidden_layers: int
    num_attention_heads: int
    head_dim: int
    num_key_value_heads: int
    intermediate_size: int
    vocab_size: int
    max_position_embeddings: int
    name: str = "model"

    @property
    def kv_dim(self) -> int:
        return self.num_key_value_heads * self.head_dim

    @property
    def qkv_dim(self) -> int:
        return self.num_attention_heads * self.head_dim


def _fetch_config(repo_id: str) -> dict:
    """Download just config.json from HuggingFace (~2 KB)."""
    from huggingface_hub import hf_hub_download
    path = hf_hub_download(repo_id=repo_id, filename="config.json")
    return json.loads(Path(path).read_text())


def parse_hf_config(cfg: dict, name: str = "model") -> TransformerArch:
    head_dim = cfg.get("head_dim")
    if head_dim is None:
        head_dim = cfg["hidden_size"] // cfg["num_attention_heads"]
    return TransformerArch(
        hidden_size=cfg["hidden_size"],
        num_hidden_layers=cfg["num_hidden_layers"],
        num_attention_heads=cfg["num_attention_heads"],
        head_dim=head_dim,
        num_key_value_heads=cfg.get("num_key_value_heads", cfg["num_attention_heads"]),
        intermediate_size=cfg["intermediate_size"],
        vocab_size=cfg["vocab_size"],
        max_position_embeddings=cfg.get("max_position_embeddings", 4096),
        name=name,
    )


def _zero_weight() -> WeightTensor:
    """Placeholder weight for area-only IR construction. The area model
    reads layer.input_dim / layer.output_dim only - never the data array -
    so a 1x1 dummy keeps memory bounded for multi-billion-parameter shapes."""
    return WeightTensor(name="weight", data=np.zeros((1, 1), dtype=np.int64),
                        scheme=QuantScheme.TERNARY)


def _warn_placeholder(layer_name: str, why: str) -> None:
    """Loudly flag a layer whose real weights could not be loaded: its
    dimensions stay correct (area/throughput reports are unaffected) but
    its data array is a 1x1 placeholder, so any weight-dependent consumer
    (emission, bit-exact validation) must not use this layer."""
    import warnings
    warnings.warn(
        f"{layer_name}: weights unavailable ({why}); keeping 1x1 placeholder "
        f"with scale=1.0 - dims are real, weight DATA is not",
        stacklevel=3,
    )


def build_ir_from_arch(arch: TransformerArch) -> ModelIR:
    """Construct a ModelIR with the matmul-resident LINEAR layers per block:
       q_proj, k_proj, v_proj (with GQA -> kv_dim, not full hidden),
       o_proj, gate_proj, up_proj, down_proj.
    Plus a final lm_head. Attention compute is handled separately."""
    layers: list[Layer] = []
    h = arch.hidden_size
    qkv = arch.qkv_dim
    kv = arch.kv_dim
    ff = arch.intermediate_size

    def add(lname: str, n: int, m: int) -> None:
        layers.append(Layer(
            name=lname, layer_type=LayerType.LINEAR,
            weights={"weight": _zero_weight()},
            input_dim=n, output_dim=m,
        ))

    for b in range(arch.num_hidden_layers):
        add(f"b{b}_q",     h, qkv)
        add(f"b{b}_k",     h, kv)         # GQA: K only num_key_value_heads * head_dim
        add(f"b{b}_v",     h, kv)
        add(f"b{b}_o",     qkv, h)
        add(f"b{b}_gate",  h, ff)
        add(f"b{b}_up",    h, ff)
        add(f"b{b}_down",  ff, h)
    add("lm_head", h, arch.vocab_size)

    return ModelIR(name=arch.name, layers=layers)


def load_config(repo_id: str = "microsoft/bitnet-b1.58-2B-4T") -> tuple[ModelIR, TransformerArch]:
    """Architecture-only IR from a HuggingFace config.json.

    No full safetensors download, no torch dependency. Sufficient for
    area + throughput reports. Use load_weights() for bit-exact validation.
    """
    cfg = _fetch_config(repo_id)
    arch = parse_hf_config(cfg, name=repo_id.split("/")[-1].replace("-", "_"))
    return build_ir_from_arch(arch), arch


def unpack_ternary_uint8(packed: np.ndarray) -> np.ndarray:
    """Unpack 4 ternary values from each uint8 byte (HF convention).

    Per transformers/integrations/bitnet.py: lane i fills a CONTIGUOUS block
    [i*N : (i+1)*N] of the output, NOT interleaved at element granularity.
    For a 1-D packed array of length N, the unpacked length is 4*N with
        out[i*N : (i+1)*N] = ((packed >> (2*i)) & 0x3) - 1

    For a 2-D packed tensor of shape (n_packed_rows, m), the unpacking
    happens along axis 0; output shape is (4*n_packed_rows, m).
    """
    p = np.asarray(packed, dtype=np.uint8)
    n = p.shape[0]
    out_shape = (n * 4,) + p.shape[1:]
    out = np.empty(out_shape, dtype=np.int8)
    for lane in range(4):
        out[lane * n : (lane + 1) * n] = ((p >> (2 * lane)) & 0x3).astype(np.int8) - 1
    return out


def decode_ternary(raw: np.ndarray) -> tuple[np.ndarray, float] | None:
    """Decode one stored weight tensor into (ternary int8 array, embedded
    scale), or None if the storage is not exactly ternary.

    uint8 input is treated as the packed 2-bit format (embedded scale 1.0;
    the per-tensor scale lives in a sibling tensor). Float input decodes
    when its distinct values are a subset of {-s, 0, +s} for a single
    s > 0: the weights are sign() and s is the embedded scale. Asymmetric
    or more-than-three-valued tensors return None.
    """
    if raw.dtype == np.uint8:
        return unpack_ternary_uint8(raw), 1.0
    vals = np.unique(raw)
    if vals.size > 3:
        return None
    pos = [float(v) for v in vals if v > 0]
    neg = [float(-v) for v in vals if v < 0]
    if len(pos) > 1 or len(neg) > 1:
        return None
    scales = set(pos) | set(neg)
    if not scales:  # all-zero tensor
        return np.zeros(raw.shape, dtype=np.int8), 1.0
    if len(scales) > 1:  # {-a, 0, +b} with a != b is not a scaled ternary
        return None
    return np.sign(raw).astype(np.int8), scales.pop()


def is_group_ternary(raw: np.ndarray, group: int = 128,
                     sample_rows: int = 8) -> bool:
    """Sampled test for group-scaled ternary storage: every length-`group`
    column segment of the sampled rows holds values in {-s, 0, +s} for a
    per-segment s. Used only to diagnose refusals precisely; the sign
    mask of such a tensor is recoverable, but a per-tensor scale cannot
    carry the scale grid."""
    if raw.ndim != 2 or raw.shape[1] < group:
        return False
    rows = raw[:: max(1, raw.shape[0] // sample_rows)][:sample_rows]
    for row in rows:
        for c0 in range(0, row.shape[0] - group + 1, group):
            u = np.unique(row[c0:c0 + group])
            pos = u[u > 0]
            neg = u[u < 0]
            if len(pos) > 1 or len(neg) > 1:
                return False
            if len(pos) and len(neg) and not np.isclose(
                    pos[0], -neg[0], rtol=1e-3):
                return False
    return True


def absmean_quantize(raw: np.ndarray) -> tuple[np.ndarray, float]:
    """The b1.58 inference-time transform for QAT master weights:
    scale = mean|W|, W = clip(round(W / scale), -1, +1)."""
    scale = float(np.abs(raw).mean())
    if scale == 0.0:
        return np.zeros(raw.shape, dtype=np.int8), 1.0
    W = np.clip(np.rint(raw / scale), -1, 1).astype(np.int8)
    return W, scale


def load_weights(repo_id: str = "microsoft/bitnet-b1.58-2B-4T",
                 progress: bool = True,
                 quantize: str | None = None,
                 ) -> tuple[ModelIR, TransformerArch, dict[str, float]]:
    """Full ternary-weight IR + per-tensor scales from the safetensors
    payload (downloaded via huggingface_hub.snapshot_download, cached in
    ~/.cache/huggingface/).

    Every stored tensor goes through the ternary decode ladder (packed
    uint8, then ternary-valued float); a tensor that is neither is kept
    as a loudly-flagged placeholder unless quantize="absmean" is passed,
    which applies the b1.58 inference-time transform to QAT master
    weights instead.

    Returns (model, arch, scales_by_layer) where scales_by_layer maps
    each layer name to its dequantization multiplier: W_effective =
    W_ternary * scale. Packed checkpoints store the transformers-bitnet
    sibling ".weight_scale", which that integration applies as a
    divisor; it is converted to the multiplier convention here, so the
    dict means one thing across storage formats.
    """
    import torch
    from huggingface_hub import snapshot_download
    from safetensors import safe_open

    if quantize not in (None, "absmean"):
        raise ValueError(f"unknown quantize mode {quantize!r}")

    snapshot = snapshot_download(
        repo_id=repo_id,
        allow_patterns=["*.safetensors", "*.json"],
    )
    snapshot_dir = Path(snapshot)

    cfg = json.loads((snapshot_dir / "config.json").read_text())
    arch = parse_hf_config(cfg, name=repo_id.split("/")[-1].replace("-", "_"))

    # Build the IR skeleton; we fill in real weights below.
    model = build_ir_from_arch(arch)
    by_name = {l.name: l for l in model.layers}

    # Map IR layer names back to the HF parameter prefixes so we can pull
    # the right stored weight + scale for each.
    # HF naming: model.layers.<i>.{self_attn,mlp}.<proj>.weight (+ .weight_scale)
    layer_to_hf: dict[str, tuple[str, int, int]] = {}
    for b in range(arch.num_hidden_layers):
        for proj, (n, m) in [
            (f"b{b}_q",    (arch.hidden_size, arch.qkv_dim)),
            (f"b{b}_k",    (arch.hidden_size, arch.kv_dim)),
            (f"b{b}_v",    (arch.hidden_size, arch.kv_dim)),
            (f"b{b}_o",    (arch.qkv_dim, arch.hidden_size)),
            (f"b{b}_gate", (arch.hidden_size, arch.intermediate_size)),
            (f"b{b}_up",   (arch.hidden_size, arch.intermediate_size)),
            (f"b{b}_down", (arch.intermediate_size, arch.hidden_size)),
        ]:
            tag = proj.split("_", 1)[1]
            sub = "self_attn" if tag in ("q", "k", "v", "o") else "mlp"
            hf_proj = f"{tag}_proj"
            layer_to_hf[proj] = (f"model.layers.{b}.{sub}.{hf_proj}", n, m)
    layer_to_hf["lm_head"] = ("lm_head", arch.hidden_size, arch.vocab_size)

    scales: dict[str, float] = {}
    safetensors_files = sorted(snapshot_dir.glob("*.safetensors"))
    if not safetensors_files:
        raise RuntimeError(f"no safetensors found under {snapshot_dir}")

    # Build a name -> file index from the safetensors metadata.
    name_to_file: dict[str, Path] = {}
    for sf in safetensors_files:
        with safe_open(sf, framework="pt") as f:
            for k in f.keys():
                name_to_file[k] = sf

    missing = [n for n, (p, _, _) in layer_to_hf.items()
               if n != "lm_head" and f"{p}.weight" not in name_to_file]
    if missing:
        raise RuntimeError(
            f"{repo_id}: {len(missing)} projection tensors not found under "
            f"llama-family naming (first: {missing[0]}); this architecture "
            f"is outside the frontend's naming map")

    n_done = 0
    n_total = len(layer_to_hf)
    for ir_name, (hf_prefix, n, m) in layer_to_hf.items():
        weight_key = f"{hf_prefix}.weight"
        scale_key = f"{hf_prefix}.weight_scale"
        if weight_key not in name_to_file:
            # Tied lm_head: try the embedding key. If that is missing too,
            # the head is aliased at runtime and never stored; keep a
            # placeholder since the area model only reads dimensions.
            if ir_name == "lm_head" and arch.vocab_size:
                alt = "model.embed_tokens.weight"
                if alt in name_to_file:
                    weight_key = alt
                    scale_key = "model.embed_tokens.weight_scale"
            if weight_key not in name_to_file:
                _warn_placeholder(ir_name, "not stored in safetensors (tied)")
                scales[ir_name] = 1.0
                n_done += 1
                continue

        with safe_open(name_to_file[weight_key], framework="pt") as f:
            t = f.get_tensor(weight_key)
            if t.dtype == torch.uint8:
                raw = t.cpu().numpy()
            else:
                raw = t.to(dtype=torch.float32).cpu().numpy()
            decoded = decode_ternary(raw)
            if decoded is None and quantize == "absmean":
                decoded = absmean_quantize(raw)
            if decoded is None:
                if is_group_ternary(raw):
                    why = (f"stored as group-scaled ternary ({t.dtype}); "
                           f"the sign mask is recoverable but per-tensor "
                           f"requantize cannot carry per-group scales")
                else:
                    why = (f"stored non-ternary ({t.dtype}); pass "
                           f"quantize='absmean' if this checkpoint holds "
                           f"QAT master weights")
                _warn_placeholder(ir_name, why)
                scales[ir_name] = 1.0
                n_done += 1
                continue
            W_out_in, embedded_scale = decoded
            # Stored layout is (out_features, in_features); transpose to
            # the IR convention (input_dim, output_dim).
            W = W_out_in.T.astype(np.int64)
            if W.shape != (n, m):
                raise RuntimeError(
                    f"{ir_name}: decoded shape {W.shape} != expected "
                    f"{(n, m)} from config.json")
            sibling_scale = 1.0
            if scale_key in name_to_file:
                with safe_open(name_to_file[scale_key], framework="pt") as g:
                    s_t = g.get_tensor(scale_key).flatten()
                    sibling_scale = float(
                        s_t[0].to(dtype=torch.float32).item())
            # The sibling tensor is a divisor in the transformers-bitnet
            # integration; the embedded float scale is a multiplier.
            scales[ir_name] = embedded_scale / sibling_scale

        layer = by_name[ir_name]
        layer.weights["weight"] = WeightTensor(
            name="weight", data=W, scheme=QuantScheme.TERNARY,
        )

        n_done += 1
        if progress and (n_done % 20 == 0 or n_done == n_total):
            print(f"  loaded {n_done}/{n_total} layers", flush=True)

    return model, arch, scales


def validate_unpack_against_transformers() -> None:
    """Round-trip check our unpack against transformers' own pack_weights /
    unpack_weights on a synthetic tensor. Catches packing-convention bugs
    in seconds without needing the full repo download."""
    import torch
    from transformers.integrations.bitnet import pack_weights, unpack_weights

    rng = np.random.default_rng(42)
    n_packed = 64  # -> n_unpacked = 256 along axis 0
    m = 8
    src = rng.choice([-1, 0, 1], size=(n_packed * 4, m), p=[0.35, 0.3, 0.35]).astype(np.int8)
    src_t = torch.from_numpy(src.astype(np.int64))

    # Pack via PyTorch's reference, unpack via our numpy implementation.
    packed_t = pack_weights(src_t.clone())
    packed_np = packed_t.cpu().numpy()
    rt = unpack_ternary_uint8(packed_np)
    if not np.array_equal(rt, src):
        mismatch = np.argwhere(rt != src)
        raise AssertionError(
            f"unpack mismatch vs transformers pack_weights in "
            f"{len(mismatch)} positions; first: rt={rt[tuple(mismatch[0])]} "
            f"src={src[tuple(mismatch[0])]}"
        )

    # And compare to transformers' own unpack to make sure they agree.
    pt_unpacked = unpack_weights(packed_t, dtype=torch.int8).cpu().numpy()
    if not np.array_equal(rt, pt_unpacked):
        raise AssertionError("our unpack disagrees with transformers.unpack_weights")

    print("unpack round-trip ok ({} x {} ternary values, "
          "matches transformers.pack_weights / unpack_weights)".format(*src.shape))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    validate_unpack_against_transformers()
    if len(sys.argv) > 1 and sys.argv[1] == "weights":
        repo = sys.argv[2] if len(sys.argv) > 2 else "microsoft/bitnet-b1.58-2B-4T"
        m, a, s = load_weights(repo)
        print(f"loaded {a.name}: {a.num_hidden_layers} layers, "
              f"{sum(L.input_dim*L.output_dim for L in m.layers)/1e6:.1f}M weights")
    else:
        m, a = load_config()
        print(f"config-only IR: {a}")
        print(f"  total LINEAR weights = "
              f"{sum(L.input_dim*L.output_dim for L in m.layers)/1e9:.3f}B")
