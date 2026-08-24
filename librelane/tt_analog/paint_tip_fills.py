# Post-route met3 tip-fill painter for the Azara TT tile GDS (klayout -b -r).
#
# DRT enters the bands' bottom-entry VREF/STROBE pin strips at their tips
# (abs y 6.2) with met2->met3 vias whose stub/pad geometry leaves 0.08-0.2um
# step notches in the union -- ~100x KLayout m3.1 (met3 width). Painting each
# strip's column over the tip zone absorbs the entry geometry into one clean
# rectangle. This CANNOT be done pre-route (GRT skips signal nets that carry
# special wires -- they'd end up unrouted), so it runs on the final GDS; the
# paint is same-net by construction (it only touches the strip column and the
# entry stubs landing on it) and each site is checked for foreign met3 within
# spacing distance first (painted only if clear, else reported).
#
# Geometry (from sa_se_band16 LEF/GDS + macro_tile.cfg, bands FS @ (23.715,6) and
# (85.715,6)): VREF family columns x_rel 1.135..1.710 + 3.7k (widened 0.12 LEFT
# only -- band-internal met3 sits exactly 0.30 to the right), STROBE family
# x_rel 2.410..2.970 + 3.7k (widened 0.16 RIGHT only -- internal met3 0.30 to
# the left); tips at abs y 6.2, paint y 5.9..6.9.
#
# Usage: klayout -b -r paint_tip_fills.py -rd gds=<path> [-rd out=<path>]
import pya

gds = globals().get("gds")
out = globals().get("out") or gds
assert gds, "pass -rd gds=<path>"

ly = pya.Layout()
ly.read(gds)
top = ly.top_cell()
dbu = ly.dbu
li = ly.layer(70, 20)  # met3 drawing

met3 = pya.Region(top.begin_shapes_rec(li))
met3.merge()

def um(v):
    return int(round(v / dbu))

sites = []
for bx in (23.715, 85.715):
    for k in range(16):
        vx0 = bx + 1.135 + 3.7 * k
        sites.append((vx0 - 0.12, vx0 + 0.575, "VREF"))
        sx0 = bx + 2.410 + 3.7 * k
        sites.append((sx0, sx0 + 0.560 + 0.16, "STROBE"))

painted, skipped = 0, 0
for x0, x1, fam in sites:
    rect = pya.Box(um(x0), um(5.9), um(x1), um(6.9))
    # clearance probe: anything within 0.28 of the paint that is NOT already
    # touching the strip column would end up spacing-violated -> skip site
    probe = pya.Region(rect.enlarged(um(0.28), um(0.28)))
    nearby = met3 & probe
    col = pya.Region(pya.Box(um(x0 - 0.05), um(4.0), um(x1 + 0.05), um(9.0)))
    foreign = nearby - (nearby.interacting(col))
    if not foreign.is_empty():
        skipped += 1
        print(f"SKIP {fam} @ x {x0:.3f}..{x1:.3f}: foreign met3 within spacing")
        continue
    top.shapes(li).insert(rect)
    painted += 1

print(f"tip fills painted: {painted}, skipped: {skipped}")

# power-net labels: the TT template declares VGND/VDPWR as SPECIALNETS with no
# pins, so the hardened GDS has no power text anywhere -- extraction then
# auto-names the power nets (VSUBS / first-pin) and LVS cannot bind them to
# the netlist's VGND/VDPWR. One met4 PORT label on a strap of each net fixes
# the binding. Magic's cifinput reads port labels from the PIN datatype
# (71/16), not the label datatype (71/5) -- the band generator's proven
# pattern. Texts placed mid-strap on c70.85/c76.35.
lt = ly.layer(71, 16)
for name, x in (("VDPWR", 6.3), ("VGND", 11.8)):
    top.shapes(lt).insert(pya.Text(name, pya.Trans(um(x), um(90.0))))
    print(f"labeled {name} @ ({x}, 90.0) on met4 pin datatype")

# power PIN shapes: pin_check requires the LEF power rects to be contained
# in met4 PIN-datatype (71/16) polygons; paint the two power straps' extents.
for x0, x1 in ((5.70, 6.90), (11.20, 12.40)):
    top.shapes(lt).insert(pya.Box(um(x0), 0, um(x1), um(225.76)))
print("power pin shapes painted")

# strip met5 (layer 72, all datatypes): TT forbids it (the chip-level power
# grid owns met5). The array macro carries 4 legacy met4->met5 landing pads on
# its VPWR strip -- redundant metal above the strip, removal is
# connectivity-neutral.
removed = 0
for ci in ly.each_cell():
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        # met5 itself (72/*) and via4 cuts (71/44) -- a via4 without met5
        # above is a dangling-cut DRC violation
        if info.layer == 72 or (info.layer == 71 and info.datatype == 44):
            n = ci.shapes(li).size()
            if n:
                ci.shapes(li).clear()
                removed += n
print(f"met5/via4 shapes removed: {removed}")

ly.write(out)
print(f"wrote {out}")
