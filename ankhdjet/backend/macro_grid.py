"""Full-model macro-grid emission: every ternary layer as a tiled set
of mask-programmed array macros.

This is the model-to-silicon tiling bridge: each LINEAR layer's
(rows x cols) ternary matrix is tiled into macro_rows x macro_cols
chunks (zero-padded at the ragged edges: a padded position is a
floating drain, exactly a zero weight), and each chunk's mask program
is emitted in the array generators' .wmat format. A per-layer manifest
records the grid geometry, padding, and per-chunk digests; a model
manifest records totals. The grid readout/accumulation RTL emitter
(ankhdjet.backend.grid_rtl) composes these chunks into full-layer
reads; the physical story per slice is anchored by
tools/openroad/run_asap7_block.sh.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from ankhdjet.backend._pool import run_ordered
from ankhdjet.backend.wmat import emit_wmat
from ankhdjet.frontend.ir import Layer, ModelIR, QuantScheme


@dataclass
class GridManifest:
    layer: str
    rows: int
    cols: int
    macro_rows: int
    macro_cols: int
    grid_r: int
    grid_c: int
    n_macros: int
    weights: int
    padded_positions: int
    wmat_bytes: int


def emit_layer_grid(layer: Layer, out_dir: Path | str,
                    macro_rows: int = 64, macro_cols: int = 256,
                    write_wmat: bool = True) -> GridManifest:
    """Tile one LINEAR layer into macro chunks and emit their mask
    programs as `<out_dir>/<layer>/r{i}_c{j}.wmat`."""
    wt = layer.weights["weight"]
    if wt.scheme != QuantScheme.TERNARY:
        raise ValueError(f"{layer.name}: expected ternary, got {wt.scheme}")
    W = np.asarray(wt.data, dtype=np.int8)
    n, m = W.shape
    gr = -(-n // macro_rows)
    gc = -(-m // macro_cols)
    out = Path(out_dir) / layer.name
    chunk_digests = {}
    wmat_bytes = 0
    for i in range(gr):
        r0, r1 = i * macro_rows, min((i + 1) * macro_rows, n)
        for j in range(gc):
            c0, c1 = j * macro_cols, min((j + 1) * macro_cols, m)
            chunk = np.zeros((macro_rows, macro_cols), dtype=np.int8)
            chunk[: r1 - r0, : c1 - c0] = W[r0:r1, c0:c1]
            if write_wmat:
                p = emit_wmat(chunk, out / f"r{i}_c{j}.wmat")
                data = p.read_bytes()
            else:
                data = b"\n".join(
                    bytes("".join({1: "+", -1: "-", 0: "0"}[int(v)] for v in row),
                          "ascii") for row in chunk) + b"\n"
            wmat_bytes += len(data)
            chunk_digests[f"r{i}_c{j}"] = hashlib.sha256(data).hexdigest()[:16]
    man = GridManifest(
        layer=layer.name, rows=n, cols=m,
        macro_rows=macro_rows, macro_cols=macro_cols,
        grid_r=gr, grid_c=gc, n_macros=gr * gc,
        weights=n * m,
        padded_positions=gr * gc * macro_rows * macro_cols - n * m,
        wmat_bytes=wmat_bytes,
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(
        {**asdict(man), "chunks_sha256_16": chunk_digests}, indent=1))
    return man


def emit_model(model: ModelIR, out_dir: Path | str,
               macro_rows: int = 64, macro_cols: int = 256,
               write_wmat: bool = True,
               skip_layers: tuple[str, ...] = (),
               progress=None, jobs: int | None = None) -> dict:
    """Emit every ternary layer's macro grid; return the model manifest.

    Layers whose weight data is a placeholder (dims real, data not, per
    the frontend's tied/bf16 warning) must be listed in `skip_layers`
    and are recorded as off-fabric. `progress`, when given, is called
    as progress("masks", done, total, layer_name) per completed layer.
    Layers fan out across a process pool (`jobs` workers, default all
    cores; 1 = serial); the manifest stays in model order either way."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    layers = []
    totals = {"macros": 0, "weights": 0, "padded": 0, "wmat_bytes": 0}
    skipped = [{"layer": L.name,
                "reason": "off-fabric (non-ternary checkpoint data)"}
               for L in model.layers if L.name in skip_layers]
    todo = [L for L in model.layers if L.name not in skip_layers]
    calls = [(L.name, emit_layer_grid,
              (L, out, macro_rows, macro_cols, write_wmat), {})
             for L in todo]
    for man in run_ordered(calls, jobs=jobs, progress=progress,
                           stage="masks"):
        layers.append(asdict(man))
        totals["macros"] += man.n_macros
        totals["weights"] += man.weights
        totals["padded"] += man.padded_positions
        totals["wmat_bytes"] += man.wmat_bytes
    model_man = {
        "model": model.name,
        "macro_rows": macro_rows,
        "macro_cols": macro_cols,
        "totals": totals,
        "off_fabric": skipped,
        "layers": layers,
    }
    (out / "model_manifest.json").write_text(json.dumps(model_man, indent=1))
    return model_man


if __name__ == "__main__":
    import argparse
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-id", default="microsoft/bitnet-b1.58-2B-4T")
    ap.add_argument("--out", default="build/bitnet_emission")
    ap.add_argument("--macro-rows", type=int, default=64)
    ap.add_argument("--macro-cols", type=int, default=256)
    ap.add_argument("--no-wmat", action="store_true",
                    help="manifests and digests only (no mask-program files)")
    args = ap.parse_args()
    from ankhdjet.frontend.hf import load_weights
    model, _arch, _scales = load_weights(args.repo_id, progress=False)
    man = emit_model(model, args.out, args.macro_rows, args.macro_cols,
                     write_wmat=not args.no_wmat, skip_layers=("lm_head",))
    t = man["totals"]
    print(f"{man['model']}: {t['macros']:,} macros "
          f"({args.macro_rows}x{args.macro_cols}), "
          f"{t['weights']:,} weights, {t['padded']:,} padded, "
          f"{t['wmat_bytes']/1e9:.2f} GB mask programs -> {args.out}")
