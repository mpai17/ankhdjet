# Precharge row — the clocked pull-up pair per column (see
# docs/precharge_design.md): row A (upright) pulls BL- and row B
# (vertically flipped, placed so the two gate caps merge into one
# poly/met1 column) pulls BL+. A met2 backbone ties every column's
# merged gate cap into the row-wide PRE_N net (met1 would short the
# macro-level source straps that cross it). One nwell merges all
# devices.
#
# Cell frame: precharge bbox y [-0.81, +1.03] around its center; cells
# are placed by lower-left, so within this row a cell's center sits
# +0.545/+0.81 from its placement point.
#
# Inputs from env (default 4 cells per row):
#   ANKHDJET_PRECHARGE_N  number of columns (default 4)
#
# Run via:
#   cd build
#   magic -dnull -noconsole -T sky130A < ../gen_precharge_row.tcl
#
# Requires precharge.mag in cwd (gen_precharge.tcl produces it).

set N [expr {[info exists ::env(ANKHDJET_PRECHARGE_N)] ? $::env(ANKHDJET_PRECHARGE_N) : 4}]
set CELL_W 1.70
set DY 1.83   ;# row B offset: cut layers (licon/mcon) at legal spacing across the seam

set name "precharge_row${N}"

drc off
file delete -force "${name}.mag" "${name}.gds" "${name}.ext"
load $name -quiet
select top cell
cellname rename "(UNNAMED)" $name

for {set i 0} {$i < $N} {incr i} {
    set x [expr $i * $CELL_W]
    box position ${x}um 0um
    getcell precharge
    box position ${x}um ${DY}um
    getcell precharge v
}

# Bridge the cap seam per column: poly and li sit 0.03-0.05 apart
# across the A/B boundary (cuts need spacing, but the conductors must
# merge into one PRE_N column), then via1 the merged met1 onto the
# met2 backbone.
for {set i 0} {$i < $N} {incr i} {
    set cx [expr $i * $CELL_W + 0.545]
    box [expr $cx - 0.135]um 1.80um [expr $cx + 0.135]um 1.87um
    paint poly
    box [expr $cx - 0.165]um 1.79um [expr $cx + 0.165]um 1.88um
    paint locali
    box [expr $cx - 0.135]um 1.81um [expr $cx + 0.135]um 1.89um
    paint metal1
    box [expr $cx - 0.13]um 1.74um [expr $cx + 0.13]um 2.00um
    paint via1
}
set bus_x2 [expr ($N - 1) * $CELL_W + 1.09 + 0.05]
box -0.10um 1.66um ${bus_x2}um 2.04um
paint metal2

# One continuous nwell over both rows (nwell.2a merge).
box -0.10um -0.05um ${bus_x2}um [expr $DY + 1.10 + 0.81]um
paint nwell

drc on
drc check
drc catchup
puts "PRECHARGE_ROW=${name}"
puts "DRC=[drc list count total]"
puts "WHY=[drc list why]"

select top cell
puts "BBOX=[box values]"

save $name
quit -noprompt
