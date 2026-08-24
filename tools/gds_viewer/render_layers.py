# KLayout batch script: render one white-on-black mask PNG per SKY130 layer
# of a GDS, plus a manifest.json with the die bbox, pixel dims, and per-layer
# shape counts. Layers with no shapes are skipped.
#
# Invoke via klayout -b:
#   klayout -b -rd gds=<in.gds> -rd out=<dir> [-rd height=2822] \
#           -r tools/gds_viewer/render_layers.py
import json
import os

import pya

LAYERS = [  # bottom -> top z-order; (layer, datatype, id)
    (64, 20, "nwell"), (94, 20, "psdm"), (93, 44, "nsdm"),
    (65, 44, "tap"), (65, 20, "diff"), (66, 20, "poly"), (66, 44, "licon"),
    (67, 20, "li1"), (67, 44, "mcon"),
    (68, 20, "met1"), (68, 44, "via"), (69, 20, "met2"), (69, 44, "via2"),
    (70, 20, "met3"), (70, 44, "via3"), (71, 20, "met4"),
]

out = out  # noqa: F821  (injected by -rd)
gds = gds  # noqa: F821
px_h = int(globals().get("height", "2822"))
os.makedirs(out, exist_ok=True)

SS = 2  # supersample: render at 2x, the tint step downscales -- antialiased
        # alpha survives palette quantization (at 1x the dot layers collapse)

layout = pya.Layout()
layout.read(gds)
top = layout.top_cell()
die = top.dbbox()
px_w = int(round(px_h * die.width() / die.height()))

counts = {}
for l, d, name in LAYERS:
    li = layout.find_layer(l, d)
    counts[name] = sum(1 for _ in top.begin_shapes_rec(li)) if li is not None else 0

view = pya.LayoutView()
view.load_layout(gds)
view.max_hier()
view.set_config("background-color", "#000000")
view.set_config("grid-visible", "false")
view.set_config("text-visible", "false")

for l, d, name in LAYERS:
    if not counts[name]:
        continue
    for lp in view.each_layer():
        match = lp.source_layer == l and lp.source_datatype == d
        lp.visible = match
        if match:
            lp.fill_color = 0xFFFFFF
            lp.frame_color = 0xFFFFFF
            lp.dither_pattern = 0
            lp.transparent = False
            lp.width = 1
    view.zoom_box(die)
    view.save_image(f"{out}/mask_{name}.png", px_w * SS, px_h * SS)

manifest = {
    "gds": os.path.basename(gds),
    "top": top.name,
    "die_w_um": round(die.width(), 4),
    "die_h_um": round(die.height(), 4),
    "px_w": px_w,
    "px_h": px_h,
    "counts": counts,
}
with open(f"{out}/manifest.json", "w") as f:
    json.dump(manifest, f, indent=1)
print(f"rendered {sum(1 for c in counts.values() if c)} layers at "
      f"{px_w}x{px_h} ({die.width() / px_w * 1000:.0f} nm/px) -> {out}")
