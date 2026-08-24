# Macro top-level: stack v4_array_NxM (mask-programmed) above
# precharge_row, with shared column pitch. This is the silicon
# core of the NOR-array memory bank -- the part that physically
# discharges BLs against precharge devices.
#
# Stack:
#   precharge_row32   y = array_top .. array_top + 1.15 um
#   v4_array_NxM      y = 0 .. array_top
#
# Both blocks share the 1.20 um column pitch, so abutment lines up
# with 0.11 um inter-cell gap accommodated by both the array's BL+
# M2 strip (col-east x=c*1.20+0.825) and the precharge cell's nwell
# strap.
#
# Inputs from env:
#   ANKHDJET_ARRAY_N    rows    (default 64)
#   ANKHDJET_ARRAY_M    cols    (default 32)
#   ANKHDJET_WEIGHTS    pattern (default checker)
#
# Run via:
#   cd build
#   ANKHDJET_ARRAY_N=64 ANKHDJET_ARRAY_M=32 \
#     magic -dnull -noconsole -T sky130A < ../gen_macro_array_pc.tcl
#
# Requires:
#   ../../bitcell_v4/build/v4_array_${N}x${M}_${PATTERN}.mag
#   ../../precharge/build/precharge_row${M}.mag
# (the script copies these into cwd as a self-contained build).

set N_ROWS  [expr {[info exists ::env(ANKHDJET_ARRAY_N)] ? $::env(ANKHDJET_ARRAY_N) : 64}]
set N_COLS  [expr {[info exists ::env(ANKHDJET_ARRAY_M)] ? $::env(ANKHDJET_ARRAY_M) : 32}]
set PATTERN [expr {[info exists ::env(ANKHDJET_WEIGHTS)] ? $::env(ANKHDJET_WEIGHTS) : "checker"}]

set ARRAY_NAME    "v4_array_${N_ROWS}x${N_COLS}_${PATTERN}"
set PRECHARGE_NAME "precharge_row${N_COLS}"
set MACRO_NAME    "macro_array_pc_${N_ROWS}x${N_COLS}_${PATTERN}"

set ARRAY_SRC    "../../bitcell_v4/build/${ARRAY_NAME}"
set PRECHARGE_SRC "../../precharge/build/${PRECHARGE_NAME}"

# Magic only auto-sources ./.magicrc, not ../.magicrc; the parent's
# .magicrc is the canonical PDK setup, so source it here when the
# build dir lacks its own copy.
if {[tech name] ne "sky130A"} {
    if {[file exists "../.magicrc"]} {
        source "../.magicrc"
    }
}

drc off

# Pull leaf cells into cwd so this build is self-contained
foreach c [list $ARRAY_NAME $PRECHARGE_NAME] {
    foreach ext {mag gds} {
        set src ""
        switch -glob -- $c {
            v4_array_*    { set src "../../bitcell_v4/build/$c.$ext" }
            precharge_*   { set src "../../precharge/build/$c.$ext" }
        }
        if {[file exists $src]} {
            file copy -force $src "./$c.$ext"
        }
    }
}
# Also pull the leaf-cell dependencies (bitcell_v4, body_tap, precharge).
foreach dep {bitcell_v4 body_tap precharge} {
    foreach ext {mag gds} {
        foreach src [list "../../bitcell_v4/build/$dep.$ext" \
                          "../../precharge/build/$dep.$ext"] {
            if {[file exists $src]} {
                file copy -force $src "./$dep.$ext"
            }
        }
    }
}

file delete -force "${MACRO_NAME}.mag" "${MACRO_NAME}.gds" "${MACRO_NAME}.ext"
load $MACRO_NAME -quiet
select top cell
cellname rename "(UNNAMED)" $MACRO_NAME

# Place array at origin
box position 0um 0um
getcell $ARRAY_NAME

# Read array bbox to learn its placement offset and top Y. Magic's
# getcell places the cell so its bbox lower-left = box position;
# since the array's internal bbox extends to (-0.10, -0.05) (WL strap
# overhang + BL strip overhang), the array's internal cell origins
# shift by (+0.10, +0.05) in absolute macro coords. Macro paints
# below add the same shift so they line up with the array's
# internal columns.
select cell ${ARRAY_NAME}_0
set ab [box values]
set array_left  [expr {[lindex $ab 0] / 200.0}]
set array_top   [expr {[lindex $ab 3] / 200.0}]
# Internal bbox lower-left (relative to placement = abs (0,0)):
#   internal x = abs x - placement_x = abs x - array_left
# Cell origin internal x=0 is at abs x_origin = -internal_x_lower_left
#   = -(internal lower-left X)
# Easier: shift = abs lower-left - internal lower-left (which is
# baked into the array's bbox). Compute via a probe getcell at
# (0,0) to learn where internal (0,0) lands. Skip; instead use
# the known internal layout: the array's WL strap extends 0.10 um
# west of the leftmost cell origin, so the shift is +0.10 in x.
set array_shift_x 0.10
set array_shift_y 0.05
puts "array bbox: $ab  array_top_um=$array_top  shift=($array_shift_x,$array_shift_y)"

# Place precharge row directly above the array, applying the same
# X shift so columns align with the array.
box position ${array_shift_x}um ${array_top}um
getcell $PRECHARGE_NAME

# Per-column precharge D -> BL+ routing.
# The precharge cell's native D M1 plate is 0.265 um wide -- too
# narrow on its own to enclose a 0.26 um via1 with via.4a 0.055
# directional. Macro-level fix: paint an M1 extension that grows
# the D pin WEST (into the inter-cell gap, where there's no
# conflict) and UP (into the cell's gate-poly y-region, M1 over
# poly is fine). via1 lands on this enlarged D pin, then M2 patch
# extends east to merge with the BL+ M2 strip at col-east.
#
# Precharge cell origin (lower-left at box position): cell extends
# x=[c*1.20, c*1.20+1.09], y=[array_top, array_top+1.04]. Cell
# internal origin maps to absolute (c*1.20+0.545, array_top+0.52).
# D plate cell-local x=[-0.335, -0.07], y=[-0.16, +0.16].
# BL+ M2 strip at abs x=c*1.20+0.825 (col-east in inter-cell gap).
set CELL_W_PC 1.70
# Extend each BL+ M4 strip up through the precharge_row at the same
# 0.30 um width as the array's BL+ M4 strip so the merged polygon has
# uniform width. BL+ moved from M2 to M4 to eliminate full-height
# met2 strips that caused ~1700 chip-level met2.3b spacing violations.
set blp_top [expr $array_top + 3.40]
for {set c 0} {$c < $N_COLS} {incr c} {
    set blp_x [expr $c * $CELL_W_PC + 1.45 + $array_shift_x]
    # Extend from array_top - 0.10 so the extension overlaps the
    # array's BL+ M4 strip (which tops at array_top) -- Magic's
    # tile engine needs actual overlap to merge them into one
    # polygon for the LEF pin extraction.
    box [expr $blp_x - 0.15]um [expr $array_top - 0.10]um \
        [expr $blp_x + 0.15]um ${blp_top}um
    paint metal4
}

for {set c 0} {$c < $N_COLS} {incr c} {
    # Precharge pair: row A (lower, upright) pulls BL-, row B (upper,
    # flipped) pulls BL+. Cell centers: x = c*1.70 + 0.745; row A
    # center y = array_top + 0.86, row B center y = array_top + 2.91
    # (the row's bbox lower-left (-0.10,-0.05) sits at (0.10, array_top)).
    set pc_ox  [expr $c * $CELL_W_PC + 0.745]
    set cy_a   [expr $array_top + 0.86]
    set cy_b   [expr $array_top + 2.91]
    set blp_x  [expr $c * $CELL_W_PC + 1.45 + $array_shift_x]
    set bln_w  [expr $c * $CELL_W_PC + 0.55 + $array_shift_x - 0.10]
    set bln_e  [expr $bln_w + 0.42]

    # --- row B drain -> BL+ (met4) ---
    box [expr $pc_ox - 0.645]um [expr $cy_b - 0.16]um \
        [expr $pc_ox - 0.275]um [expr $cy_b + 0.40]um
    paint metal1
    box [expr $pc_ox - 0.59]um [expr $cy_b + 0.05]um \
        [expr $pc_ox - 0.33]um [expr $cy_b + 0.31]um
    paint via1
    box [expr $pc_ox - 0.645]um [expr $cy_b - 0.10]um \
        [expr $blp_x + 0.085]um [expr $cy_b + 0.37]um
    paint metal2
    # The via stack sits WEST of the strip center so the met2 jog ends
    # 0.165 before the next column's jog (adjacent jogs abutted at the
    # cell boundary otherwise -- the silent all-BLP short).
    set via_cy [expr $cy_b + 0.10]
    box [expr $blp_x - 0.24]um [expr $via_cy - 0.14]um \
        [expr $blp_x + 0.04]um [expr $via_cy + 0.14]um
    paint via2
    box [expr $blp_x - 0.31]um [expr $via_cy - 0.28]um \
        [expr $blp_x + 0.135]um [expr $via_cy + 0.28]um
    paint metal3
    box [expr $blp_x - 0.25]um [expr $via_cy - 0.16]um \
        [expr $blp_x + 0.07]um [expr $via_cy + 0.16]um
    paint via3
    box [expr $blp_x - 0.35]um [expr $via_cy - 0.25]um \
        [expr $blp_x + 0.15]um [expr $via_cy + 0.25]um
    paint metal4

    # --- row A drain -> BL- (met3, via a local widening of the strip) ---
    box ${bln_w}um [expr $array_top - 0.10]um ${bln_e}um [expr $array_top + 1.30]um
    paint metal3
    box [expr $pc_ox - 0.645]um [expr $cy_a - 0.16]um \
        [expr $pc_ox - 0.275]um [expr $cy_a + 0.40]um
    paint metal1
    box [expr $pc_ox - 0.59]um [expr $cy_a + 0.05]um \
        [expr $pc_ox - 0.33]um [expr $cy_a + 0.31]um
    paint via1
    box [expr $pc_ox - 0.645]um [expr $cy_a - 0.10]um \
        [expr $bln_e + 0.02]um [expr $cy_a + 0.37]um
    paint metal2
    box [expr $bln_w + 0.07]um [expr $cy_a - 0.04]um \
        [expr $bln_w + 0.35]um [expr $cy_a + 0.24]um
    paint via2
}

# VPWR M1 row rail at the top of precharge_row, connecting all
# precharge S terminals via per-cell vertical M1 strips. Source
# plate sits at cell-local x=[+0.07, +0.335], y=[-0.16, +0.16];
# cell-local y >+0.16 has no other M1 in the source X range, so
# vertical M1 from source plate top up to a horizontal rail above
# the cell merges the sources into one VPWR net.
# Rail bottom needs met1.3b 0.28 spacing to the macro's
# precharge-D M1 extension plate (which tops out at array_top+0.97)
# because the rail is > 3 um long.
set vpwr_y_lo [expr $array_top + 4.05]
set vpwr_y_hi [expr $array_top + 4.45]
set rail_x_lo  0.0
set rail_x_hi  [expr $N_COLS * $CELL_W_PC + $array_shift_x]
box ${rail_x_lo}um ${vpwr_y_lo}um ${rail_x_hi}um ${vpwr_y_hi}um
paint metal1
box ${rail_x_lo}um ${vpwr_y_lo}um ${rail_x_hi}um ${vpwr_y_hi}um
label VPWR
port make
for {set c 0} {$c < $N_COLS} {incr c} {
    set pc_ox [expr $c * $CELL_W_PC + 0.745]
    # Per-cell vertical M1 source strap. The strap is > 3 um long, so
    # Magic's met1.3b wants 0.28 to the (also-long) merged gate-cap
    # column: the strap runs at pc_ox+[0.415, 0.555] (0.28 from the cap
    # east edge) and short per-row stubs bridge it into each source
    # plate, passing y-clear of the cap.
    box [expr $pc_ox + 0.415]um [expr $array_top + 0.79]um \
        [expr $pc_ox + 0.555]um [expr $vpwr_y_lo + 0.001]um
    paint metal1
    box [expr $pc_ox + 0.105]um [expr $array_top + 0.36]um \
        [expr $pc_ox + 0.555]um [expr $array_top + 1.36]um
    paint metal1
    box [expr $pc_ox + 0.105]um [expr $array_top + 2.41]um \
        [expr $pc_ox + 0.555]um [expr $array_top + 3.41]um
    paint metal1
}

# VGND M1 row rail above VPWR (1.85..2.10, 0.35 um separation from
# VPWR rail satisfies met1.3b 0.28). VGND is exposed as a LEF pin so
# LibreLane can route the chip's ground rail to this macro; the bitcell
# sources tie to substrate (pwell) which is biased to chip VGND via
# the standard cell tap row at chip top level. This M1 strap is a
# logical pin; no internal current carrier (bitcell sources flow into
# pwell directly, not through this strap).
set vgnd_y_lo [expr $array_top + 4.90]
set vgnd_y_hi [expr $array_top + 5.30]
box ${rail_x_lo}um ${vgnd_y_lo}um ${rail_x_hi}um ${vgnd_y_hi}um
paint metal1
box ${rail_x_lo}um ${vgnd_y_lo}um ${rail_x_hi}um ${vgnd_y_hi}um
label VGND
port make

# Internal n-taps inside the precharge nwell strip (clears nwell.4 +
# LU.3 chip-level violations). Sizing per OpenRAM precharge_0.mag
# precedent + body_tap.tcl reference: nsubdiff 0.41 x 0.29 with a
# 0.17 x 0.17 nsubdiffcont and 0.33 x 0.29 locali.
#
# The precharge cells are 1.09 x 1.04 um and packed too tight to fit
# the tap inside without conflicting with PMOS active (diff/tap.3 +
# licon.2 fire when the tap lands on a cell internal). Solution:
# paint a small nwell extension ABOVE each tap location (y=array_top+
# 1.00 to 1.30), bridging into the existing precharge cell nwell
# (which ends at y=array_top+1.04) and placing the tap inside the
# extended region clear of PMOS. 2 taps (25% + 75% across the 38.4
# um row) cover LU.3 15-um latch-up distance with margin.
foreach cx {7.65 22.95 38.25 49.30} {
    # nwell extension (>= 0.84 x 0.84 per nwell.1 min width; merges with
    # precharge cell nwell which tops at array_top+1.04). Bottom edge
    # at array_top+0.88 overlaps cell nwell; top at array_top+1.72
    # extends above precharge_row top, under the VPWR M1 rail.
    set nw_y_lo [expr $array_top + 3.60]
    set nw_y_hi [expr $array_top + 4.58]
    box [expr $cx - 0.60]um ${nw_y_lo}um [expr $cx + 0.60]um ${nw_y_hi}um
    paint nwell

    # n-tap centered in the extension, 0.395 nwell enclosure each side
    # in x (>= 0.18 diff/tap.10), 0.275 in y; 0.355 from precharge pdiff
    # (>= 0.27 diff/tap.3).
    set cy [expr $array_top + 4.25]
    box [expr $cx - 0.205]um [expr $cy - 0.145]um \
        [expr $cx + 0.205]um [expr $cy + 0.145]um
    paint nsubdiff
    box [expr $cx - 0.085]um [expr $cy - 0.085]um \
        [expr $cx + 0.085]um [expr $cy + 0.085]um
    paint nsubdiffcont
    # li extends up into the VPWR M1 rail with a viali, physically
    # tying the nwell to the rail (a label alone does not survive
    # the chip flow's `extract unique`).
    box [expr $cx - 0.165]um [expr $cy - 0.145]um \
        [expr $cx + 0.165]um [expr $array_top + 4.42]um
    paint locali
    box [expr $cx - 0.085]um [expr $array_top + 4.20]um \
        [expr $cx + 0.085]um [expr $array_top + 4.37]um
    paint viali
    box [expr $cx - 0.165]um [expr $cy - 0.145]um \
        [expr $cx + 0.165]um [expr $cy + 0.145]um
    label VPWR
    port make
    port use power
}

# ---------------------------------------------------------------------
# Met4 PIN copper for chip-level PDN connectivity.
# Production pattern (per OpenRAM sky130_sram_macros): expose VPWR/VGND
# on met4 (PDN_VERTICAL_LAYER default) so chip-level pdngen stripes can
# overlap and drop vias. The via stack via1+via2+via3 is the macro
# author's responsibility; pdngen is overlap-driven only.
#
# Layout: a via1+via2+via3+met4 stack above each M1 rail. The via stack
# is centered along the macro width to land under typical PDN stripes.
#
# SKY130 enclosures (consulted from sky130A.tech via.5/met2.4/via2.5
# /met3.4/via3.5/met4.4 rules):
#   via1   0.26 x 0.26 cut, met1.4 enclosure 0.06, met2.4 enclosure 0.06
#   via2   0.20 x 0.20 cut, met2.4 enclosure 0.04, met3.4 enclosure 0.065
#   via3   0.20 x 0.20 cut, met3.4 enclosure 0.06, met4.4 enclosure 0.065
# Magic's `paint via1/via2/via3` registers the contact layer; the LEF
# extractor emits a CUT layer + adjacent metal patches automatically.

# VPWR via stack at x=8..8.40 (0.40 wide -- meets via.1a 0.26 + 2*0.07
# enclosures on each side for met2.4 and met3.4 0.06+0.07 enclosures).
# M1 rail is now 0.40 um tall so via1/2/3 each get a 0.40x0.40 footprint
# with proper enclosures on adjacent metal pads.
set vp_via_x_lo 8.00
set vp_via_x_hi 8.40
box ${vp_via_x_lo}um ${vpwr_y_lo}um ${vp_via_x_hi}um ${vpwr_y_hi}um
paint via1
# met2 pad with met2.4 0.06 enclosure
box [expr $vp_via_x_lo - 0.06]um [expr $vpwr_y_lo - 0.06]um \
    [expr $vp_via_x_hi + 0.06]um [expr $vpwr_y_hi + 0.06]um
paint metal2
box ${vp_via_x_lo}um ${vpwr_y_lo}um ${vp_via_x_hi}um ${vpwr_y_hi}um
paint via2
# met3 pad with met3.4 0.07 enclosure
box [expr $vp_via_x_lo - 0.07]um [expr $vpwr_y_lo - 0.07]um \
    [expr $vp_via_x_hi + 0.07]um [expr $vpwr_y_hi + 0.07]um
paint metal3
box ${vp_via_x_lo}um ${vpwr_y_lo}um ${vp_via_x_hi}um ${vpwr_y_hi}um
paint via3
# Met4 PIN copper -- full-width strip, 1.40 um tall so a chip met5
# VPWR stripe crossing it can drop a via4 (0.80 cut + 0.19 enclosure
# per side needs >= 1.18 um of met4). Bottom sits 0.30 (met4.2) above
# the BL+ strip tops at array_top + 0.85; the macro is placed so this
# strip centers under a chip met5 VPWR stripe. Bottom sits 0.33 above
# the precharge M4 patches (top at array_top + 0.92).
box ${rail_x_lo}um [expr $array_top + 3.95]um \
    ${rail_x_hi}um [expr $array_top + 5.25]um
paint metal4
# VPWR met4 port label (binds to topmost layer at box = metal4)
box ${rail_x_lo}um [expr $array_top + 3.95]um \
    ${rail_x_hi}um [expr $array_top + 5.25]um
label VPWR
port make

# met5 pads + via4 on the VPWR met4 strip, at the y of the chip met5
# VPWR stripe (the macro is placed so the stripe [110.08, 111.68]
# covers macro y [93.50, 95.10]). pdngen never drops a via between
# PARALLEL met4/met5 overlaps (PDN-0110), so the macro carries its own
# via4s; the pads merge with the chip stripe as same-layer metal in
# the flat extraction. The pads are excluded from the LEF (no met5
# pin/OBS) so pdngen lays the stripe straight over them.
# ANKHDJET_NO_MET5=1 omits the pads (and their via4): TinyTapeout tiles
# forbid met5 (reserved for the TT chip grid); there the tile's
# vertical met4 PDN stripes overlap-bind the macro met4 strip instead.
if {![info exists ::env(ANKHDJET_NO_MET5)] || !$::env(ANKHDJET_NO_MET5)} {
    foreach vx {8.2 22.0 36.0 50.0} {
        box [expr $vx - 1.30]um [expr $array_top + 3.80]um \
            [expr $vx + 1.30]um [expr $array_top + 5.40]um
        paint metal5
        box [expr $vx - 0.59]um [expr $array_top + 4.06]um \
            [expr $vx + 0.59]um [expr $array_top + 5.24]um
        paint via4
    }
}

# PRE_N pin: via2 from the precharge row's met2 gate backbone
# (y = array_top + [1.71, 2.09]) up to a met3 riser in the met3-free
# lane between BL- strips, protruding 0.20 past the macro top so the
# router lands on it outside the OBS (horizontal met3 tracks cross
# the stub there -- the proven band-pin pattern).
set pre_x 15.89
box [expr $pre_x - 0.14]um [expr $array_top + 1.755]um \
    [expr $pre_x + 0.14]um [expr $array_top + 2.035]um
paint via2
box [expr $pre_x - 0.205]um [expr $array_top + 1.69]um \
    [expr $pre_x + 0.205]um [expr $array_top + 5.50]um
paint metal3
box [expr $pre_x - 0.05]um [expr $array_top + 5.30]um \
    [expr $pre_x + 0.05]um [expr $array_top + 5.40]um
label PRE_N c metal3
port make

# No VGND via stack or met4 strip: VGND is carried by the substrate
# (the source/read-line ground network ties the M1 rail, the body
# taps, and the bitcell sources to the pwell, which the chip's tap
# rows bias to chip VGND). The M1 rail remains the LEF pin.

# PR boundary FIXED_BBOX property is set just before save (below)
# at the correct point in the flow when [box values] reflects the
# cell bbox.

# StrongARM SA is a SEPARATE hard macro -- placed at chip level by
# LibreLane (not inside this array+precharge tile). The SA's pin
# pitch is column-mux'd (BLP/BLN spacing 6 um vs array BL pitch
# 0.225 um), so direct integration here was geometrically infeasible
# at 1.20 um column pitch. Chip-level integration: column mux is
# synthesized digital (TGATE std cells) connecting BLP_<c>/BLN_<c>
# pins to the SA's BLP/BLN inputs.

# Magic's tile-engine doesn't fire spurious met2.1 at subcell-
# boundary M2 polygons. KLayout's geometric DRC sees no narrow M2
# either way, but flattening keeps Magic+KLayout in agreement.
# -dolabels keeps existing top-level labels (VPWR) in the flattened
# cell. Pin labels for BL+/BL-/WL are added BELOW the flatten
# because the underlying M1/M2/M3 layers come from the bitcell array
# subcell -- before flatten, paint at those positions doesn't bind
# to the right layer at the macro top level.
flatten -dolabels $MACRO_NAME
load $MACRO_NAME -quiet
select top cell

# Top-level pin labels (post-flatten). Each BL+/BL- M2/M3 strip and
# each WL M1 strap gets a Magic port label so digital periphery
# synthesis can wire to them.
set CELL_H_PC 1.30
set TAP_H_PC  1.30
set TAP_EVERY_PC [expr {[info exists ::env(ANKHDJET_TAP_EVERY)] ? $::env(ANKHDJET_TAP_EVERY) : 8}]
for {set c 0} {$c < $N_COLS} {incr c} {
    # BLP_<col> on M4 BL+ strip at top. Paint a wider M4 patch at the
    # top of the strip and label it, so the LEF pin shape includes the
    # full M4 strip below (Magic traces the connected polygon from the
    # label).
    set blp_x [expr $c * $CELL_W_PC + 1.45 + $array_shift_x]
    # Paint a unified M4 strip in the macro from array bottom (y=0)
    # to extension top, merging with any pre-existing M4 (from the
    # flattened array + per-cell w=+1 patches + extension). Then
    # label the same box.
    box [expr $blp_x - 0.15]um 0um \
        [expr $blp_x + 0.15]um ${blp_top}um
    paint metal4
    label BLP_$c
    port make
    # BLN_<col> on M3 BL- strip. The M3 strip is from the array
    # subcell flattened in; paint a no-op M3 patch here first so
    # Magic's tile engine registers a metal3 tile bound to this
    # box before the label call.
    set bln_x [expr $c * $CELL_W_PC + 0.60 + $array_shift_x]
    box [expr $bln_x - 0.07]um [expr $array_top - 0.10]um \
        [expr $bln_x + 0.07]um [expr $array_top - 0.05]um
    paint metal3
    label BLN_$c
    port make
}
set wl_y_cursor 0.0
for {set r 0} {$r < $N_ROWS} {incr r} {
    set wl_y_lo [expr $wl_y_cursor + 0.95]
    set wl_y_hi [expr $wl_y_cursor + 1.07]
    # Paint a no-op M1 patch first (M1 already there from WL strap)
    # so the label binds to metal1 not space.
    box 0.0um ${wl_y_lo}um 0.10um ${wl_y_hi}um
    paint metal1
    label WL_$r
    port make
    set wl_y_cursor [expr $wl_y_cursor + $CELL_H_PC]
    if {[expr ($r + 1) % $TAP_EVERY_PC] == 0 && $r < ($N_ROWS - 1)} {
        set wl_y_cursor [expr $wl_y_cursor + $TAP_H_PC]
    }
}

# Source/read-line ground network. Each bitcell's source pad (li at
# column-local x [0.62, 0.79]) is otherwise unconnected: the mask
# programming wires only the drain, so the cells have no discharge
# return path and extract as per-cell floating source nodes.
#
# Three pieces, all locali (vertical met1 would short the WL straps;
# li has no interaction with the met1 WLs or the met3/met4 bitlines):
#   1. A vertical li strap per column at x [0.78, 0.95] -- the clear
#      lane right of the source pads (0.14 li spacing to the gate-cap
#      li ending at x 0.64) -- with a stub into every cell's source pad.
#   2. A horizontal li bus across each body-tap row, merging the 32
#      straps with the tap rows' li (pwell ties): sources = pwell.
#   3. Substrate taps under the VGND met1 rail (psubdiff + contact +
#      li + viali + met1 merging the rail): rail = pwell = sources,
#      so the whole ground network extracts as the single VGND net.
set strap_top [expr ($N_ROWS - 1) * $CELL_H_PC \
                   + (($N_ROWS - 1) / $TAP_EVERY_PC) * $TAP_H_PC + 0.45]
for {set c 0} {$c < $N_COLS} {incr c} {
    set sx [expr $c * $CELL_W_PC]
    box [expr $sx + 0.96]um 0.04um [expr $sx + 1.13]um ${strap_top}um
    paint locali
}
set src_y 0.0
for {set r 0} {$r < $N_ROWS} {incr r} {
    for {set c 0} {$c < $N_COLS} {incr c} {
        set sx [expr $c * $CELL_W_PC]
        box [expr $sx + 0.62]um [expr $src_y + 0.04]um \
            [expr $sx + 1.13]um [expr $src_y + 0.21]um
        paint locali
    }
    set src_y [expr $src_y + $CELL_H_PC]
    if {[expr ($r + 1) % $TAP_EVERY_PC] == 0 && $r < ($N_ROWS - 1)} {
        box 0.14um [expr $src_y + 0.15]um \
            [expr ($N_COLS - 1) * $CELL_W_PC + 1.13]um [expr $src_y + 0.32]um
        paint locali
        set src_y [expr $src_y + $TAP_H_PC]
    }
}
# VGND-rail substrate taps (rail met1 at y [94.60, 95.00]; nwell tops
# out at 94.12; via stacks at x 8.0-8.4 and 30.0-30.4 are avoided).
foreach c {1 5 9 13 21 25 29} {
    set xc [expr $c * $CELL_W_PC + 0.605]
    box [expr $xc - 0.205]um [expr $array_top + 4.96]um [expr $xc + 0.205]um [expr $array_top + 5.25]um
    paint psubdiff
    box [expr $xc - 0.085]um [expr $array_top + 5.02]um [expr $xc + 0.085]um [expr $array_top + 5.19]um
    paint psubdiffcont
    box [expr $xc - 0.165]um [expr $array_top + 4.96]um [expr $xc + 0.165]um [expr $array_top + 5.25]um
    paint locali
    box [expr $xc - 0.085]um [expr $array_top + 5.02]um [expr $xc + 0.085]um [expr $array_top + 5.19]um
    paint viali
    box [expr $xc - 0.135]um [expr $array_top + 4.92]um [expr $xc + 0.135]um [expr $array_top + 5.30]um
    paint metal1
}

select top cell

drc on
drc check
drc catchup
puts "MACRO=${MACRO_NAME}"
puts "DRC=[drc list count total]"
puts "WHY=[drc list why]"
puts "BBOX=[box values]"

# FIXED_BBOX property for LibreLane Magic.StreamOut PR boundary.
# Magic stores the property at 2x the input (magscale 1:2); LEF write
# reads at 200 CIF units/um. [box values] reports at the BBOX-print
# scale. Divide input by 2 so the stored value lands at the correct
# CIF scale that matches the actual layout bbox.
set bb [box values]
set llx [expr {[lindex $bb 0] / 2}]
set lly [expr {[lindex $bb 1] / 2}]
set urx [expr {[lindex $bb 2] / 2}]
set ury [expr {[lindex $bb 3] / 2}]
property FIXED_BBOX "$llx $lly $urx $ury"
puts "FIXED_BBOX=[property list FIXED_BBOX]"

save $MACRO_NAME
gds write ${MACRO_NAME}.gds

quit -noprompt
