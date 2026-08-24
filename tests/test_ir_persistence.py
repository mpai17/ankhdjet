"""Round-trip test for ModelIR.save / ModelIR.load."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.package


import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ankhdjet.frontend.ir import (
    Layer, LayerType, ModelIR, QuantScheme, WeightTensor,
)


def main() -> None:
    rng = np.random.default_rng(13)
    # Build a small ModelIR
    W1 = rng.choice([-1, 0, 1], size=(16, 8), p=[0.35, 0.3, 0.35]).astype(np.int64)
    W2 = rng.choice([-1, 0, 1], size=(8, 4), p=[0.35, 0.3, 0.35]).astype(np.int64)
    wt1 = WeightTensor(name="weight", data=W1, scheme=QuantScheme.TERNARY,
                       scale=np.float64(0.25))
    wt2 = WeightTensor(name="weight", data=W2, scheme=QuantScheme.TERNARY,
                       scale=np.float64(0.33))
    l1 = Layer(name="l0", layer_type=LayerType.LINEAR, weights={"weight": wt1},
               input_dim=16, output_dim=8)
    l2 = Layer(name="l1", layer_type=LayerType.LINEAR, weights={"weight": wt2},
               input_dim=8, output_dim=4)
    model = ModelIR(name="roundtrip", layers=[l1, l2],
                    metadata={"note": "test"})

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "model"
        model.save(path)
        assert path.with_suffix(".json").exists()
        assert path.with_suffix(".npz").exists()

        loaded = ModelIR.load(path)

    # Check equality
    assert loaded.name == model.name
    assert loaded.metadata == model.metadata
    assert len(loaded.layers) == len(model.layers)
    for a, b in zip(loaded.layers, model.layers):
        assert a.name == b.name
        assert a.input_dim == b.input_dim
        assert a.output_dim == b.output_dim
        assert a.layer_type == b.layer_type
        for wn in a.weights:
            wa, wb = a.weights[wn], b.weights[wn]
            assert np.array_equal(wa.data, wb.data)
            assert wa.scheme == wb.scheme
            assert float(wa.scale) == float(wb.scale)

    print("Round-trip OK")
    print(loaded.summary())


if __name__ == "__main__":
    main()
