"""Independent content audit of an emitted mask set.

For every layer in the model manifest: reassemble the layer's weight
matrix from its emitted .wmat chunk files on disk (parse, un-pad,
stitch) and compare bit-for-bit against the reference weights. This
checks the artifact, not the emitter's return values: what is in the
files is what would be manufactured. The audit log is written beside
the audited output.

Optionally renders one layer's mask program as a PNG (one pixel per
weight: +1 white, -1 black, 0 gray) and writes a self-contained HTML
report of the audit; both need pillow, which is not a core dependency
and is reported as absent rather than failing.

    ankhdjet verify [--dir out] [--repo-id ...] [--render b0_q] [--report]
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ankhdjet.backend.wmat import load_wmat


def reassemble(layer_dir: Path):
    man = json.loads((layer_dir / "manifest.json").read_text())
    gr, gc = man["grid_r"], man["grid_c"]
    mr, mc = man["macro_rows"], man["macro_cols"]
    full = np.zeros((gr * mr, gc * mc), dtype=np.int8)
    for i in range(gr):
        for j in range(gc):
            full[i * mr:(i + 1) * mr, j * mc:(j + 1) * mc] = \
                load_wmat(layer_dir / f"r{i}_c{j}.wmat")
    return full[: man["rows"], : man["cols"]], full, man


def verify_layer(layer_dir: Path, W_ref: np.ndarray) -> tuple[str, bool, str]:
    name = layer_dir.name
    try:
        W, full, man = reassemble(layer_dir)
        if not np.array_equal(W, W_ref):
            return name, False, "content mismatch vs checkpoint"
        # padding must be all-zero (floating drains)
        pad_sum = int(np.abs(full).sum()) - int(np.abs(W_ref).sum())
        if pad_sum != 0:
            return name, False, f"nonzero padding ({pad_sum})"
        return name, True, f"{man['n_macros']} macros"
    except Exception as e:  # noqa: BLE001
        return name, False, f"error: {e}"


def verify_model(model, root: Path, jobs: int = 8,
                 progress=None) -> dict:
    """Audit every manifest layer of the emission at `root` against the
    layers of `model` (any ModelIR whose weight data is real). Returns
    {"ok", "n_ok", "n_layers", "total_macros", "failures"}."""
    root = Path(root)
    model_man = json.loads((root / "model_manifest.json").read_text())
    refs = {l.name: l.weights["weight"].data for l in model.layers}
    layer_names = [lm["layer"] for lm in model_man["layers"]]

    n_ok = 0
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = {pool.submit(verify_layer, root / n, refs[n]): n
                for n in layer_names}
        for k, fut in enumerate(as_completed(futs), 1):
            name, ok, detail = fut.result()
            if ok:
                n_ok += 1
            else:
                failures.append((name, detail))
            if progress is not None:
                progress(k, len(layer_names), name, ok, detail)
    return {"ok": not failures, "n_ok": n_ok,
            "n_layers": len(layer_names),
            "total_macros": model_man["totals"]["macros"],
            "failures": failures, "model_manifest": model_man}


def _write_report(root: Path, model_man: dict, layer: str,
                  W: np.ndarray, img: np.ndarray,
                  n_ok: int, n_layers: int, failures: list,
                  stamp: str) -> Path:
    """Self-contained HTML: audit verdict, totals, the rendered layer
    (full view + pixel-scale crop), and a raw chunk sample."""
    import base64
    import io

    from PIL import Image

    def b64(im: "Image.Image") -> str:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    full = Image.fromarray(img)
    web = full.copy()
    web.thumbnail((1280, 1280), Image.NEAREST)
    ch, cw = img.shape[0] // 2, img.shape[1] // 2
    crop = full.crop((cw, ch, cw + 128, ch + 128)).resize((512, 512),
                                                          Image.NEAREST)
    t = model_man["totals"]
    counts = {"+1": int((W == 1).sum()), "-1": int((W == -1).sum()),
              "0": int((W == 0).sum())}
    lm = json.loads((root / layer / "manifest.json").read_text())
    sample_rows = (root / layer / "r0_c0.wmat").read_text().splitlines()[:6]
    sample = "\n".join(r[:72] for r in sample_rows)
    verdict_ok = not failures
    verdict = (f"AUDIT PASS — {n_ok}/{n_layers} layers bit-exact from disk"
               if verdict_ok else
               f"AUDIT FAIL — {len(failures)} of {n_layers} layers mismatch")
    vcol = "var(--good)" if verdict_ok else "#b3402a"
    html = f"""<title>{model_man['model']} as a Mask Set</title>
<style>
:root {{ --bg:#faf9f6; --ink:#1c1a16; --muted:#6d675c; --line:#e2ded4;
  --accent:#9a6b1f; --panel:#f1efe8; --good:#2e6b3f; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#14130f; --ink:#ece8de; --muted:#98917f; --line:#2c2a23;
    --accent:#d9a441; --panel:#1c1a15; --good:#7dc491; }} }}
:root[data-theme="dark"] {{ --bg:#14130f; --ink:#ece8de; --muted:#98917f;
  --line:#2c2a23; --accent:#d9a441; --panel:#1c1a15; --good:#7dc491; }}
:root[data-theme="light"] {{ --bg:#faf9f6; --ink:#1c1a16; --muted:#6d675c;
  --line:#e2ded4; --accent:#9a6b1f; --panel:#f1efe8; --good:#2e6b3f; }}
body {{ background:var(--bg); color:var(--ink); margin:0;
  font:16px/1.6 Seravek,"Gill Sans Nova",Ubuntu,Calibri,"DejaVu Sans",sans-serif; }}
main {{ max-width:880px; margin:0 auto; padding:48px 24px 80px; }}
.eyebrow {{ font-size:12px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--accent); font-weight:600; }}
h1 {{ font-size:clamp(28px,5vw,40px); line-height:1.15; margin:8px 0 4px;
  text-wrap:balance; font-weight:650; }}
.sub {{ color:var(--muted); max-width:62ch; margin:0 0 28px; }}
.verdict {{ display:inline-block; border:1px solid {vcol}; color:{vcol};
  border-radius:3px; padding:2px 10px; font-weight:600; font-size:14px; }}
.statrow {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:1px; background:var(--line); border:1px solid var(--line); margin:28px 0; }}
.stat {{ background:var(--panel); padding:14px 16px; }}
.stat b {{ display:block; font-size:22px; font-variant-numeric:tabular-nums;
  font-weight:650; }}
.stat span {{ font-size:12.5px; color:var(--muted); }}
figure {{ margin:32px 0; }}
.maskwrap {{ display:grid; grid-template-columns:1fr; gap:12px; }}
@media (min-width:700px) {{ .maskwrap {{ grid-template-columns:2fr 1fr; }} }}
.maskwrap img {{ width:100%; height:auto; display:block;
  border:1px solid var(--line); }}
.maskwrap .zoom img {{ image-rendering:pixelated; }}
figcaption {{ font-size:13px; color:var(--muted); margin-top:10px; max-width:72ch; }}
h2 {{ font-size:20px; margin:40px 0 10px; font-weight:650; }}
pre {{ background:var(--panel); border:1px solid var(--line); padding:14px 16px;
  overflow-x:auto; margin:12px 0;
  font:13px/1.5 ui-monospace,"Cascadia Code",Menlo,Consolas,monospace; }}
p {{ max-width:68ch; }}
.legend {{ display:flex; gap:18px; font-size:13px; color:var(--muted);
  flex-wrap:wrap; margin-top:8px; }}
.chip {{ display:inline-block; width:11px; height:11px;
  border:1px solid var(--line); vertical-align:-1px; margin-right:6px; }}
code {{ font:.92em ui-monospace,Menlo,Consolas,monospace; color:var(--accent); }}
</style>
<main>
<div class="eyebrow">Ankhdjet · full-model emission audit · {stamp}</div>
<h1>{model_man['model']}, compiled to its mask set</h1>
<p class="sub">Every ternary layer of the checkpoint, tiled into mask-programmed
array macros and written to disk as via-programming source; then read back,
reassembled, and compared bit-for-bit against the checkpoint.</p>
<span class="verdict">{verdict}</span>
<div class="statrow">
 <div class="stat"><b>{t['macros']:,}</b><span>macros, {model_man['macro_rows']} rows × {model_man['macro_cols']} cols</span></div>
 <div class="stat"><b>{t['weights']:,}</b><span>ternary weights emitted</span></div>
 <div class="stat"><b>{100*t['padded']/(t['weights']+t['padded']):.2f}%</b><span>edge padding (floating drains)</span></div>
 <div class="stat"><b>{t['wmat_bytes']/1e9:.2f}&nbsp;GB</b><span>mask-program source (.wmat)</span></div>
</div>
<h2>One layer, seen as its mask</h2>
<figure>
<div class="maskwrap">
 <div><img alt="{layer} mask program, one pixel per weight" src="data:image/png;base64,{b64(web)}"></div>
 <div class="zoom"><img alt="128x128 crop at pixel scale" src="data:image/png;base64,{b64(crop)}"></div>
</div>
<div class="legend">
 <span><span class="chip" style="background:#fff"></span>+1 · via to BL+ ({counts['+1']:,})</span>
 <span><span class="chip" style="background:#000"></span>−1 · via to BL− ({counts['-1']:,})</span>
 <span><span class="chip" style="background:#808080"></span>0 · floating drain ({counts['0']:,})</span>
</div>
<figcaption>Left: layer <code>{layer}</code>, all {lm['weights']:,} weights of a
{lm['rows']}×{lm['cols']} projection, one pixel per weight, reassembled from its
{lm['n_macros']} emitted macro chunks. Right: a 128×128 crop at pixel scale;
each square is one transistor's drain-via choice.</figcaption>
</figure>
<h2>What a macro chunk looks like on disk</h2>
<p>The unit of manufacture: row <i>r</i> is wordline <i>r</i>, column <i>c</i> is
bitline pair <i>c</i>.</p>
<pre>{layer}/r0_c0.wmat  (rows 0–5, first 72 of {model_man['macro_cols']} columns)

{sample}</pre>
<h2>Provenance</h2>
<p>Each layer directory carries a manifest with grid geometry and a SHA-256
digest per chunk; off-fabric layers: {", ".join(x['layer'] for x in model_man['off_fabric']) or "none"}.
This page regenerates from the audit itself:</p>
<pre>ankhdjet compile &lt;model&gt; -o &lt;dir&gt;   # emit the design bundle
ankhdjet verify --dir &lt;dir&gt; --report  # audit + this report</pre>
</main>
"""
    out = root / "emission_report.html"
    out.write_text(html)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ankhdjet verify", description=__doc__)
    ap.add_argument("--dir", default="build/bitnet_emission",
                    help="emission/bundle directory to audit")
    ap.add_argument("--repo-id", default="microsoft/bitnet-b1.58-2B-4T")
    ap.add_argument("--render", default=None,
                    help="layer name to render as PNG (1 px/weight)")
    ap.add_argument("--report", action="store_true",
                    help="write a self-contained emission_report.html "
                         "beside the audited output (implies rendering "
                         "--render or b0_q)")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args(argv)

    root = Path(args.dir)
    from ankhdjet.frontend.hf import load_weights
    print("loading checkpoint for reference...", flush=True)
    model, _arch, _scales = load_weights(args.repo_id, progress=False)

    t0 = time.time()

    def on_progress(k, total, name, ok, detail):
        if not ok:
            print(f"  FAIL {name}: {detail}", flush=True)
        if k % 30 == 0:
            print(f"  {k}/{total} layers checked ({time.time()-t0:.0f}s)",
                  flush=True)

    res = verify_model(model, root, jobs=args.jobs, progress=on_progress)
    verdict = ("PASS" if res["ok"]
               else f"FAIL ({len(res['failures'])} layers)")
    line = (f"emission audit: {res['n_ok']}/{res['n_layers']} layers "
            f"bit-exact ({res['total_macros']:,} macros reassembled from "
            f"disk) -> {verdict}")
    print(line)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (root / f"emission_audit_{stamp}.log").write_text(
        line + "\n" +
        "\n".join(f"FAIL {n}: {d}" for n, d in res["failures"]) + "\n")

    render_layer = args.render or ("b0_q" if args.report else None)
    if render_layer:
        try:
            from PIL import Image
        except ImportError:
            print("render/report skipped: pillow not installed "
                  "(pip install ankhdjet[flow])")
            return 0 if res["ok"] else 1
        W, _, _ = reassemble(root / render_layer)
        img = np.full(W.shape, 128, dtype=np.uint8)
        img[W == 1] = 255
        img[W == -1] = 0
        out = root / f"mask_{render_layer}.png"
        Image.fromarray(img).save(out)
        print(f"rendered {render_layer} ({W.shape[0]}x{W.shape[1]} weights) "
              f"-> {out}")
        if args.report:
            rpt = _write_report(root, res["model_manifest"], render_layer,
                                W, img, res["n_ok"], res["n_layers"],
                                res["failures"], stamp)
            print(f"report -> {rpt}")

    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
