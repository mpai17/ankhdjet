"""Build the 16-cell sense band entirely in KLayout, with port labels injected
directly as GDS text on the metal PIN datatype (datatype 16: met1=68/16,
met2=69/16, met3=70/16, met4=71/16). Magic's cifinput maps these layers with
`labels MET<n>PIN port`, so a GDS text on 16 is read back as a real port -- the
band extracts as `.subckt sa_se_band16 VGND VDD HIT_0 BL_0 ... STROBE_15`. Text
on datatype 5 reads as plain `text` instead, which is why the cell's own 5-layer
labels are stripped below.

Base: sa_se_cell.gds (verified 1x, KLayout DRC 0). Tile 16x at 3.70um, flatten,
merge nwell over the PMOS region, and escape every signal pin on a met3 riser
that reaches a band edge.

Signal pins are met3 vertical risers that reach a macro boundary (the routable
escape the detailed router needs -- a buried met2 nub gets no FlexPA access
point). BL/STROBE/HIT exit the bottom edge, VREF exits the top edge (BL and VREF
share the cell-local x but run opposite directions, so they never overlap). Each
riser ties to its cell's met2 nub through a via2 over a 0.30um met2 landing pad.

Power binds through 4 wide (1.6um) vertical met4 legs that cross the chip's
interior met5 hstripes; pdngen's macro grid only via4-stitches the macro's own
met4 to met5, so each leg must be full-height (the band edges fall between met5
stripes, so a horizontal edge rail overlaps none) and wide enough to seat a via4
(>=1.18um). Each leg ties to its rail (VGND met1 bottom / VDD met2 top) via a
via stack.
"""
import klayout.db as db
import json as _json

import os
PITCH = 3.70
N = int(os.environ.get("ANKHDJET_BAND_N", "16"))
CELL_GDS = "cell/sky130/strongarm/build/sa_se_cell.gds"
OUT = f"cell/sky130/strongarm/build/sa_se_band{N}_kl.gds"
DBU = 0.001

# load the single cell
src = db.Layout(); src.read(CELL_GDS)
src_top = src.top_cell()

# new band layout, copy the cell hierarchy in
band = db.Layout(); band.dbu = DBU
top = band.create_cell(f"sa_se_band{N}")
imported = band.create_cell(src_top.name)
imported.copy_tree(src_top)

# place N instances at PITCH
s = 1.0 / DBU
for i in range(N):
    trans = db.Trans(db.Vector(int(round(i * PITCH * s)), 0))
    top.insert(db.CellInstArray(imported.cell_index(), trans))

# flatten the band so all metal is native top-level
top.flatten(-1, True)

# Strip the cells' OWN internal text labels (bare "BL","VREF","HIT","HITB",
# "STROBE","VDD","VGND") that flattened in 16x -- they collide with our indexed
# band ports. The cell writes these on datatype 5 (read as plain text); delete
# all datatype-5 text and re-inject only the indexed band ports (on datatype 16).
for li in band.layer_indexes():
    info = band.get_info(li)
    if info.datatype == 5:
        to_del = [sh for sh in top.shapes(li).each() if sh.is_text()]
        for sh in to_del:
            top.shapes(li).erase(sh)

def lyr(layer, datatype):
    return band.layer(layer, datatype)

# merge nwell (64/20) over the PMOS region across the band: one strip.
# Bottom edge = the cell's own nwell bottom (47.50): any lower and the
# strip swallows the latch nfets' diffusion (tops at 46.13) -- N+ in
# nwell extracts as a well tap, shorting the internal nodes to the
# well/VDD network.
nwell = lyr(64, 20)
x0 = int(-0.30 * s); y0 = int(47.5 * s)
x1 = int(((N-1)*PITCH + 3.15) * s); y1 = int(73.0 * s)
top.shapes(nwell).insert(db.Box(x0, y0, x1, y1))

def g(v): return round(round(v/0.005)*0.005, 3)   # snap to the 5nm mfg grid

def box(layer_dt, x0u, y0u, x1u, y1u):
    l, d = layer_dt
    top.shapes(band.layer(l, d)).insert(
        db.Box(int(round(g(x0u)*s)), int(round(g(y0u)*s)), int(round(g(x1u)*s)), int(round(g(y1u)*s))))

def sq(layer_dt, xc, yc, half):   # grid-snapped square cut/pad
    box(layer_dt, xc-half, yc-half, xc+half, yc+half)

def text(layer_dt, name, xum, yum):
    l, d = layer_dt
    t = db.Text(name, db.Trans(db.Vector(int(round(g(xum)*s)), int(round(g(yum)*s)))))
    top.shapes(band.layer(l, d)).insert(t)

MET1G=(68,20); MET2G=(69,20); MET3G=(70,20); MET4G=(71,20)
VIA1=(68,44); VIA2=(69,44); VIA3=(70,44)
MET3=(70,16)   # MET3PIN: cifinput reads a label here as a met3 port (risers are met3)

# --- per-SA FEOL latch-up fixes (magic drc(full) = the TT precheck runner;
# these classes are ZERO on every shipped TT project, unlike the metX.3b
# parallel-run family) ---------------------------------------------------
# (1) diff/tap.10: the SA's nwell tap (2.55..2.95 x 47.60..48.60) sits only
#     0.10 above the merged nwell strip's bottom edge (47.50); the rule wants
#     >=0.18 nwell overlap of the tap. Notch the nwell DOWN locally at the
#     tap column only -- the latch nfets' diffusion below ends at x 2.08, so
#     a notch at x 2.30..3.20 to y 47.30 touches nothing (the FULL strip
#     cannot be lowered, see the strip comment).
# (2) LU.3: the top pmos diffusions (y 58.8..71.65) sit >15um from that tap.
#     One added n-tap per SA at y ~67.1, tied to the VDD met2 top rail by a
#     private met1 riser (li pad -> mcon -> met1 -> via1 into the rail at
#     y 72.5). The tie MUST stay off li: the li in 1.0..2.7 x ~67.1 belongs
#     to HIT, and any li bridge there merges every HIT port into VDD (all
#     comparator outputs stuck high). met1 crosses the SA-top li/met2/met3
#     without contact. Tap diff 0.42 wide (licon 0.17 + 0.125 enclosure per
#     side), nsdm +0.125, li pad >=0.10 licon enclosure, clear of the pmos
#     diff (ends x 2.08) by 0.51.
NWELLG=(64,20); TAPD=(65,44); NSDM=(93,44); LI1G=(67,20); LICON=(66,44); MCON=(67,44)
def feol_latchup_fixes():
    for c in range(N):
        b = c*PITCH
        box(NWELLG, b+2.30, 47.30, b+3.15, 47.55)      # tap.10 nwell notch (3.15: the merged strip ends at (N-1)*P+3.15; wider pokes an nwell.1 sliver)
        # The tap lives in the inter-SA lane x 3.15..3.75: the SA-top is occupied
        # to x 3.13 (STROBE met2 vertical at 2.87..3.01 with met1 arms to 3.13,
        # VDD met2 feed at 1.865..2.005, HIT li at 1.0..2.7 around y 67.1), and
        # any band-level li/met1 painted over those shapes silently merges nets
        # (DRC-legal, LVS-fatal). The lane is li/met1/met2-free floor to rail.
        box(TAPD,   b+3.185, 66.90, b+3.605, 67.40)    # LU.3 top tap
        box(NSDM,   b+3.06, 66.775, b+3.73, 67.525)
        box(LI1G,   b+3.21, 66.94, b+3.58, 67.36)      # licon pad (nearest SA li ends x 2.02)
        box(LICON,  b+3.31, 67.065, b+3.48, 67.235)
        box(MCON,   b+3.31, 67.065, b+3.48, 67.235)    # li -> met1, stacked on the licon
        box(MET1G,  b+3.27, 66.99, b+3.55, 72.66)      # met1 riser; left edge 0.14 (m1.2)
                                                       # off the STROBE arm ending x 3.13
        box(VIA1,   b+3.34, 72.425, b+3.49, 72.575)    # into the band VDD met2 rail
        if c == N-1:
            # the merged pmos nwell ends at (N-1)*P+3.15 (cells abut there);
            # the last tap needs 0.18 enclosure to b+3.785, flush with the
            # cell bbox so the LEF SIZE stays 59.285.
            box(NWELLG, b+2.98, 66.70, b+3.785, 67.60)

# --- signal risers ------------------------------------------------------------
# Per signal (cell-local): nub center (x,y), riser x, riser y-span, edge.
# HIT/BL exit the BOTTOM (y_lo=-0.20), VREF/STROBE exit the TOP (y_hi=72.80).
# BL and VREF share the cell-local x (1.29) but run opposite directions, so the
# two never overlap. Splitting 2 risers per edge keeps each riser wide enough
# (0.72um) that the chip router always lands an on-grid via with legal met3
# enclosure (a 0.30um riser forces off-centre vias -> m3.4 in the chip context).
# Risers end flush at the boundaries (protruding stubs invited track
# wires 0.02 from foreign tips). Router landings at the flush ends make
# <0.30 euclidean inside corners with the riser edges (m3.1) -- those
# are same-net notches, closed post-route by the sign-off ECO fills
# (interior-only pins starve the router instead: DRT cannot converge).
# HIT and BL/VREF risers sit 0.56 apart: DRT extends landing wires up
# to ~0.21 past the pin edge, which at narrower gaps ended <0.30 from
# the neighbor riser (m3.2).
YBOT = 0.00; YTOP = 72.80
TRIM = 0.00
RW_HALF = 0.36   # riser half-width (0.72um total)
# Riser extents solve the via3 pad-poke budget: DRT places via pads up
# to 0.27 past a riser edge and extends landing wires up to 0.30, so
# every riser-to-riser (and riser-to-fixture) gap must be >= 0.60 (the
# HIT riser narrows to [0.035, 0.365] -- enclosure exactly 0.065 on
# both sides of its via2 -- giving 0.77 to BL and to the next STROBE,
# and pulling the band-edge riser inside the OBS cover). The
# via2 onto each nub moves with the riser: BL/VREF +0.01 (riser west
# enclosure exactly 0.065), STROBE west-jogged on a met2 extension of
# its nub.
SIGS = [
    # name,   via2_x, nub_y,  riser_x_lo, x_hi,  y_lo,  y_hi,  label_y
    ("HIT",    0.20,  37.65,   0.035,     0.365, YBOT,  37.90, 18.00),
    ("BL",     1.30,  25.40,   1.135,     1.71,  YBOT,  25.70, 12.00),
    ("VREF",   1.30,  34.90,   1.135,     1.71,  34.60, YTOP,  54.00),
    ("STROBE", 2.65,  16.25,   2.41,      2.97,  16.00, YTOP,  60.00),
]
RW = (N-1)*PITCH + 3.36   # band right extent for the rails

def g2(v): return round(round(v/0.005)*0.005, 3)
signal_pins = []
for i in range(N):
    bx = i * PITCH
    for nm, nx, ny, rxl, rxh, ylo, yhi, ly in SIGS:
        # The met3 riser, the via2 down to the cell's met2 nub, the met2 landing
        # pad, and the riser's port label are all built here. The label sits on
        # MET3PIN (70/16), so Magic's cifinput reads it as a port bound to the riser
        # net -> the band extracts BL_0..STROBE_15 as ports that route to each cell.
        box(MET3G, bx+rxl, ylo, bx+rxh, yhi)   # full met3 riser
        p_lo = ylo + (TRIM if ylo <= 0.0 else 0.0)
        p_hi = yhi - (TRIM if yhi >= 72.80 else 0.0)
        signal_pins.append([f"{nm}_{i}",
                            [["met3", g2(bx+rxl), g2(p_lo), g2(bx+rxh), g2(p_hi)]]])
        # met2 landing pad: covers the via2 and the cell nub (the STROBE
        # via2 is west of its nub, so the pad spans both), and reaches
        # 0.20 below so it merges the cell's lower met2 strip (no sliver)
        pad_w = bx + min(nx - 0.15, 2.79 if nm == "STROBE" else 99)
        # STROBE's via2 sits west of the cell nub strip, so the pad must
        # provide the met2 y-enclosure itself (via2.5): top at ny+0.25
        pad_t = ny + (0.25 if nm == "STROBE" else 0.15)
        box(MET2G, pad_w, ny-0.35, bx + (3.09 if nm == "STROBE" else nx + 0.15), pad_t)
        sq(VIA2,  bx+nx, ny, 0.10)   # via2 0.20
        text(MET3, f"{nm}_{i}", bx+(rxl+rxh)/2, ly)   # port label on the riser

# --- power rails (no full-width met4 -- it would block the bottom risers) ------
# Rails end 0.30/0.50 inside the cells' span: the tips fed nothing and
# chip wires hugged them at 0.02 (m2.2); Magic's ECO erase cannot remove
# subcell geometry, so the trim lives here.
box(MET1G, 0.30, 0.20, RW - 0.50, 0.80)      # VGND met1 bottom rail
box(MET2G, 0.30, 72.30, RW + 0.20, 72.80)    # VDD met2 top rail (right end covers the
                                             # last tap riser's via1 at (N-1)*P+3.49
                                             # with 0.07 enclosure)

# --- met4 power legs (the pdngen binding) + one via stack each ----------------
# pdngen's macro grid is just `add_pdn_connect met4 met5` (no added stripes): it
# only drops a via4 where the macro's OWN met4 power pin overlaps a chip met5
# hstripe. So the leg must be (1) VERTICAL/full-height to cross the interior met5
# stripe pairs (the band's top/bottom edges fall BETWEEN met5 stripes, so a
# horizontal edge rail overlaps none -> empty grid -> PDN-0232), and (2) >=1.18um
# wide so an M4M5_PR via4 (0.80 cut + 0.19 met4 enclosure/side) fits -- a 0.30um
# leg yields PDN-0110 "no via met4<->met5" and floats. 1.6um matches PDN_VWIDTH.
# Legs are 1.18um (via4 0.80 cut + 0.19 enclosure/side) and only span
# enough height to cross one chip met5 stripe pair (band-local y 25.88
# VPWR / 29.18 VGND at the y=125 placement): a full-height leg would sit
# over the top pins and block their via3 access.
LEG_HALF = 0.59
def vchan(cell): return cell*PITCH + 2.425   # VGND leg center (stack vias at vstk)
def vchan_top(cell): return cell*PITCH + 0.20  # VDD: the HIT column (riser-free at top)
# Leg x's must dodge the chip met4 vstripes (band-local x ~ 14, 34, 54) and the
# met3 risers; 9.5/50.2 (VGND) and 20.6/39.1 (VDD) clear both.
# Legs whose y-ranges overlap (VGND tops at 33, VDD starts at 18) must
# sit >= 2 cells apart -- adjacent-cell legs land 0.295 um apart on
# met4 (m4.2). Small bands carry one leg of each.
VGND_CELLS = (0,) if N < 12 else (2, N-3)   # legs that bind to VGND (met1 bottom)
VDD_CELLS  = (2,) if N < 12 else (5, N-6)   # legs that bind to VDD  (met2 top)

# Stack pads are 0.33 x 0.73: 0.065 via enclosure (m3.4/via3.4) and
# 0.24um^2 met3 area (m3.6), centered at x 2.115 cell-local -- the
# middle of the VREF..STROBE riser gap, 0.30 (met3.2) from both.
def _pads(xc, yc, layers):
    for L in layers:
        box(L, xc - 0.165, yc - 0.365, xc + 0.165, yc + 0.365)

def vstack_to_met1(xc):  # met4 leg -> VGND met1 rail (full m1->m4 stack)
    yc = 0.55
    # met1 pad only spans the via1 enclosure: it merges the met1 rail
    # below, and a taller pad passes 0.03 from a cell met1 wire (m1.2)
    box(MET1G, xc - 0.165, yc - 0.15, xc + 0.165, yc + 0.15)
    _pads(xc, yc, (MET2G, MET3G))
    sq(VIA1, xc, yc, 0.075); sq(VIA2, xc, yc, 0.10); sq(VIA3, xc, yc, 0.10)

def vstack_to_met2(xc):  # met4 leg -> VDD met2 rail (m2->m4 stack)
    yc = 72.55
    _pads(xc, yc, (MET2G, MET3G))
    sq(VIA2, xc, yc, 0.10); sq(VIA3, xc, yc, 0.10)

def vstk(cell): return cell*PITCH + 2.515   # stack x: clear of BL landing-wire reach
for c in VGND_CELLS:
    box(MET4G, vchan(c)-LEG_HALF, 0.20, vchan(c)+LEG_HALF, 33.00)   # leg crosses the stripe pair
    vstack_to_met1(vstk(c))                                         # tie to VGND met1
for c in VDD_CELLS:
    # leg spans the top rail tie (via3 top 72.65 + 0.065 met4 enclosure)
    # down across the stripe pair; the HIT column is met3-free above 37.9
    # and HIT keeps its bottom stub + via3 access below y 18.
    box(MET4G, vchan_top(c)-LEG_HALF, 18.00, vchan_top(c)+LEG_HALF, 72.75)
    vstack_to_met2(vchan_top(c))                                           # tie to VDD met2

feol_latchup_fixes()

# Power port labels (so Magic's chip extraction recognises VGND/VDD ports). Like
# the signal risers, inject as GDS text on the metal PIN datatype (met1=68/16,
# met2=69/16, met4=71/16) -- cifinput reads these as ports on the rail nets.
MET1L=(68,16); MET2L=(69,16); MET4L=(71,16)
text(MET1L, "VGND", 5.0, 0.50)            # VGND met1 bottom rail
text(MET2L, "VDD",  5.0, 72.55)           # VDD met2 top rail
# Labels must sit ON leg metal: the VGND legs span y 0.2..33.0, and a label at
# y 36 floats on empty space -- Magic then names a zero-area node "VGND" and the
# extracted port binds to nothing (the real leg metal ends up on an anonymous
# node). The VDD legs span 18..72.75, so y 36 is on-metal for them.
for c in VGND_CELLS: text(MET4L, "VGND", vchan(c), 30.0)   # VGND met4 ring edges
for c in VDD_CELLS:  text(MET4L, "VDD",  vchan_top(c), 36.0)   # VDD met4 ring edges

# Power-pin manifest: ONE source of truth for the LEF authoring step. Each entry:
# (layer, x0,y0,x1,y1). Power is a met1/met2 rail plus two 1.6um vertical met4 legs
# per net (the pdngen via4-to-met5 binding pins).
RE_HALF = LEG_HALF
power_pins = {
    "VGND": {"use": "GROUND", "rects": [
        ["met1", 0.30, 0.20, RW - 0.50, 0.80],
    ] + [["met4", vchan(c)-RE_HALF, 0.20, vchan(c)+RE_HALF, 33.00]
         for c in VGND_CELLS]},
    "VDD": {"use": "POWER", "rects": [
        ["met2", 0.30, 72.30, RW - 0.50, 72.80],
    ] + [["met4", vchan_top(c)-RE_HALF, 18.00, vchan_top(c)+RE_HALF, 72.75]
         for c in VDD_CELLS]},
}
# Magic carves the met3 obstruction comb itself (the risers are full-height met3
# ports), so only the power pins need a manifest.
manifest = {"power": power_pins, "signal": signal_pins}
_json.dump(manifest, open(OUT.replace(".gds", "_power.json"), "w"), indent=1)

# PR boundary (areaid.sc 235/4) covering the band
prb = band.layer(235, 4)
b = top.bbox()
top.shapes(prb).insert(db.Box(b.left, b.bottom, b.right, b.top))

band.write(OUT)
b = top.bbox()
print(f"wrote {OUT}")
print(f"  size {(b.right-b.left)*DBU:.2f}x{(b.top-b.bottom)*DBU:.2f}um  children={band.cells()-1}")
labs = [sh.text_string for li in band.layer_indexes() for sh in top.shapes(li).each() if sh.is_text()]
sig = [l for l in labs if any(l.startswith(p) for p in ("BL_","VREF_","HIT_","STROBE_"))]
print(f"  injected: {len(sig)} signal risers on met3")
