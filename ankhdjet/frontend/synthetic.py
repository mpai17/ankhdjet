"""Synthetic-shape IR construction: a BitNet-class transformer's
matmul-resident layers from bare shape parameters, for estimator
sweeps and fit searches that need no checkpoint."""

from __future__ import annotations

from ankhdjet.frontend.hf import _zero_weight
from ankhdjet.frontend.ir import Layer, LayerType, ModelIR


def build_transformer_ir(
    hidden: int,
    layers: int,
    heads: int,
    head_dim: int,
    ffn_mult: int,
    vocab: int,
    name: str = "bitnet",
) -> ModelIR:
    """Construct a ModelIR with only the matmul layers that the CiROM
    arrays need to store. Each transformer block contributes:
        Q, K, V projections:  hidden -> heads*head_dim each
        Output projection:    heads*head_dim -> hidden
        FFN up:               hidden -> ffn_mult * hidden
        FFN down:             ffn_mult * hidden -> hidden
    Plus a final unembedding head: hidden -> vocab
    """
    ir_layers: list[Layer] = []

    def add(lname: str, n: int, m: int) -> None:
        ir_layers.append(Layer(
            name=lname, layer_type=LayerType.LINEAR,
            weights={"weight": _zero_weight()}, input_dim=n, output_dim=m,
        ))

    qkv_total = heads * head_dim
    for b in range(layers):
        add(f"b{b}_q",   hidden, qkv_total)
        add(f"b{b}_k",   hidden, qkv_total)
        add(f"b{b}_v",   hidden, qkv_total)
        add(f"b{b}_o",   qkv_total, hidden)
        add(f"b{b}_up",   hidden, ffn_mult * hidden)
        add(f"b{b}_down", ffn_mult * hidden, hidden)
    add("head", hidden, vocab)

    return ModelIR(name=name, layers=ir_layers)
