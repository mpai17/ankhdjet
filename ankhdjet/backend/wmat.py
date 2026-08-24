"""Mask-program emitter: IR weights to the .wmat format.

The .wmat file is the mask-program source the array generators consume
(macro/sky130/gen_abstracts.py --weights-file, gen_macro_array_pc.tcl via
ANKHDJET_WEIGHTS_FILE): N_ROWS lines of N_COLS characters from {+, -, 0},
where row r is wordline r, column c is the weight column whose bitline
pair is BLP_c/BLN_c, '+' programs the cell's drain via to BLP (+1), '-'
to BLN (-1), and '0' leaves it floating (zero weight).

This is the bridge from the compiler IR to the physical weights path:
a compiled layer's mask program is emitted here, then the array/macro
generators turn it into the programmed GDS. Orientation matches the
compiler convention everywhere else (reference_nor, the tile RTL):
W[r, c] with r the activation/row index and c the output column.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ankhdjet.frontend.ir import Layer, QuantScheme

_TO_CHAR = {1: "+", -1: "-", 0: "0"}
_FROM_CHAR = {"+": 1, "-": -1, "0": 0}


def emit_wmat(W: np.ndarray, path: str | Path) -> Path:
    """Write a ternary weight matrix as a .wmat mask-program file.

    Args:
        W: (N, M) integer array with values in {-1, 0, +1}; row r is
           wordline r, column c is bitline pair c.
        path: output file path (created/overwritten).
    Returns:
        The path written.
    """
    W = np.asarray(W)
    if W.ndim != 2:
        raise ValueError(f"weight matrix must be 2-D, got shape {W.shape}")
    vals = set(np.unique(W).tolist())
    if not vals.issubset({-1, 0, 1}):
        raise ValueError(f"weights must be ternary, found values {sorted(vals)}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["".join(_TO_CHAR[int(w)] for w in row) for row in W]
    path.write_text("\n".join(lines) + "\n")
    return path


def emit_layer_wmat(layer: Layer, path: str | Path) -> Path:
    """Emit one IR LINEAR layer's ternary weight matrix as a .wmat file."""
    wt = layer.weights["weight"]
    if wt.scheme != QuantScheme.TERNARY:
        raise ValueError(f"layer {layer.name}: expected ternary, got {wt.scheme}")
    return emit_wmat(wt.data, path)


def load_wmat(path: str | Path) -> np.ndarray:
    """Parse a .wmat file back into an (N, M) int8 ternary matrix.

    Mirrors the array generators' parsing (blank lines skipped, one row
    per line); the round-trip with emit_wmat is exact.
    """
    rows: list[list[int]] = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append([_FROM_CHAR[ch] for ch in line])
        except KeyError as e:
            raise ValueError(f"invalid .wmat character {e.args[0]!r} in {path}") from None
    if not rows:
        raise ValueError(f"empty .wmat file: {path}")
    m = len(rows[0])
    if any(len(r) != m for r in rows):
        raise ValueError(f"ragged .wmat rows in {path}")
    return np.asarray(rows, dtype=np.int8)
