#!/usr/bin/env python3
"""Assemble a self-contained GDS web viewer from rendered layer masks.

Reads the masks + manifest.json produced by render_layers.py, tints each
mask its SKY130 layer color (ImageMagick), quantizes, picks the smaller
encoding per layer, and embeds everything into viewer_template.html as
data URIs. The result is one HTML file with no external references.
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

# id -> (hex color, default opacity, on by default)
STYLE = {
    "nwell": ("8B7BD8", 0.38, False),
    "psdm":  ("6E5AA8", 0.30, False),
    "nsdm":  ("907030", 0.30, False),
    "tap":   ("2E8B57", 0.80, True),
    "diff":  ("4CAF6E", 0.80, True),
    "poly":  ("E4573D", 0.85, True),
    "licon": ("D9D9D9", 0.60, True),
    "li1":   ("7FD4DC", 0.80, True),
    "mcon":  ("F5F5F5", 0.70, True),
    "met1":  ("5B8DEF", 0.80, True),
    "via":   ("EDEDED", 0.95, True),
    "met2":  ("D964BE", 0.80, True),
    "via2":  ("FFCE54", 0.95, True),
    "met3":  ("4FC3E8", 0.80, True),
    "via3":  ("FFA94D", 0.95, True),
    "met4":  ("E5C453", 0.85, True),
}
GDS_LD = {
    "nwell": (64, 20), "psdm": (94, 20), "nsdm": (93, 44),
    "tap": (65, 44), "diff": (65, 20), "poly": (66, 20), "licon": (66, 44),
    "li1": (67, 20), "mcon": (67, 44),
    "met1": (68, 20), "via": (68, 44), "met2": (69, 20), "via2": (69, 44),
    "met3": (70, 20), "via3": (70, 44), "met4": (71, 20),
}


def tint(mask: Path, color: str, w: int, h: int) -> bytes:
    """Colorize a white-on-black mask; return the smaller of RGBA/quantized."""
    full = mask.with_name(mask.stem.replace("mask_", "layer_") + ".png")
    quant = full.with_name(full.stem + "_q.png")
    subprocess.run(
        ["magick", "-size", f"{w}x{h}", f"xc:#{color}",
         "(", str(mask), "-resize", f"{w}x{h}!", ")",
         "-compose", "CopyOpacity", "-composite", f"PNG32:{full}"],
        check=True)
    subprocess.run(
        ["magick", str(full), "-channel", "A", "-posterize", "6", "+channel",
         "-colors", "48", f"PNG8:{quant}"],
        check=True)
    # quantization can collapse sparse dot layers to fully transparent;
    # only accept the smaller quantized file if it kept opaque pixels
    mean_a = float(subprocess.run(
        ["magick", str(quant), "-format", "%[fx:mean.a]", "info:"],
        capture_output=True, text=True, check=True).stdout or 0)
    best = min([full, quant], key=lambda p: p.stat().st_size) \
        if mean_a > 0 else full
    return best.read_bytes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("masks", help="directory with mask_*.png + manifest.json")
    ap.add_argument("out", help="output HTML path")
    ap.add_argument("--title", default=None, help="header title")
    ap.add_argument("--subtitle", default=None, help="header subtitle")
    ap.add_argument("--about", default="", help="sidebar note (HTML allowed)")
    args = ap.parse_args()

    masks = Path(args.masks)
    mf = json.loads((masks / "manifest.json").read_text())
    w, h = mf["px_w"], mf["px_h"]

    layers = []
    for lid, (color, alpha, on) in STYLE.items():
        mask = masks / f"mask_{lid}.png"
        if not mask.exists() or not mf["counts"].get(lid):
            continue
        data = base64.b64encode(tint(mask, color, w, h)).decode()
        l, d = GDS_LD[lid]
        layers.append({"id": lid, "color": f"#{color}", "l": l, "d": d,
                       "count": mf["counts"][lid], "alpha": alpha, "on": on,
                       "src": f"data:image/png;base64,{data}"})

    page = (HERE / "viewer_template.html").read_text()
    page = (page
            .replace("__LAYERS__", json.dumps(layers))
            .replace("__DIEW__", str(mf["die_w_um"]))
            .replace("__DIEH__", str(mf["die_h_um"]))
            .replace("__IMGW__", str(w))
            .replace("__IMGH__", str(h))
            .replace("__TITLE__", args.title or mf["top"])
            .replace("__SUB__", args.subtitle or f"GDS viewer — {mf['gds']}")
            .replace("__ABOUT__", args.about))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"{out}  {out.stat().st_size / 1e6:.2f} MB  "
          f"({len(layers)} layers, {mf['die_w_um']}x{mf['die_h_um']} um)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
