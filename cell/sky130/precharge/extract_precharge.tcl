# Extract precharge cells to SPICE for LVS reference. Mirrors the
# bitcell extraction settings.
#
# Run via:
#   cd cell/sky130/precharge/build
#   magic -dnull -noconsole -T sky130A < ../extract_precharge.tcl

drc off

foreach cell {precharge precharge_row4} {
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
