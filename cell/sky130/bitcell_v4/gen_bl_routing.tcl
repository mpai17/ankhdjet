# Bit-line routing — BL+ on M4 (full-height vertical strip), BL- on M3.
#
# BL+ was previously on M2 at 1.20 um column pitch, producing 32
# full-height met2 strips per macro that caused ~1700 chip-level
# met2.3b spacing violations (chip-routed met2 within 0.56 um of
# macro-internal full-height met2). Moving BL+ to M4 eliminates the
# full-height met2 footprint -- only small per-cell M2 drain patches
# remain (see gen_mask_programming.tcl for the M1->via1->M2->via2->
# M3->via3->M4 via stack used when w=+1).
#
# Per column c at column pitch 1.20 um:
#   BL+ (M4) at x = c*CELL_W + 0.825   (inter-cell gap; 0.30 um wide)
#   BL- (M3) at x = c*CELL_W + 0.60    (column center; 0.30 um wide)
#
# Spacing checks:
#   met4.5b (>3 um long edge): 0.80 um required.
#     Adjacent BL+ M4: pitch 1.20 - width 0.30 = 0.90 um gap. PASS.
#   met3.2 (BL- M3 to local M3 patch for w=+1 via stack):
#     BL- east at cell-local +0.15; local M3 patch west at cell-local
#     +0.30 (BL+ via stack centered at +0.45 with width 0.30 -> west
#     edge +0.30). Gap 0.15 um. PASS (met3.2 0.06).
#
# Inputs from env:
#   ANKHDJET_ARRAY_N  rows    (default 64)
#   ANKHDJET_ARRAY_M  cols    (default 32)
#
# Run via:
#   cd build
#   ANKHDJET_ARRAY_N=64 ANKHDJET_ARRAY_M=32 magic -dnull -noconsole -T sky130A < ../gen_bl_routing.tcl
#
# Requires v4_array_<N>x<M>_wl.mag in cwd (gen_wl_routing_m1.tcl produces it).

set N_ROWS  [expr {[info exists ::env(ANKHDJET_ARRAY_N)] ? $::env(ANKHDJET_ARRAY_N) : 64}]
set N_COLS  [expr {[info exists ::env(ANKHDJET_ARRAY_M)] ? $::env(ANKHDJET_ARRAY_M) : 32}]
set CELL_W  1.70
set CELL_H 1.30
set TAP_H  1.30
set TAP_EVERY [expr {[info exists ::env(ANKHDJET_TAP_EVERY)] ? $::env(ANKHDJET_TAP_EVERY) : 8}]

set src "v4_array_${N_ROWS}x${N_COLS}_wl"
set dst "v4_array_${N_ROWS}x${N_COLS}_wlbl"

drc off

file delete -force "${dst}.mag" "${dst}.gds" "${dst}.ext"
file copy -force "${src}.mag" "${dst}.mag"
load $dst -quiet
select top cell
cellname rename "(UNNAMED)" $dst

# Compute total Y span for full-height strips
set y_total 0.0
for {set r 0} {$r < $N_ROWS} {incr r} {
    set y_total [expr $y_total + $CELL_H]
    if {[expr ($r + 1) % $TAP_EVERY] == 0 && $r < ($N_ROWS - 1)} {
        set y_total [expr $y_total + $TAP_H]
    }
}

for {set c 0} {$c < $N_COLS} {incr c} {
    # BL+ on M4 (0.30 wide). At pitch 1.70, BL+ M4 is centered at
    # c*CELL_W + 1.45 (midpoint of inter-BL- gap c*CELL_W+0.75 ..
    # c*CELL_W+2.15). The M3 patch in the BL+ via stack (0.50 wide,
    # met3.6 0.24 area satisfied at 0.25) lands at the same x with
    # 0.45 um clearance from cell c BL- east (0.75) and 0.45 um
    # from cell c+1 BL- west (2.15) -- both > met3.3d 0.40 for
    # the long-edge BL- M3 strips.
    set blp_x [expr $c * $CELL_W + 1.45]
    box [expr $blp_x - 0.15]um -0.05um [expr $blp_x + 0.15]um [expr $y_total + 0.05]um
    paint metal4
    # BL- on M3 at column center, 0.30 um wide for met3.1
    set bln_x [expr $c * $CELL_W + 0.60]
    box [expr $bln_x - 0.15]um -0.05um [expr $bln_x + 0.15]um [expr $y_total + 0.05]um
    paint metal3
}

drc on
drc check
drc catchup
puts "BL_M2M3=${dst}"
puts "DRC=[drc list count total]"

select top cell
puts "BBOX=[box values]"

save $dst

quit -noprompt
