# Word-line routing on M1 — horizontal strap per row connecting all
# bitcell gate-top M1 contacts in that row.
#
# Each bitcell now has a built-in M1 stub at its gate top, spanning
# x=cell_center +/- 0.135, y=cy + 0.36 .. cy + 0.67 (cell-local).
# For row r at y_cursor[r], cy = y_cursor[r] + 0.34, so the cell's
# gate M1 stub absolute Y is [y_cursor + 0.70, y_cursor + 1.01].
#
# Paint a horizontal M1 strap at y = y_cursor + 0.74 .. y_cursor + 0.96
# (0.22 um tall, well inside cell stub Y range), spanning the full row
# width plus a small overhang. Magic merges the strap with each cell's
# M1 stub forming one connected WL_<r> net per row.
#
# Inter-row M1 spacing: strap top at cy + 0.62 = y_cursor + 0.96;
# row r+1 cell ndiff M1 bottom at cy_{r+1} - 0.21 = y_cursor + 1.38.
# Gap 0.42 um >= 0.14 met1.2.
#
# Inputs from env (default 64x32 production-shape):
#   ANKHDJET_ARRAY_N  number of rows    (default 64)
#   ANKHDJET_ARRAY_M  number of cols    (default 32)
#
# Run via:
#   cd build
#   ANKHDJET_ARRAY_N=64 ANKHDJET_ARRAY_M=32 magic -dnull -noconsole -T sky130A < ../gen_wl_routing_m1.tcl
#
# Requires v4_array_<N>x<M>.mag in cwd.

set N_ROWS  [expr {[info exists ::env(ANKHDJET_ARRAY_N)] ? $::env(ANKHDJET_ARRAY_N) : 64}]
set N_COLS  [expr {[info exists ::env(ANKHDJET_ARRAY_M)] ? $::env(ANKHDJET_ARRAY_M) : 32}]
set CELL_W  1.70
set CELL_H 1.30
set TAP_H  1.30
set TAP_EVERY [expr {[info exists ::env(ANKHDJET_TAP_EVERY)] ? $::env(ANKHDJET_TAP_EVERY) : 8}]

set src "v4_array_${N_ROWS}x${N_COLS}"
set dst "${src}_wl"

drc off

file delete -force "${dst}.mag" "${dst}.gds" "${dst}.ext"
file copy -force "${src}.mag" "${dst}.mag"
load $dst -quiet
select top cell
cellname rename "(UNNAMED)" $dst

set y_cursor 0.0
for {set r 0} {$r < $N_ROWS} {incr r} {
    # WL_r M1 strap. Spans the full row width. y range chosen so the
    # long-M1 (>3 um) keeps met1.3b 0.28 um clearance from the cell's
    # S/D M1 (top at y_cursor+0.55) while still merging with the cell
    # gate-top M1 stub (y_cursor+0.70..1.01). Strap at y_cursor+0.85..
    # y_cursor+1.07 (0.22 um tall): bottom = 0.55+0.30 = 0.85 (>= 0.28
    # met1.3b ok), overlaps gate stub from 0.85 to 1.01 (0.16 um, plenty
    # for magic to merge into one connected WL net).
    set wl_x1 -0.10
    set wl_x2 [expr $N_COLS * $CELL_W + 0.10]
    set wl_y1 [expr $y_cursor + 0.85]
    set wl_y2 [expr $y_cursor + 1.07]
    box ${wl_x1}um ${wl_y1}um ${wl_x2}um ${wl_y2}um
    paint metal1

    set y_cursor [expr $y_cursor + $CELL_H]
    if {[expr ($r + 1) % $TAP_EVERY] == 0 && $r < ($N_ROWS - 1)} {
        set y_cursor [expr $y_cursor + $TAP_H]
    }
}

drc on
drc check
drc catchup
puts "WL_M1=${dst}"
puts "DRC=[drc list count total]"

select top cell
puts "BBOX=[box values]"

save $dst

quit -noprompt
