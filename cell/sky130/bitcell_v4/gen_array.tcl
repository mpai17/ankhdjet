# Parameterized N x M cell-array placement for the cirom matmul tile.
# Produces v4_array_${N}x${M}.mag with bitcell_v4 instances at 1.70 x
# 1.30 um pitch and a body_tap row every 8 rows (SKY130 LU.2 latch-up
# rule: max diff-to-tap distance 15 um).
#
# Pitch for the bitcell with built-in gate-top contact:
#   X = 1.70 um (CELL_W, column pitch): carries the BL- met3 strip,
#       the BL+ met4 strip, the li source strap, and the per-column
#       mask-jog lanes with DRC margin.
#   Y = 1.30 um (CELL_H, row pitch): closes poly.2 and li rules
#       between the cell's top contact stack and the next row's
#       bottom poly stub. Tap row gets the same pitch (TAP_H).
#
# Inputs come from env (default 256 x 256 to match the production shape):
#   ANKHDJET_ARRAY_N  number of rows    (default 256)
#   ANKHDJET_ARRAY_M  number of cols    (default 256)
#   ANKHDJET_TAP_EVERY  rows per tap    (default 8)
#
# Run via:
#   cd build
#   ANKHDJET_ARRAY_N=64 ANKHDJET_ARRAY_M=32 magic -dnull -noconsole -T sky130A < ../gen_array.tcl
#
# Requires bitcell_v4.mag and body_tap.mag in the cwd.

drc off

set N_ROWS    [expr {[info exists ::env(ANKHDJET_ARRAY_N)]      ? $::env(ANKHDJET_ARRAY_N) : 256}]
set N_COLS    [expr {[info exists ::env(ANKHDJET_ARRAY_M)]      ? $::env(ANKHDJET_ARRAY_M) : 256}]
set TAP_EVERY [expr {[info exists ::env(ANKHDJET_TAP_EVERY)]    ? $::env(ANKHDJET_TAP_EVERY) : 8}]

set CELL_W 1.70
set CELL_H 1.30
set TAP_H  1.30

set name "v4_array_${N_ROWS}x${N_COLS}"

# Remove any stale .mag / .gds for this target name so the build is
# reproducible — `load $name` would otherwise pick up the prior run's
# placement and double up on getcell calls.
file delete -force "${name}.mag" "${name}.gds" "${name}.ext"

load $name -quiet
select top cell
cellname rename "(UNNAMED)" $name

set y_cursor 0.0
set placed_cells 0
set placed_taps  0

for {set r 0} {$r < $N_ROWS} {incr r} {
    for {set c 0} {$c < $N_COLS} {incr c} {
        set x [expr $c * $CELL_W]
        box position ${x}um ${y_cursor}um
        getcell bitcell_v4
        incr placed_cells
    }
    set y_cursor [expr $y_cursor + $CELL_H]

    if {[expr ($r + 1) % $TAP_EVERY] == 0 && $r < ($N_ROWS - 1)} {
        for {set c 0} {$c < $N_COLS} {incr c [expr $TAP_EVERY]} {
            set x [expr $c * $CELL_W]
            box position ${x}um ${y_cursor}um
            getcell body_tap
            incr placed_taps
        }
        set y_cursor [expr $y_cursor + $TAP_H]
    }
}

drc on
drc check
drc catchup
puts "ARRAY=${name}"
puts "DRC=[drc list count total]"
select top cell
puts "BBOX=[box values]"
puts "Placed: ${placed_cells} bitcell_v4 + ${placed_taps} body_tap"

save $name

quit -noprompt
