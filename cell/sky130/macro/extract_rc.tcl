drc off
crashbackups stop
load macro_array_pc_64x32_checker
select top cell
flatten mfc_rc_flat
load mfc_rc_flat
extract do resistance
extract all
extresist tolerance 1
extresist all
ext2spice scale off
ext2spice extresist on
ext2spice cthresh 0
ext2spice rthresh 1
ext2spice subcircuit on
ext2spice -o macro_rc.spice
puts "RC_EXTRACT_DONE"
quit -noprompt
