# OpenROAD CTS + STA on a pre-placed ORFS design.
#
# Skips ORFS's post-CTS detailed_placement (which currently SIGILLs on
# AMD Zen 3 hosts in 26Q2-565). Reads the platform's liberty + tech LEF
# + the placed .odb + the floorplan SDC, runs CTS, repairs setup timing,
# then dumps the timing reports we need for the throughput-calibration
# anchor.
#
# Inputs (env vars set by run_openroad_anchor.py):
#   ANKHDJET_PLACED_ODB     path to *_3_5_place_dp.odb
#   ANKHDJET_SDC            path to *_2_floorplan.sdc
#   ANKHDJET_LIBS           space-separated list of liberty files (one or more)
#   ANKHDJET_OUT_DIR        where to write report files
#   ANKHDJET_PS_TO_NS       multiplier converting STA's reported time units to ns
#                        (1.0 for libs in ns, 0.001 for libs in ps)
#   ANKHDJET_CTS_BUF_LIST   optional space-sep buffer cell names; empty -> auto

set odb           $::env(ANKHDJET_PLACED_ODB)
set sdc           $::env(ANKHDJET_SDC)
set libs          $::env(ANKHDJET_LIBS)
set out           $::env(ANKHDJET_OUT_DIR)
set ps_to_ns      [expr double($::env(ANKHDJET_PS_TO_NS))]
set cts_buf_list  ""
if { [info exists ::env(ANKHDJET_CTS_BUF_LIST)] } {
    set cts_buf_list $::env(ANKHDJET_CTS_BUF_LIST)
}

foreach lib $libs {
    read_liberty $lib
}

read_db  $odb
read_sdc $sdc

# Conservative wire RC so estimate_parasitics produces non-zero capacitance.
# Real per-node values aren't critical for the alpha calibration since alpha
# is dominated by H-tree skew, not signal wires.
set_wire_rc -clock -resistance 1.7e-3 -capacitance 1.3e-4
set_wire_rc -signal -resistance 1.7e-3 -capacitance 1.3e-4

if { $cts_buf_list ne "" } {
    clock_tree_synthesis -buf_list $cts_buf_list -sink_clustering_enable
} else {
    clock_tree_synthesis -sink_clustering_enable
}

estimate_parasitics -placement

# repair_timing inserts buffers + resizes cells to fix setup violations.
# Without it, worst_slack reflects an unbuffered design and dramatically
# under-reports achievable fmax.
catch { repair_timing -setup -skip_pin_swap }
estimate_parasitics -placement

set ws_setup [sta::worst_slack -max]
set ws_hold  [sta::worst_slack -min]

# Pull SDC clock period from the parsed clocks list, in liberty time units.
set clk_period_user 0.0
foreach clk [sta::all_clocks] {
    set p [sta::get_property $clk period]
    if { $p > $clk_period_user } { set clk_period_user $p }
}

set clk_period_ns       [expr $clk_period_user * $ps_to_ns]
set ws_setup_ns         [expr $ws_setup * $ps_to_ns]
set ws_hold_ns          [expr $ws_hold * $ps_to_ns]
set achieved_period_ns  [expr $clk_period_ns - $ws_setup_ns]
set achieved_fmax_mhz   [expr 1000.0 / $achieved_period_ns]

set f [open "$out/timing.txt" w]
puts $f "target_period_ns     $clk_period_ns"
puts $f "worst_slack_setup_ns $ws_setup_ns"
puts $f "worst_slack_hold_ns  $ws_hold_ns"
puts $f "achieved_period_ns   $achieved_period_ns"
puts $f "achieved_fmax_mhz    $achieved_fmax_mhz"
close $f

report_clock_skew > $out/clock_skew_full.txt
report_checks -path_delay max -fields {capacitance slew} -format full_clock_expanded > $out/timing_report.txt

# Block area in mm^2 from the die bbox.
set die [ord::get_db_block]
set bbox [$die getDieArea]
set llx [$bbox xMin]; set lly [$bbox yMin]
set urx [$bbox xMax]; set ury [$bbox yMax]
# DB units are 1 nm in all ORFS platforms.
set width_mm  [expr ($urx - $llx) * 1e-6]
set height_mm [expr ($ury - $lly) * 1e-6]
set area_mm2  [expr $width_mm * $height_mm]
set f [open "$out/area.txt" w]
puts $f "die_width_mm  $width_mm"
puts $f "die_height_mm $height_mm"
puts $f "die_area_mm2  $area_mm2"
close $f

puts "DONE"
exit 0
