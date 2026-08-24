"""Author the final band LEF: take Magic's signal-pin LEF and replace the
VDD/VGND power PIN blocks with the geometry from the build_band_klayout.py
manifest (sa_se_band16_kl_power.json). Single source of truth for power pins
-> no script drift. Magic's lef-write clips full-width/ring power ports, so power
is authored here from the manifest instead.

The met3 obstruction is rebuilt as FULL coverage of the band area minus the
signal-pin shapes. Magic's own comb only obstructs where the band has met3
(the risers), leaving the inter-riser field open -- the chip router then
threads met3 wires between risers at sub-0.30 spacing to the pins (m3.2)
and attaches off-center at the stub tips (m3.1). With full OBS the router
connects at the protruding stub tips or drops via3 from met4 onto a pin.

Usage: author_band_lef.py <magic_lef> <power_json> <out_lef>
"""
import re, json, sys
magic_lef, power_json, out_lef = sys.argv[1], sys.argv[2], sys.argv[3]
t = open(magic_lef).read()
manifest = json.load(open(power_json))
pp = manifest["power"]

def pinblock(pin, use, rects):
    s = "  PIN %s\n    USE %s ;\n" % (pin, use)
    for lay, x0, y0, x1, y1 in rects:
        s += "    PORT\n      LAYER %s ;\n        RECT %.3f %.3f %.3f %.3f ;\n    END\n" % (lay, x0, y0, x1, y1)
    s += "  END %s\n" % pin
    return s

for name, rects in manifest.get("signal", []):
    blk = pinblock(name, "SIGNAL", rects)
    if re.search(r'  PIN %s\b.*?  END %s\n' % (name, name), t, re.S):
        t = re.sub(r'  PIN %s\b.*?  END %s\n' % (name, name), blk.replace("\\", "\\\\"), t, count=1, flags=re.S)
    else:
        t = t.replace("END " + re.search(r"MACRO (\S+)", t).group(1), blk + "END " + re.search(r"MACRO (\S+)", t).group(1), 1)

for pin, spec in pp.items():
    blk = pinblock(pin, spec["use"], spec["rects"])
    # replace existing PIN <pin> block if present, else insert before END MACRO
    if re.search(r'  PIN %s\b.*?  END %s\n' % (pin, pin), t, re.S):
        t = re.sub(r'  PIN %s\b.*?  END %s\n' % (pin, pin), blk, t, count=1, flags=re.S)
    else:
        t = re.sub(r'(END sa_se_band16\b)', blk + r'\1', t, count=1)

open(out_lef, "w").write(t)
# Rebuild the met3 OBS: full band area minus every met3 PIN rect.
import klayout.db as db
S = 1000
pin_rects = []
for blk in re.findall(r"  PIN .*?\n  END \S+\n", t, re.S):
    for lay, x0, y0, x1, y1 in re.findall(
            r"LAYER (\S+) ;\s*RECT ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ;", blk):
        if lay == "met3":
            pin_rects.append((float(x0), float(y0), float(x1), float(y1)))
size = re.search(r"SIZE ([\d.]+) BY ([\d.]+)", t)
W, H = float(size.group(1)), float(size.group(2))
# Clamp the cover to the design boundary (the VDD rail top, 72.80), NOT
# the LEF SIZE: the riser stubs poke past 72.80 and SIZE follows the GDS
# bbox, so covering to SIZE would entomb the stubs in OBS and leave the
# router no access at all (DRT-0073 on any pin without via3-from-met4).
H_CORE = min(H, 72.80)
# Cover from -0.30 (the GDS bbox west edge): chip wires in the
# inter-band channel hugged the westmost riser from outside the macro.
cover = db.Region(db.Box(int(round(-0.30*S)), 0, int(round(W*S)), int(round(H_CORE*S))))
pins = db.Region()
for x0, y0, x1, y1 in pin_rects:
    pins.insert(db.Box(int(round(x0*S)), int(round(y0*S)), int(round(x1*S)), int(round(y1*S))))
# 0.30 moat around the pins: via3 met3 enclosure pads landing on a pin
# must keep met3 spacing to the OBS, so OBS abutting the pins makes
# every via position illegal (DRT-0073).
obs = cover - pins.sized(300)
obs.merge()
obs_rects = []
for p in obs.each_merged():
    for r in p.decompose_trapezoids():
        b = r.bbox()
        obs_rects.append("        RECT %.3f %.3f %.3f %.3f ;" %
                         (b.left/S, b.bottom/S, b.right/S, b.top/S))
# splice: replace the met3 section inside the OBS block
def rebuild_obs(match):
    body = match.group(1)
    sections = re.split(r"(      LAYER \S+ ;\n)", body)
    out = []
    i = 0
    while i < len(sections):
        s = sections[i]
        if s.startswith("      LAYER met3"):
            i += 2  # drop this LAYER line + its RECTs
            continue
        out.append(s)
        i += 1
    kept = "".join(out)
    # met1 keepout strip west of the band: the cell's own met1 reaches
    # -0.30 and chip met1 wires hugged it at 0.02 (m1.2).
    keepout = "      LAYER met1 ;\n        RECT -0.600 0.000 -0.300 72.800 ;"
    return ("  OBS\n" + kept.rstrip("\n") + "\n" + keepout + "\n      LAYER met3 ;\n"
            + "\n".join(obs_rects) + "\n  END\n")
t2, nsub = re.subn(r"  OBS\n(.*?)\n  END\n", rebuild_obs, t, count=1, flags=re.S)
assert nsub == 1, "OBS block not found"
t = t2
open(out_lef, "w").write(t)
npin = t.count("\n  PIN ")
print("authored %s: %d PINs; full met3 OBS (%d rects) minus %d pin shapes"
      % (out_lef, npin, len(obs_rects), len(pin_rects)))
