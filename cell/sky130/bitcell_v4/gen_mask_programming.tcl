# Mask programming pass — paint via1 + bridge M1 per cell, connecting
# the cell drain to BL+ (M2, weight=+1), BL- (M3, weight=-1), or
# leaving it floating (weight=0).
#
# Cell geometry (after the L=0.17 + gate-top contact rework):
#   Cell bbox 0.75 x 1.05 um (placed lower-left at column box position).
#   Cell-internal D label at (-0.23, 0) -> row x = c*1.10 + 0.145
#   Drain M1 stub spans cell-internal x=[-0.335, -0.105] ->
#     row x = c*1.10 + 0.04 .. c*1.10 + 0.27
#   BL+ on M2 / BL- on M3 both at column-center x = c*1.10 + 0.55
#
# Per cell (r, c) with weight w:
#   w = +1: M1 bridge from drain right edge (0.27) to BL+ via1 region
#           (column-center +/- 0.145). Then via1 (0.17 x 0.17) under
#           local M2 patch (0.27 x 0.27).
#   w = -1: same M1 bridge + via1 + local M2 patch; PLUS via2 from M2
#           to M3 (0.20 x 0.20), local M3 patch (0.30 x 0.30 for met3.1).
#   w =  0: no via.
#
# Inputs from env:
#   ANKHDJET_ARRAY_N    rows    (default 64)
#   ANKHDJET_ARRAY_M    cols    (default 32)
#   ANKHDJET_WEIGHTS    "all_pos" | "all_neg" | "all_zero" | "checker"
#                    (default checker)
#
# Run via:
#   cd build
#   ANKHDJET_ARRAY_N=64 ANKHDJET_ARRAY_M=32 ANKHDJET_WEIGHTS=checker \
#     magic -dnull -noconsole -T sky130A < ../gen_mask_programming.tcl
#
# Requires v4_array_<N>x<M>_wlbl.mag in cwd.

set N_ROWS  [expr {[info exists ::env(ANKHDJET_ARRAY_N)] ? $::env(ANKHDJET_ARRAY_N) : 64}]
set N_COLS  [expr {[info exists ::env(ANKHDJET_ARRAY_M)] ? $::env(ANKHDJET_ARRAY_M) : 32}]
set PATTERN [expr {[info exists ::env(ANKHDJET_WEIGHTS)] ? $::env(ANKHDJET_WEIGHTS) : "checker"}]
set CELL_W  1.70
set CELL_H 1.30
set TAP_H  1.30
set TAP_EVERY [expr {[info exists ::env(ANKHDJET_TAP_EVERY)] ? $::env(ANKHDJET_TAP_EVERY) : 8}]

set src "v4_array_${N_ROWS}x${N_COLS}_wlbl"
set dst "v4_array_${N_ROWS}x${N_COLS}_${PATTERN}"

drc off

file delete -force "${dst}.mag" "${dst}.gds" "${dst}.ext"
file copy -force "${src}.mag" "${dst}.mag"
load $dst -quiet
select top cell
cellname rename "(UNNAMED)" $dst

# A weights file (ANKHDJET_WEIGHTS_FILE) overrides the builtin patterns:
# N_ROWS lines of N_COLS characters from {+,-,0}, row 0 first. The
# ANKHDJET_WEIGHTS name then only names the output cell.
array set WMAT {}
if {[info exists ::env(ANKHDJET_WEIGHTS_FILE)]} {
    set _f [open $::env(ANKHDJET_WEIGHTS_FILE) r]
    set _r 0
    while {[gets $_f _line] >= 0} {
        set _line [string trim $_line]
        if {$_line eq ""} { continue }
        for {set _c 0} {$_c < [string length $_line]} {incr _c} {
            switch -- [string index $_line $_c] {
                "+" { set WMAT($_r,$_c) 1 }
                "-" { set WMAT($_r,$_c) -1 }
                "0" { set WMAT($_r,$_c) 0 }
                default { error "weights file: bad char at row $_r col $_c" }
            }
        }
        incr _r
    }
    close $_f
    puts "WEIGHTS_FILE: $::env(ANKHDJET_WEIGHTS_FILE) ($_r rows)"
}

proc weight_at {r c pattern} {
    global WMAT
    if {[info exists WMAT($r,$c)]} { return $WMAT($r,$c) }
    if {$pattern eq "all_pos"}  { return 1 }
    if {$pattern eq "all_neg"}  { return -1 }
    if {$pattern eq "all_zero"} { return 0 }
    if {$pattern eq "checker"}  {
        if {[expr ($r + $c) % 2] == 0} { return 1 }
        return -1
    }
    return 0
}

set placed_pos 0
set placed_neg 0
set placed_zero 0
set y_cursor 0.0
# Mask programming: place via1 fully over the cell drain region (no
# bridge crossing source M1, which would short drain to source). At
# 1.20 column pitch with BL+ moved to the inter-cell gap (col-east
# x=c*1.20 + 0.825), the M2 patch east edge for w=-1 has enough room
# to clear BL+ by met2.3b 0.28 um, eliminating the BL+ -> BL- short
# that occurred at 1.10 pitch.
#
# Drain M1 fill plate: cell-local x=[-0.395, -0.025], y=[-0.220,
# +0.220]. Width 0.37 = via1 0.26 + 2 * via.4a 0.055; height 0.44
# fits via1 long enclosure (0.085 each side), and clears the cell M1
# horizontal connector at y=+0.36 by met1.2 0.14.
#
# BL+ M2 strip: c*1.20 + 0.825, west edge c*1.20 + 0.755 (cell-local
# +0.380), east edge c*1.20 + 0.895 (cell-local +0.520).
# BL- M3 strip: c*1.20 + 0.60 (column center), west c*1.20 + 0.45,
# east c*1.20 + 0.75 (cell-local +0.075..+0.375).
for {set r 0} {$r < $N_ROWS} {incr r} {
    set cy [expr $y_cursor + 0.34]
    for {set c 0} {$c < $N_COLS} {incr c} {
        set w [weight_at $r $c $PATTERN]
        if {$w == 0} { incr placed_zero; continue }

        set cell_ox  [expr $c * $CELL_W + 0.375]
        set blp_east [expr $c * $CELL_W + 1.700]
        set bln_east [expr $c * $CELL_W + 0.750]

        # Drain M1 fill plate
        box [expr $cell_ox - 0.395]um [expr $cy - 0.220]um \
            [expr $cell_ox - 0.025]um [expr $cy + 0.220]um
        paint metal1
        # via1 0.26 inside plate (no source crossing)
        box [expr $cell_ox - 0.340]um [expr $cy - 0.13]um \
            [expr $cell_ox - 0.080]um [expr $cy + 0.13]um
        paint via1

        if {$w == 1} {
            # w=+1: drain -> M1 -> via1 -> M2 -> via2 -> M3 pad ->
            # via3 -> M4 pad (merges the BL+ M4 strip [c+1.30, c+1.60]
            # by 0.30 overlap). The stack sits WEST of the strip center
            # so the M2 jog ends 0.235 before the next cell's M2
            # (met2.2) and the M3 pad sits 0.31 east of this column's
            # BL- M3 strip east edge (c+0.75) and 0.495 west of the
            # neighbor's BL- bump (met3.2 0.30). The old stack at
            # blp_x+0.25 reached the cell boundary exactly and abutted
            # the next cell's jog, silently shorting BLP_c to BLN_c+1.
            box [expr $cell_ox - 0.395]um [expr $cy - 0.220]um \
                [expr $c * $CELL_W + 1.445]um [expr $cy + 0.220]um
            paint metal2
            box [expr $c * $CELL_W + 1.125]um [expr $cy - 0.14]um \
                [expr $c * $CELL_W + 1.405]um [expr $cy + 0.14]um
            paint via2
            box [expr $c * $CELL_W + 1.06]um [expr $cy - 0.25]um \
                [expr $c * $CELL_W + 1.60]um [expr $cy + 0.25]um
            paint metal3
            box [expr $c * $CELL_W + 1.15]um [expr $cy - 0.16]um \
                [expr $c * $CELL_W + 1.47]um [expr $cy + 0.16]um
            paint via3
            box [expr $c * $CELL_W + 1.06]um [expr $cy - 0.25]um \
                [expr $c * $CELL_W + 1.60]um [expr $cy + 0.25]um
            paint metal4
            incr placed_pos
        } else {
            # w=-1: M2 carries the drain east to a via2 placed directly
            # under the BL- M3 strip ([c+0.45, c+0.75]); a local M3
            # bump widens the strip to meet the via2 enclosure. No
            # long M3 jog -- the old jog's west edge overlapped the
            # previous cell's BL+ M3 pad (the BLP/BLN short).
            box [expr $cell_ox - 0.395]um [expr $cy - 0.220]um \
                [expr $c * $CELL_W + 0.78]um [expr $cy + 0.220]um
            paint metal2
            box [expr $c * $CELL_W + 0.46]um [expr $cy - 0.14]um \
                [expr $c * $CELL_W + 0.74]um [expr $cy + 0.14]um
            paint via2
            box [expr $c * $CELL_W + 0.395]um [expr $cy - 0.205]um \
                [expr $c * $CELL_W + 0.805]um [expr $cy + 0.205]um
            paint metal3
            incr placed_neg
        }
    }
    set y_cursor [expr $y_cursor + $CELL_H]
    if {[expr ($r + 1) % $TAP_EVERY] == 0 && $r < ($N_ROWS - 1)} {
        set y_cursor [expr $y_cursor + $TAP_H]
    }
}

drc on
drc check
drc catchup
puts "MASK_PROGRAMMED=${dst}"
puts "PATTERN=${PATTERN}  +1=${placed_pos}  -1=${placed_neg}  0=${placed_zero}"
puts "DRC=[drc list count total]"

select top cell
puts "BBOX=[box values]"

save $dst

quit -noprompt
