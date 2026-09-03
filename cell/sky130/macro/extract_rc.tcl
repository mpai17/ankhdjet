# RC extraction of a built macro (resistance + capacitance) for the
# chip-level mixed-signal cosim. ANKHDJET_MACRO selects the macro (default
# the checker program); writes <macro>_rc.spice into the build dir.
drc off
crashbackups stop
set MACRO [expr {[info exists ::env(ANKHDJET_MACRO)] ? $::env(ANKHDJET_MACRO) : "macro_array_pc_64x32_checker"}]
load $MACRO
select top cell
flatten ${MACRO}_rc
load ${MACRO}_rc
extract do resistance
extract all
extresist tolerance 1
extresist all
ext2spice scale off
ext2spice extresist on
ext2spice cthresh 0
ext2spice rthresh 1
ext2spice subcircuit on
ext2spice subcircuit top on
ext2spice -o ${MACRO}_rc.spice
puts "RC_EXTRACT_DONE"
quit -noprompt
