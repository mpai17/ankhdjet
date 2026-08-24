# Validate bitcell_v4 at sub-column scale: N rows + 1 body_tap, DRC clean.
#
# Pitch 1.25 um. The bitcell's gate poly extends y=±0.34 from cell center
# (channel y=±0.21 + 0.13 um licon1 stub on each side), so poly-to-poly
# spacing between adjacent cells = pitch - 0.68 must be >= 0.21 um
# (SKY130 rule poly.2). 1.25 - 0.68 = 0.21 (at limit; 0.005 um margin
# from grid quantization).
#
# diff/tap.3 (diff spacing 0.27 um) is also satisfied at this pitch
# (pitch - 0.42 = 0.47 >= 0.27).
#
# Inputs come from env (default 16 rows = SUBCOL_ROWS for the
# production sub-column):
#   ANKHDJET_SUBCOL_ROWS  number of bitcells in this sub-column (default 16)
#
# Run via:
#   cd build
#   magic -dnull -noconsole -T sky130A < ../gen_subcol_v4.tcl
#
# Requires bitcell_v4.mag and body_tap.mag in the build/ cwd:
#   magic -dnull -noconsole -T sky130A < ../gen_bitcell_v4.tcl
#   magic -dnull -noconsole -T sky130A < ../gen_body_tap.tcl

set N_ROWS [expr {[info exists ::env(ANKHDJET_SUBCOL_ROWS)] ? $::env(ANKHDJET_SUBCOL_ROWS) : 16}]
set name "v4_subcol_${N_ROWS}"

drc off

file delete -force "${name}.mag" "${name}.gds" "${name}.ext"

load $name -quiet
select top cell
cellname rename "(UNNAMED)" $name

# N bitcell_v4 instances at 1.25 um pitch
for {set i 0} {$i < $N_ROWS} {incr i} {
    set y [expr $i * 1.25]
    box position 0um ${y}um
    getcell bitcell_v4
}

# 1 body_tap above the topmost bitcell. The topmost cell is placed at
# y = (N-1)*1.25 with bbox height 1.05 um, so its top is at
# (N-1)*1.25 + 1.05. body_tap is 0.54 um tall (extents +/-0.27 from
# center); for 0.13 um clearance from the topmost cell's metal1 cap
# (top at y+0.67 cell-internal -> (N-1)*1.25 + 1.01 absolute) to the
# tap's psubdiff bottom, tap center sits at (N-1)*1.25 + 1.45.
# Total sub-column height ~(N-1)*1.25 + 1.72 um, must stay < 15 um
# (SKY130 LU.2 latch-up rule) -> N <= 11.
set tap_y [expr ($N_ROWS - 1) * 1.25 + 1.45]
box position 0um ${tap_y}um
getcell body_tap

drc on
drc check
drc catchup
puts "SUBCOL=${name}"
puts "DRC=[drc list count total]"

select top cell
puts "BBOX=[box values]"

save $name

quit -noprompt
