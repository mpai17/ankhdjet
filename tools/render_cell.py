#!/usr/bin/env -S uv run python
"""Render a Magic .mag cell to a colored PNG using KLayout + the SKY130 .lyp.

Workflow:
  1. magic -dnull -noconsole writes the cell to GDS
  2. KLayout (-b -r) reads the GDS, applies the SKY130 layer-property file,
     and rasterizes the top cell's bbox (or a user-specified crop) to PNG.

Usage:
  uv run tools/render_cell.py <cell_dir> <cell_name> [--out PATH] [--width PX]
                       [--crop X1,Y1,X2,Y2]

Example:
  uv run tools/render_cell.py cell/sky130/strongarm/build strongarm
  uv run tools/render_cell.py cell/sky130/strongarm/build strongarm \
      --crop -8,0,3,6.5 --out strongarm_bottom.png

Requires klayout (apt install klayout) and magic in $PATH, plus a volare-installed
sky130A PDK at $HOME/.volare or $PDK_ROOT.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_PDK_GLOB = [
    "{home}/.volare/volare/sky130/versions/*/sky130A/libs.tech/klayout/tech/sky130A.lyp",
    "{pdk_root}/sky130A/libs.tech/klayout/tech/sky130A.lyp",
]


def find_lyp() -> Path:
    home = os.environ.get("HOME", "")
    pdk_root = os.environ.get("PDK_ROOT", "")
    import glob

    for pattern in DEFAULT_PDK_GLOB:
        for hit in glob.glob(pattern.format(home=home, pdk_root=pdk_root)):
            return Path(hit)
    raise FileNotFoundError(
        "sky130A.lyp not found. Set $PDK_ROOT or install via volare."
    )


def write_gds(cell_dir: Path, cell_name: str) -> Path:
    """Run magic to write <cell_name>.gds in cell_dir."""
    if shutil.which("magic") is None:
        raise FileNotFoundError("magic not in PATH")
    gds_path = cell_dir / f"{cell_name}.gds"
    tcl = (
        f"load {cell_name}\n"
        f"gds write {cell_name}.gds\n"
        "quit -noprompt\n"
    )
    subprocess.run(
        ["magic", "-dnull", "-noconsole"],
        cwd=cell_dir,
        input=tcl,
        text=True,
        check=True,
        capture_output=True,
    )
    if not gds_path.exists():
        raise RuntimeError(f"magic did not produce {gds_path}")
    return gds_path


def render_png(
    gds_path: Path,
    lyp_path: Path,
    out_path: Path,
    width: int,
    crop: tuple[float, float, float, float] | None,
    scalebar: float = 0.0,
) -> None:
    """Run klayout -b to rasterize gds_path to out_path."""
    if shutil.which("klayout") is None:
        raise FileNotFoundError("klayout not in PATH")
    crop_arg = (
        f"pya.DBox({crop[0]},{crop[1]},{crop[2]},{crop[3]})"
        if crop is not None
        else "lv.cellview(0).layout().top_cell().dbbox()"
    )
    script = f"""\
import pya
lv = pya.LayoutView()
lv.load_layout("{gds_path}", 0)
lv.load_layer_props("{lyp_path}")
lv.max_hier()
bbox = {crop_arg}
height = int({width} * bbox.height() / bbox.width())
if {scalebar}:
    ant = pya.Annotation()
    sx = bbox.left + bbox.width() * 0.05
    sy = bbox.bottom + bbox.height() * 0.03
    ant.p1 = pya.DPoint(sx, sy)
    ant.p2 = pya.DPoint(sx + {scalebar}, sy)
    ant.fmt = "$D"
    ant.style = pya.Annotation.StyleRuler
    lv.insert_annotation(ant)
lv.save_image_with_options("{out_path}", {width}, height, 0, 0, 0, bbox, False)
print(f"Saved {{height}}x{width} -> {out_path}")
"""
    script_path = Path("/tmp/render_cell_klayout.py")
    script_path.write_text(script)
    subprocess.run(["klayout", "-b", "-r", str(script_path)], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cell_dir", type=Path)
    ap.add_argument("cell_name")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--width", type=int, default=1600, help="image width in px")
    ap.add_argument(
        "--crop",
        type=str,
        default=None,
        help="bbox to render as 'x1,y1,x2,y2' (um); default = top cell bbox",
    )
    ap.add_argument(
        "--scalebar",
        type=float,
        default=0.0,
        help="draw a ruler of this length in um at the bottom-left (0 = none)",
    )
    ap.add_argument(
        "--lyp",
        type=Path,
        default=None,
        help="path to sky130A.lyp (auto-discovered from $PDK_ROOT or volare otherwise)",
    )
    args = ap.parse_args()

    cell_dir = args.cell_dir.resolve()
    if not (cell_dir / f"{args.cell_name}.mag").exists():
        print(f"error: {cell_dir}/{args.cell_name}.mag not found", file=sys.stderr)
        return 1

    lyp_path = (args.lyp or find_lyp()).resolve()
    out_path = (args.out or cell_dir / f"{args.cell_name}.png").resolve()
    crop = None
    if args.crop is not None:
        parts = args.crop.split(",")
        if len(parts) != 4:
            print("error: --crop must be 'x1,y1,x2,y2'", file=sys.stderr)
            return 1
        crop = tuple(float(p) for p in parts)  # type: ignore[assignment]

    gds_path = write_gds(cell_dir, args.cell_name)
    render_png(gds_path, lyp_path, out_path, args.width, crop, args.scalebar)
    print(f"PNG: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
