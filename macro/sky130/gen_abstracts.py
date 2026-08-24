"""Generate LEF + Liberty + Verilog blackbox abstracts for the
macro_array_pc hard macro (bitcell array + precharge_row + VPWR rail).

LibreLane consumes these via the MACROS dict in config_bands.json:

    "MACROS": {
        "macro_array_pc_64x32_checker": {
            "gds": ["dir::macros/macro_array_pc_64x32_checker.gds"],
            "lef": ["dir::macros/macro_array_pc_64x32_checker.lef"],
            "lib": {"*": ["dir::macros/macro_array_pc_64x32_checker.lib"]},
            "nl":  ["dir::macros/macro_array_pc_64x32_checker.bb.v"],
            ...
        }
    }

This script:
  1. Reads the macro's GDS bbox via klayout
  2. Calls Magic with `lef write` to emit the .lef
  3. Emits a hand-templated Liberty (analog macro: area + power, no
     timing arcs -- BL+/BL- are sensed by chip-level SAs)
  4. Emits a Verilog blackbox matching the labeled pins

Usage:
    uv run macro/sky130/gen_abstracts.py 64 32 checker
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
MACRO_BUILD = REPO / "cell" / "sky130" / "macro" / "build"
OUT_DIR = REPO / "macro" / "sky130" / "abstracts"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def relabel_pins_to_pin_datatype(gds: Path, top: str) -> None:
    """Move the macro's top-cell pin labels from the text datatype (X/5,
    Magic's gds-write default) to the metal PIN datatype (X/16): the chip
    flow's Magic extraction reads labels as net names/ports only from the
    PIN datatype. Idempotent. Top-cell only -- subcell-internal labels
    must not become ports."""
    import tempfile
    script = f"""
import pya
ly = pya.Layout()
ly.read("{gds}")
tc = ly.cell("{top}")
n = 0
for li in list(ly.layer_indexes()):
    info = ly.get_info(li)
    if info.datatype != 5:
        continue
    dst = ly.layer(info.layer, 16)
    for s in [s for s in tc.shapes(li).each() if s.is_text()]:
        tc.shapes(dst).insert(s.text)
        tc.shapes(li).erase(s)
        n += 1
if n:
    ly.write("{gds}")
print(f"RELABELED {{n}}")
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(script)
        path = f.name
    try:
        r = subprocess.run(["klayout", "-b", "-r", path],
                           capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(path)
    for ln in r.stdout.splitlines():
        if ln.startswith("RELABELED"):
            print(f"pin labels moved to the PIN datatype: {ln.split()[1]}")
            return
    raise RuntimeError(f"relabel failed:\n{r.stdout}\n{r.stderr}")


def read_bbox_um(gds: Path, top: str) -> tuple[float, float, float, float]:
    """Return (x_min, y_min, x_max, y_max) in microns via klayout."""
    import tempfile
    script = f"""
import pya
ly = pya.Layout()
ly.read("{gds}")
top = ly.cell("{top}")
bb = top.bbox()
print(f"BBOX_NM {{bb.left}} {{bb.bottom}} {{bb.right}} {{bb.top}}")
"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(script)
        script_path = f.name
    try:
        r = subprocess.run(
            ["klayout", "-b", "-r", script_path],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        os.unlink(script_path)
    for ln in r.stdout.splitlines():
        if ln.startswith("BBOX_NM"):
            _, l, b, t_r, t_t = ln.split()
            return (int(l) / 1000, int(b) / 1000,
                    int(t_r) / 1000, int(t_t) / 1000)
    raise RuntimeError(f"klayout bbox failed:\n{r.stdout}\n{r.stderr}")


def emit_lef_via_magic(mag_dir: Path, top: str, out_lef: Path) -> None:
    """Run Magic to emit a LEF abstract from the macro's .mag.
    Loads sky130A.tech explicitly via PDK_ROOT to avoid .magicrc
    discovery issues across cwd / PATH."""
    pdk_root = os.environ.get("PDK_ROOT", str(Path.home() / ".ciel"))
    tech = f"{pdk_root}/sky130A/libs.tech/magic/sky130A.tech"
    tcl = f"""
tech load {tech}
load {top} -quiet
select top cell
lef write {top} -hide
quit -noprompt
"""
    env = os.environ.copy()
    env["PDK_ROOT"] = pdk_root
    r = subprocess.run(
        ["magic", "-dnull", "-noconsole"],
        input=tcl, cwd=mag_dir, env=env,
        capture_output=True, text=True, timeout=120,
    )
    # Magic writes <top>.lef in cwd; move to out_lef.
    written = mag_dir / f"{top}.lef"
    if not written.exists():
        raise RuntimeError(
            f"magic lef write failed (no {written}):\n{r.stdout[-1500:]}\n{r.stderr[-500:]}"
        )
    out_lef.write_bytes(written.read_bytes())


SKY130_GDS_LAYERS = {
    "li1":  (67, 20),
    "met1": (68, 20),
    "met2": (69, 20),
    "met3": (70, 20),
    "met4": (71, 20),
    # met5 deliberately absent: the macro's only met5 is the VPWR via4
    # pads, which merge with the chip met5 PDN stripe -- declaring them
    # OBS would make pdngen cut its stripe over the macro.
}


def parse_lef_pins_per_layer(lef_text: str) -> dict[str, list[tuple[float, float, float, float]]]:
    """Return {layer: [(x1,y1,x2,y2), ...]} for all PORT RECTs in the LEF."""
    import re
    pins: dict[str, list[tuple[float, float, float, float]]] = {}
    in_pin = False
    layer = None
    for line in lef_text.splitlines():
        s = line.strip()
        if s.startswith("PIN "):
            in_pin = True
            continue
        if s == "END" and in_pin:
            # bare END terminates a PORT (a pin may have several PORTs on
            # different layers, e.g. VPWR met1+nwell+met4); reset the layer but
            # stay in the pin so every PORT's RECTs are captured.
            layer = None
            continue
        m = re.match(r"END\s+\S+", s)
        if m and in_pin:
            in_pin = False
            layer = None
            continue
        if not in_pin:
            continue
        m = re.match(r"LAYER\s+(\S+)\s*;", s)
        if m:
            layer = m.group(1)
            continue
        m = re.match(r"RECT\s+([\-\d.]+)\s+([\-\d.]+)\s+([\-\d.]+)\s+([\-\d.]+)\s*;", s)
        if m and layer:
            pins.setdefault(layer, []).append(tuple(float(x) for x in m.groups()))
    return pins


def emit_obs_from_gds(top: str, gds_path: Path, lef_path: Path) -> None:
    """Post-process the LEF: replace its OBS block with a full-coverage
    OBS computed from the GDS (per-layer geometry minus PIN rectangles).
    Magic's `lef write -hide` omits OBS for any layer that has a labeled
    PIN, which leaves internal met2/met3/met4 patches uncovered and
    causes chip-router placed metal to violate spacing against them.

    Uses klayout via subprocess (parent process is the uv project env;
    klayout has its own embedded Python so we don't import pya here)."""
    import tempfile
    lef_text = lef_path.read_text()
    pins = parse_lef_pins_per_layer(lef_text)
    # Klayout script: read GDS, subtract per-layer pin rects, emit boxes.
    layer_specs = ";".join(f"{name}:{n}/{d}" for name, (n, d) in SKY130_GDS_LAYERS.items())
    pin_lines = []
    for layer, rects in pins.items():
        for x1, y1, x2, y2 in rects:
            pin_lines.append(f"{layer} {x1} {y1} {x2} {y2}")
    pins_blob = "\n".join(pin_lines)
    script = f'''
import pya
ly = pya.Layout()
ly.read("{gds_path}")
top = ly.cell("{top}")
dbu = ly.dbu
layers = {{}}
for name, spec in {SKY130_GDS_LAYERS!r}.items():
    lidx = ly.layer(spec[0], spec[1])
    layers[name] = lidx

pin_rects_um = """{pins_blob}"""
pin_by_layer = {{}}
for line in pin_rects_um.strip().split("\\n"):
    if not line.strip():
        continue
    parts = line.split()
    layer = parts[0]
    x1, y1, x2, y2 = (float(p) for p in parts[1:5])
    pin_by_layer.setdefault(layer, []).append((x1, y1, x2, y2))

for name in ["met2", "met3", "met4"]:
    lidx = layers[name]
    region = pya.Region(top.begin_shapes_rec(lidx))
    # Subtract pin rects on this layer
    pin_region = pya.Region()
    for (x1, y1, x2, y2) in pin_by_layer.get(name, []):
        b = pya.Box(int(round(x1/dbu)), int(round(y1/dbu)),
                    int(round(x2/dbu)), int(round(y2/dbu)))
        # met3 pins in the rails region (only PRE_N lives there) get a
        # 0.30 moat: OBS abutting a short interior pin leaves the router
        # no legal access (the band macro lesson). The full-height array
        # bitline pins stay exactly-subtracted.
        if name == "met3" and y1 > 93.0:
            b = b.enlarged(int(round(0.30/dbu)), int(round(0.30/dbu)))
        pin_region.insert(b)
    obs = region - pin_region
    obs.merge()
    print(f"OBS_LAYER {{name}}")
    for poly in obs.each():
        bb = poly.bbox()
        print(f"OBS_RECT {{name}} {{bb.left*dbu:.3f}} {{bb.bottom*dbu:.3f}} {{bb.right*dbu:.3f}} {{bb.top*dbu:.3f}}")
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(script)
        script_path = f.name
    try:
        r = subprocess.run(
            ["klayout", "-b", "-r", script_path],
            capture_output=True, text=True, timeout=300,
        )
    finally:
        os.unlink(script_path)
    if r.returncode != 0:
        raise RuntimeError(f"klayout obs extract failed:\n{r.stdout}\n{r.stderr}")
    # Group by layer
    obs_rects: dict[str, list[tuple[float, float, float, float]]] = {}
    for ln in r.stdout.splitlines():
        if ln.startswith("OBS_RECT"):
            _, layer, x1, y1, x2, y2 = ln.split()
            obs_rects.setdefault(layer, []).append((float(x1), float(y1), float(x2), float(y2)))

    # Splice OBS block: keep existing OBS contents (li1 + met1), append met2/3/4
    lines = lef_text.splitlines()
    obs_start = None
    end_macro = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == "OBS" and obs_start is None:
            obs_start = i
        if s.startswith("END macro_array_pc_") or s.startswith(f"END {top}"):
            end_macro = i
            break
    if obs_start is None or end_macro is None:
        raise RuntimeError("could not locate OBS / END MACRO in LEF")
    # Find the END of OBS block (the line "    END" just before END MACRO)
    obs_end = None
    for j in range(end_macro - 1, obs_start, -1):
        if lines[j].strip() == "END":
            obs_end = j
            break
    if obs_end is None:
        raise RuntimeError("could not locate end of OBS block")
    new_obs = []
    for layer in ("met2", "met3", "met4"):
        if layer not in obs_rects:
            continue
        new_obs.append(f"      LAYER {layer} ;")
        for x1, y1, x2, y2 in obs_rects[layer]:
            new_obs.append(f"        RECT {x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f} ;")
    # From Magic's kept OBS contents keep only li1/met1: met2/3/4 are
    # recomputed below (Magic's versions reflect its fragmented pins,
    # e.g. the VPWR strip remainder), and met5 must not appear at all
    # (the VPWR via4 pads would obstruct the chip met5 stripe).
    kept = list(lines[:obs_start + 1])
    skip = False
    for ln in lines[obs_start + 1:obs_end]:
        s = ln.strip()
        if s.startswith("LAYER "):
            skip = s not in ("LAYER li1 ;", "LAYER met1 ;")
        if not skip:
            kept.append(ln)
    out_lines = kept + new_obs + lines[obs_end:]
    lef_path.write_text("\n".join(out_lines) + "\n")


def emit_liberty(top: str, n_rows: int, n_cols: int,
                  bbox: tuple[float, float, float, float],
                  out_lib: Path) -> None:
    """Hand-templated Liberty for the analog macro. Area + power only;
    BL+/BL- have no timing arcs because they're analog levels sensed
    by chip-level StrongARM SAs (LibreLane treats them as inout)."""
    x_lo, y_lo, x_hi, y_hi = bbox
    area_um2 = (x_hi - x_lo) * (y_hi - y_lo)
    lines = [
        f"/* {top} Liberty (auto-generated from gen_abstracts.py)",
        f" * Bitcell array {n_rows}x{n_cols} + precharge row + VPWR rail.",
        f" * Bbox: {x_hi - x_lo:.2f} x {y_hi - y_lo:.2f} um = {area_um2:.0f} um^2.",
        f" * Pins: WL_<r> (input WL drive), BLP_<c>/BLN_<c> (analog BL),",
        f" *       VPWR (precharge source), VGND (substrate).",
        " */",
        "",
        f"library ({top}) {{",
        "  technology (cmos);",
        "  delay_model : table_lookup;",
        '  time_unit                    : "1ns";',
        '  voltage_unit                 : "1V";',
        '  current_unit                 : "1mA";',
        '  pulling_resistance_unit      : "1kohm";',
        "  capacitive_load_unit (1, ff);",
        '  leakage_power_unit           : "1nW";',
        "  default_input_pin_cap        : 0.001;",
        "  default_inout_pin_cap        : 0.001;",
        "  default_output_pin_cap       : 0.000;",
        "  nom_voltage                  : 1.80;",
        "  nom_temperature              : 25.0;",
        "  nom_process                  : 1.0;",
        "  input_threshold_pct_rise     : 50;",
        "  input_threshold_pct_fall     : 50;",
        "  output_threshold_pct_rise    : 50;",
        "  output_threshold_pct_fall    : 50;",
        "  slew_lower_threshold_pct_rise: 20;",
        "  slew_upper_threshold_pct_rise: 80;",
        "  slew_lower_threshold_pct_fall: 20;",
        "  slew_upper_threshold_pct_fall: 80;",
        "  slew_derate_from_library     : 1.0;",
        "  voltage_map (VPWR, 1.80);",
        "  voltage_map (VGND, 0.0);",
        "",
        f"  cell ({top}) {{",
        "    is_macro_cell : true;",
        f"    area : {area_um2:.1f};",
        "    pg_pin (VPWR) {",
        "      pg_type : primary_power;",
        "      voltage_name : VPWR;",
        "    }",
        "    pg_pin (VGND) {",
        "      pg_type : primary_ground;",
        "      voltage_name : VGND;",
        "    }",
        "",
    ]
    for r in range(n_rows):
        lines += [
            f"    pin (WL_{r}) {{",
            "      direction : input;",
            "      capacitance : 30.0;",
            "      related_power_pin  : VPWR;",
            "      related_ground_pin : VGND;",
            "    }",
            "",
        ]
    lines += [
        "    pin (PRE_N) {",
        "      direction : input;",
        "      capacitance : 105.0;",
        "      related_power_pin  : VPWR;",
        "      related_ground_pin : VGND;",
        "    }",
        "",
    ]
    for c in range(n_cols):
        for sig in ("BLP", "BLN"):
            lines += [
                f"    pin ({sig}_{c}) {{",
                "      direction : inout;",
                "      capacitance : 60.0;",
                "      max_capacitance : 450.0;",
                "      related_power_pin  : VPWR;",
                "      related_ground_pin : VGND;",
                "    }",
                "",
            ]
    lines += ["  }", "}", ""]
    out_lib.write_text("\n".join(lines))


def emit_blackbox_verilog(top: str, n_rows: int, n_cols: int,
                           out_v: Path) -> None:
    """Verilog blackbox for synthesis. Pins as flat names matching the
    Magic port labels (LibreLane / Yosys can match these via the
    MACROS.<name>.nl entry)."""
    lines = [
        f"// {top} blackbox (auto-generated from gen_abstracts.py)",
        f"// {n_rows}x{n_cols} bitcell array + precharge_row.",
        "",
        "`celldefine",
        "(* blackbox *)",
        f"module {top} (",
    ]
    pin_lines = []
    for r in range(n_rows):
        pin_lines.append(f"    input  WL_{r}")
    for c in range(n_cols):
        pin_lines.append(f"    inout  BLP_{c}")
        pin_lines.append(f"    inout  BLN_{c}")
    pin_lines.append("    input  PRE_N")
    pin_lines.append("    inout  VPWR")
    pin_lines.append("    inout  VGND")
    lines.append(",\n".join(pin_lines))
    lines += [
        ");",
        "endmodule",
        "`endcelldefine",
        "",
    ]
    out_v.write_text("\n".join(lines))


def emit_lvs_schematic(top: str, n_rows: int, n_cols: int, pattern: str,
                       out_sp, wmat=None) -> None:
    """Transistor-level LVS reference for the macro, generated from the
    weight rule (independent of the layout). One nfet per bitcell with
    the drain on the weight-programmed bitline and source/bulk on VGND
    (the source/read-line ground network), plus the clocked
    precharge pair per column (pfet pull-ups on BL+ and BL-, gates on
    the PRE_N pin; see docs/precharge_design.md). Consumed
    by the chip flow via EXTRA_SPICE_MODELS so the flat-extracted array
    has a schematic to match."""
    def weight(r: int, c: int) -> int:
        if wmat is not None:
            return wmat[r][c]
        if pattern == "all_pos":
            return 1
        if pattern == "all_neg":
            return -1
        return 1 if (r + c) % 2 == 0 else -1

    ports = [f"WL_{r}" for r in range(n_rows)]
    for c in range(n_cols):
        ports += [f"BLP_{c}", f"BLN_{c}"]
    ports += ["PRE_N", "VPWR", "VGND"]
    lines = [
        f"* {top} LVS schematic (auto-generated from gen_abstracts.py)",
        f".subckt {top} {' '.join(ports)}",
    ]
    for r in range(n_rows):
        for c in range(n_cols):
            w = weight(r, c)
            # w=0: the drain stub is mask-left floating -- a dangling
            # unique net, matching the unprogrammed cell in layout.
            bl = f"BLP_{c}" if w == 1 else (f"BLN_{c}" if w == -1 else f"nc_{r}_{c}")
            lines.append(f"XB{r}_{c} VGND WL_{r} {bl} VGND"
                         f" sky130_fd_pr__nfet_01v8 w=0.42 l=0.17")
    for c in range(n_cols):
        lines.append(f"XPP{c} VPWR PRE_N BLP_{c} VPWR"
                     f" sky130_fd_pr__pfet_01v8 w=1.0 l=0.15")
        lines.append(f"XPN{c} VPWR PRE_N BLN_{c} VPWR"
                     f" sky130_fd_pr__pfet_01v8 w=1.0 l=0.15")
    lines.append(f".ends {top}")
    out_sp.write_text("\n".join(lines) + "\n")


def normalize_bln_pins(lef_path, n_cols: int) -> None:
    """Magic's LEF writer under-reports the BL- pin when the met3 strip
    polygon is non-rectangular (the per-cell via2 bumps): it emits only
    the top fragment, and the OBS generator then covers the rest of the
    strip, leaving the router no access (DRT-0073). The strip is
    geometrically continuous (0 .. 92.40), so rewrite each BLN pin RECT
    to the full strip extent."""
    text = lef_path.read_text()
    out = []
    cur_pin = None
    for ln in text.splitlines():
        s = ln.split()
        if len(s) == 2 and s[0] == "PIN" and s[1].startswith("BLN_"):
            cur_pin = int(s[1][4:])
        if len(s) == 2 and s[0] == "END" and s[1].startswith("BLN_"):
            cur_pin = None
        if cur_pin is not None and s and s[0] == "RECT":
            x = cur_pin * 1.70 + 0.55
            ln = (f"        RECT {x:.3f} 0.000"
                  f" {x + 0.30:.3f} 92.400 ;")
        out.append(ln)
    # Same pathology for VPWR: the met4 strip + via stacks + via4 pads
    # make the net polygon non-rectangular, and Magic emits only a
    # fragment of the strip as the pin (the rest would become OBS,
    # which blocks pdngen: PDN-0006). Rewrite the met4 rect to the
    # full strip.
    out2 = []
    in_vpwr = False
    vpwr_layer = None
    for ln in out:
        s = ln.split()
        if s[:2] == ["PIN", "VPWR"]:
            in_vpwr = True
        if s[:2] == ["END", "VPWR"]:
            in_vpwr = False
        if in_vpwr and s[:1] == ["LAYER"]:
            vpwr_layer = s[1]
        if in_vpwr and s[:1] == ["RECT"] and vpwr_layer == "met4":
            ln = "        RECT 0.000 96.350 54.500 97.650 ;"
        out2.append(ln)
    lef_path.write_text("\n".join(out2) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rows", type=int)
    ap.add_argument("cols", type=int)
    ap.add_argument("pattern",
                    help="weight pattern: all_pos / all_neg / checker, or any"
                         " name when --weights-file provides the matrix")
    ap.add_argument("--weights-file",
                    help="N_ROWS lines of N_COLS chars from {+,-,0}; overrides"
                         " the builtin patterns and enables w=0 cells")
    args = ap.parse_args()

    wmat = None
    if args.weights_file:
        wmat = []
        for line in open(args.weights_file):
            line = line.strip()
            if not line:
                continue
            wmat.append([{"+": 1, "-": -1, "0": 0}[ch] for ch in line])
        assert len(wmat) == args.rows and all(len(r) == args.cols for r in wmat)

    top = f"macro_array_pc_{args.rows}x{args.cols}_{args.pattern}"
    gds = MACRO_BUILD / f"{top}.gds"
    if not gds.exists():
        print(f"ERROR: {gds} missing -- run gen_macro_array_pc.tcl first")
        return 1

    relabel_pins_to_pin_datatype(gds, top)
    bbox = read_bbox_um(gds, top)
    print(f"bbox: ({bbox[0]:.3f}, {bbox[1]:.3f}) - ({bbox[2]:.3f}, {bbox[3]:.3f}) um")

    out_lef = OUT_DIR / f"{top}.lef"
    out_lib = OUT_DIR / f"{top}.lib"
    out_v = OUT_DIR / f"{top}.bb.v"

    emit_lef_via_magic(MACRO_BUILD, top, out_lef)
    normalize_bln_pins(out_lef, args.cols)
    emit_obs_from_gds(top, gds, out_lef)
    print(f"wrote {out_lef}")
    emit_liberty(top, args.rows, args.cols, bbox, out_lib)
    print(f"wrote {out_lib}")
    emit_blackbox_verilog(top, args.rows, args.cols, out_v)
    print(f"wrote {out_v}")

    # simulation views: one bit per (row, col) for each polarity --
    # consumed by the behavioral array model and testbench expectations
    def wbit(r, c):
        if wmat is not None:
            return wmat[r][c]
        if args.pattern == "all_pos":
            return 1
        if args.pattern == "all_neg":
            return -1
        return 1 if (r + c) % 2 == 0 else -1
    for pol, val in (("pos", 1), ("neg", -1)):
        out_memh = OUT_DIR / f"{top}.w{pol}.memh"
        with open(out_memh, "w") as f:
            for r in range(args.rows):
                word = 0
                for c in range(args.cols):
                    if wbit(r, c) == val:
                        word |= 1 << c
                f.write(f"{word:08x}\n")
        print(f"wrote {out_memh}")
    out_sp = OUT_DIR / f"{top}.lvs.spice"
    emit_lvs_schematic(top, args.rows, args.cols, args.pattern, out_sp, wmat=wmat)
    print(f"wrote {out_sp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
