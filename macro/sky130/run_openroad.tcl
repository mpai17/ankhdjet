# Array-size-agnostic OpenROAD floorplan + macro-place + STA flow on
# any cirom_array_NxM[_pdk][_biroma] hard macro abstraction.
#
# Reads file paths from environment variables set by run_openroad.sh:
#   ANKHDJET_TECH_LEF      tech LEF (sky130 vs gf180 path differs)
#   ANKHDJET_SC_LEF        standard cell LEF
#   ANKHDJET_SC_LIB        standard cell Liberty (gunzipped if needed)
#   ANKHDJET_MACRO_LEF     this run's cirom_array LEF (in build/)
#   ANKHDJET_MACRO_LIB     this run's cirom_array Liberty (in build/)
#   ANKHDJET_GATES_V       Yosys output gates.v (in build/)
#   ANKHDJET_TOP           top-level module name
#   ANKHDJET_OUT_DIR       where to write timing reports + .odb / .def
#   ANKHDJET_DIE_AREA      "x0 y0 x1 y1" — die bbox (default 130 130 + macro margin)
#   ANKHDJET_CORE_MARGIN   core inset from die (um)
#   ANKHDJET_SITE          row site name (unithd for sky130, GF018hv5v_green_sc9 for gf180)
#   ANKHDJET_LAYER_HOR     horizontal pin layer (met3 / Metal3)
#   ANKHDJET_LAYER_VER     vertical pin layer   (met2 / Metal2)
#   ANKHDJET_CLK_PERIOD_NS clock period in ns (5.0 for sky130, 7.0 for gf180)
#   ANKHDJET_MACRO_X       macro placement x (um)
#   ANKHDJET_MACRO_Y       macro placement y (um)
#   ANKHDJET_TRACK_LAYERS  space-sep list of "layer x_off x_pitch y_off y_pitch" tuples;
#                       expected as "li1 0.23 0.46 0.17 0.34 met1 0.17 ..." form.

set tech_lef    $::env(ANKHDJET_TECH_LEF)
set sc_lef      $::env(ANKHDJET_SC_LEF)
set sc_lib      $::env(ANKHDJET_SC_LIB)
set macro_lef   $::env(ANKHDJET_MACRO_LEF)
set macro_lib   $::env(ANKHDJET_MACRO_LIB)
set gates_v     $::env(ANKHDJET_GATES_V)
set top_module  $::env(ANKHDJET_TOP)
set out_dir     $::env(ANKHDJET_OUT_DIR)
set die_area    $::env(ANKHDJET_DIE_AREA)
set core_margin $::env(ANKHDJET_CORE_MARGIN)
set site_name   $::env(ANKHDJET_SITE)
set layer_hor   $::env(ANKHDJET_LAYER_HOR)
set layer_ver   $::env(ANKHDJET_LAYER_VER)
set clk_period  $::env(ANKHDJET_CLK_PERIOD_NS)
set macro_x     $::env(ANKHDJET_MACRO_X)
set macro_y     $::env(ANKHDJET_MACRO_Y)
set track_spec  $::env(ANKHDJET_TRACK_LAYERS)

file mkdir $out_dir

read_lef $tech_lef
read_lef $sc_lef
read_lef $macro_lef
read_liberty $sc_lib
read_liberty $macro_lib
read_verilog $gates_v
link_design $top_module

# Compute core_area = die shrunk by core_margin on each side.
lassign $die_area dx0 dy0 dx1 dy1
set cx0 [expr $dx0 + $core_margin]
set cy0 [expr $dy0 + $core_margin]
set cx1 [expr $dx1 - $core_margin]
set cy1 [expr $dy1 - $core_margin]

initialize_floorplan -die_area "$dx0 $dy0 $dx1 $dy1" \
                     -core_area "$cx0 $cy0 $cx1 $cy1" \
                     -site $site_name

# ANKHDJET_TRACK_LAYERS comes as 5-tuples per layer, space-separated.
foreach {layer x_off x_pitch y_off y_pitch} $track_spec {
    make_tracks $layer -x_offset $x_off -x_pitch $x_pitch \
                       -y_offset $y_off -y_pitch $y_pitch
}

place_macro -macro_name u_macro -location "$macro_x $macro_y" -orientation R0
place_pins  -hor_layers $layer_hor -ver_layers $layer_ver

global_placement -density 0.5 -pad_left 1 -pad_right 1
detailed_placement
report_design_area

create_clock -name CLK -period $clk_period [get_ports clk]
set_propagated_clock [get_clocks CLK]
report_checks -path_delay min_max -fields {nets cap slew} > $out_dir/timing_report.txt
report_check_types > $out_dir/check_types.txt
report_worst_slack
report_tns

write_db  $out_dir/design.odb
write_def $out_dir/design.def

puts "===== OPENROAD FLOW COMPLETE ====="
puts "Output dir: $out_dir"
puts "=================================="
exit
