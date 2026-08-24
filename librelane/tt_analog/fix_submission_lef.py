# Normalize the shipped LEF for TT precheck's pin_check + power_pin_check.
#
# Magic's WriteLEF merges each template pin's PORT with the routed metal
# attached to it (rst_n becomes 0.3 x 11.7), but pin_check requires the LEF
# rect to match the template DEF stub EXACTLY (and then checks the GDS pin
# shape contains that rect -- our GDS stubs are already template-exact, so
# fixing the LEF fixes both error families). Magic also writes no power pins;
# power_pin_check requires PIN VGND (USE GROUND) + PIN VDPWR (USE POWER).
#
# Usage: uv run fix_submission_lef.py <lef> <template_def>
import re
import sys

lef_path, def_path = sys.argv[1], sys.argv[2]

# template pins: name -> (layer, absolute rect in um)
pins = {}
cur = None
for ln in open(def_path):
    m = re.match(r"\s*- (\S+) \+ NET", ln)
    if m:
        cur = m.group(1)
        continue
    m = re.match(r"\s*\+ LAYER (\S+) \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)", ln)
    if m and cur:
        pins[cur] = [m.group(1), *(int(g) for g in m.groups()[1:])]
        continue
    m = re.match(r"\s*\+ (?:PLACED|FIXED) \( (-?\d+) (-?\d+) \)", ln)
    if m and cur and cur in pins:
        layer, x0, y0, x1, y1 = pins[cur]
        px, py = int(m.group(1)), int(m.group(2))
        pins[cur] = (layer, (px + x0) / 1000, (py + y0) / 1000, (px + x1) / 1000, (py + y1) / 1000)
        cur = None

lef = open(lef_path).read()
fixed = 0
for name, (layer, x0, y0, x1, y1) in pins.items():
    # replace the whole PORT geometry of this pin with the template rect
    pat = re.compile(
        r"(PIN " + re.escape(name) + r"\n(?:.*\n)*?\s*PORT\n)(?:.*\n)*?(\s*END\n\s*END " + re.escape(name) + r")",
        re.MULTILINE,
    )
    rect = f"      LAYER {layer} ;\n        RECT {x0:.3f} {y0:.3f} {x1:.3f} {y1:.3f} ;\n"
    new, n = pat.subn(lambda m: m.group(1) + rect + m.group(2), lef, count=1)
    if n:
        lef = new
        fixed += 1

# Analog pins are direction-less wires into the pad mux: the TT template
# declares every ua pin INOUT, and the submission validator rejects any
# other direction. Magic writes them as INPUT (VREF is only ever driven
# in), so normalize here.
lef, ua_fixed = re.subn(
    r"(PIN ua\[\d+\]\n\s*DIRECTION )INPUT( ;)",
    r"\1INOUT\2",
    lef,
)

# power pins: met4 rects on the patch straps (VDPWR c84.35, VGND c145.35 --
# where the painter puts the matching GDS labels)
power = """  PIN VGND
    DIRECTION INOUT ;
    USE GROUND ;
      PORT
      LAYER met4 ;
        RECT 11.200 0.000 12.400 225.760 ;
      END
  END VGND
  PIN VDPWR
    DIRECTION INOUT ;
    USE POWER ;
      PORT
      LAYER met4 ;
        RECT 5.700 0.000 6.900 225.760 ;
      END
  END VDPWR
"""
if "PIN VGND" not in lef:
    lef = re.sub(r"^END ", power + "END ", lef, count=1, flags=re.MULTILINE)

open(lef_path, "w").write(lef)
print(f"fixed {fixed} template pin rects; {ua_fixed} ua pins set INOUT; power pins {'added' if 'PIN VGND' in lef else 'MISSING'}")
