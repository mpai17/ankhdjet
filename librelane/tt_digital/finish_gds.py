# Post-route GDS finisher for the Darga TT tile (klayout -b -r).
#
# Two jobs, both required by the TT precheck on the shipped GDS:
#
# 1. Power-net labels + PIN shapes: the TT template declares VGND/VDPWR as
#    SPECIALNETS with no pins, so the hardened GDS has no power text --
#    extraction then auto-names the power nets and LVS cannot bind them to
#    the netlist's VGND/VDPWR. One met4 PORT label on a strap of each net
#    fixes the binding; Magic's cifinput reads port labels from the PIN
#    datatype (71/16), not the label datatype (71/5). pin_check additionally
#    requires the LEF power rects to be contained in met4 PIN-datatype
#    polygons, so the two power straps' full extents are painted there too.
#    Straps: VDPWR c6.30 (5.70..6.90), VGND c11.80 (11.20..12.40), full die
#    height (see pdn_patch.tcl).
#
# 2. met5/via4 strip: TT forbids met5 (the chip-level power grid owns it).
#    The array macro carries 4 legacy met4->met5 landing pads on its VPWR
#    strip -- redundant metal above the strip, removal is
#    connectivity-neutral. via4 cuts (71/44) go with it: a via4 without met5
#    above is a dangling-cut DRC violation.
#
# Usage: klayout -b -r finish_gds.py -rd gds=<path> [-rd out=<path>]
import pya

gds = globals().get("gds")
out = globals().get("out") or gds
assert gds, "pass -rd gds=<path>"

ly = pya.Layout()
ly.read(gds)
top = ly.top_cell()
dbu = ly.dbu


def um(v):
    return int(round(v / dbu))


lt = ly.layer(71, 16)  # met4 PIN datatype
for name, x in (("VDPWR", 6.3), ("VGND", 11.8)):
    top.shapes(lt).insert(pya.Text(name, pya.Trans(um(x), um(90.0))))
    print(f"labeled {name} @ ({x}, 90.0) on met4 pin datatype")

for x0, x1 in ((5.70, 6.90), (11.20, 12.40)):
    top.shapes(lt).insert(pya.Box(um(x0), 0, um(x1), um(225.76)))
print("power pin shapes painted")

removed = 0
for ci in ly.each_cell():
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        if info.layer == 72 or (info.layer == 71 and info.datatype == 44):
            n = ci.shapes(li).size()
            if n:
                ci.shapes(li).clear()
                removed += n
print(f"met5/via4 shapes removed: {removed}")

ly.write(out)
print(f"wrote {out}")
