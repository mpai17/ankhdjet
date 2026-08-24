"""Ankhdjet compiler IR - data structures flowing through the pipeline.

Frontend produces IR from a trained ternary model. Backend consumes IR
to emit mask programs (.wmat chunks with manifests) and the structural
SystemVerilog that composes the rtl/ library.

The IR is precision-agnostic in principle (the same structures can carry
INT2/INT4-class cell encodings) but only ternary weights are supported.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import numpy as np


class LayerType(Enum):
    LINEAR = "linear"
    EMBEDDING = "embedding"
    LAYER_NORM = "layer_norm"
    ATTENTION = "attention"
    ACTIVATION = "activation"


class QuantScheme(Enum):
    TERNARY = "ternary"  # {-1, 0, +1}
    FLOAT = "float"      # unquantized (e.g. scale factors, layernorm params)


@dataclass
class WeightTensor:
    """One weight matrix with associated quantization metadata."""
    name: str
    data: np.ndarray                  # raw values: int8 for ternary, float for scales
    scheme: QuantScheme
    scale: np.ndarray | None = None   # per-tensor or per-channel scale factor (float)

    def __post_init__(self):
        if self.scheme == QuantScheme.TERNARY:
            vals = set(np.unique(self.data).tolist())
            if not vals.issubset({-1, 0, 1}):
                raise ValueError(
                    f"Ternary tensor {self.name!r} contains values outside "
                    f"{{-1,0,+1}}: {sorted(vals)}"
                )

    @property
    def shape(self) -> tuple[int, ...]:
        return self.data.shape

    @property
    def num_nonzero(self) -> int:
        return int(np.count_nonzero(self.data))


@dataclass
class Layer:
    """One layer of the network."""
    name: str
    layer_type: LayerType
    weights: dict[str, WeightTensor] = field(default_factory=dict)
    input_dim: int = 0
    output_dim: int = 0
    params: dict = field(default_factory=dict)  # e.g. num_heads, activation_fn

    def weight_count(self) -> int:
        return sum(w.data.size for w in self.weights.values())

    def ternary_weight_count(self) -> int:
        return sum(
            w.data.size for w in self.weights.values()
            if w.scheme == QuantScheme.TERNARY
        )


@dataclass
class ModelIR:
    """Complete model IR."""
    name: str
    layers: list[Layer] = field(default_factory=list)
    layer_order: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def total_ternary_weights(self) -> int:
        return sum(l.ternary_weight_count() for l in self.layers)

    def summary(self) -> str:
        lines = [f"Model: {self.name}"]
        lines.append(f"Layers: {len(self.layers)}")
        lines.append(f"Total ternary weights: {self.total_ternary_weights():,}")
        lines.append("")
        for layer in self.layers:
            lines.append(f"  {layer.name} [{layer.layer_type.value}]")
            for wname, wt in layer.weights.items():
                nnz = wt.num_nonzero
                total = wt.data.size
                sparsity = 100.0 * (1.0 - nnz / total) if total else 0.0
                lines.append(
                    f"    {wname}: {wt.shape} {wt.scheme.value}"
                    f" ({nnz:,}/{total:,} nonzero, {sparsity:.1f}% sparse)"
                )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self, path: str | Path) -> None:
        """Save the IR as `<path>.json` + `<path>.npz`.

        Weight arrays go to the npz; everything else (names, shapes, layer
        order, scale factors) goes to JSON.
        """
        path = Path(path)
        arrays: dict[str, np.ndarray] = {}
        layer_defs = []
        for layer in self.layers:
            wdefs = {}
            for wname, wt in layer.weights.items():
                key = f"{layer.name}__{wname}"
                arrays[key] = wt.data
                scale_serial = None
                if wt.scale is not None:
                    if isinstance(wt.scale, np.ndarray):
                        scale_serial = wt.scale.tolist()
                    else:
                        scale_serial = float(wt.scale)
                wdefs[wname] = {
                    "array_key": key,
                    "scheme": wt.scheme.value,
                    "scale": scale_serial,
                }
            layer_defs.append({
                "name": layer.name,
                "layer_type": layer.layer_type.value,
                "input_dim": layer.input_dim,
                "output_dim": layer.output_dim,
                "params": layer.params,
                "weights": wdefs,
            })
        meta = {
            "name": self.name,
            "layers": layer_defs,
            "layer_order": self.layer_order,
            "metadata": self.metadata,
        }
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        np.savez(path.with_suffix(".npz"), **arrays)

    @classmethod
    def load(cls, path: str | Path) -> "ModelIR":
        path = Path(path)
        meta = json.loads(path.with_suffix(".json").read_text())
        arrays = np.load(path.with_suffix(".npz"))

        layers: list[Layer] = []
        for ldef in meta["layers"]:
            weights = {}
            for wname, wdef in ldef["weights"].items():
                data = arrays[wdef["array_key"]]
                scale = wdef["scale"]
                if scale is not None and isinstance(scale, list):
                    scale = np.asarray(scale)
                weights[wname] = WeightTensor(
                    name=wname, data=data,
                    scheme=QuantScheme(wdef["scheme"]),
                    scale=scale,
                )
            layers.append(Layer(
                name=ldef["name"],
                layer_type=LayerType(ldef["layer_type"]),
                weights=weights,
                input_dim=ldef["input_dim"],
                output_dim=ldef["output_dim"],
                params=ldef.get("params", {}),
            ))
        return cls(
            name=meta["name"],
            layers=layers,
            layer_order=meta.get("layer_order", []),
            metadata=meta.get("metadata", {}),
        )
