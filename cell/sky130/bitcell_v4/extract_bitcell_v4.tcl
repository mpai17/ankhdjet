# Extract bitcell_v4 to SPICE for LVS reference. Mirrors the strongarm
# extraction settings (lvs mode, infinite cap/res thresholds, subckt on).
#
# Run via:
#   cd cell/sky130/bitcell_v4/build
#   magic -dnull -noconsole -T sky130A < ../extract_bitcell_v4.tcl

drc off

# Primitives + sub-column + the production-shape array. Discover any
# v4_subcol_<N> and v4_array_<N>x<M> .mag files in cwd so the
# extraction is array-size agnostic; the engineer adds shapes by
# building them with gen_subcol_v4.tcl / gen_array.tcl, and this
# script extracts whatever it finds.
set targets {bitcell_v4 bitcell_v4_biroma body_tap}
foreach mag [lsort [glob -nocomplain v4_subcol_*.mag v4_array_*x*.mag]] {
    lappend targets [file rootname $mag]
}

foreach cell $targets {
    if {![file exists ${cell}.mag]} { continue }
    load $cell -quiet
    select top cell
    extract no all
    extract do local
    extract no capacitance
    extract no resistance
    extract all
    ext2spice lvs
    ext2spice cthresh infinite
    ext2spice rthresh infinite
    ext2spice subcircuit on
    ext2spice -o ${cell}_extracted.spice
    puts "Extracted ${cell}_extracted.spice"
}

quit -noprompt
