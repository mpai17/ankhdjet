# Std-cell PDN for Darga (the TT digital tile). pdngen owns ONLY the met1
# followpin rails; every met4 strap is hand-drawn by pdn_patch.tcl. Two
# reasons pdngen cannot own met4 here:
#   1. The array macro's full-width met4 VPWR strip and its 64 bitline
#      risers forbid ANY met4 strap from crossing x 102.0..157.25; the
#      array's own VPWR binding is a 0.5-wide riser-strap threading the
#      dummy-column gap at c153.98, which pdngen cannot express.
#   2. pdngen silently RELOCATES straps it cannot place as specified to the
#      leftmost free met4 track, which can land a strap on the array's dummy
#      bitline risers (a crowbar path through the ROM cells). pdn_patch's
#      asserts tripwire exactly this.
source $::env(SCRIPTS_DIR)/openroad/common/set_global_connections.tcl
set_global_connections

set_voltage_domain -name CORE -power $::env(VDD_NET) -ground $::env(GND_NET)

define_pdn_grid -name stdcell_grid -starts_with POWER -voltage_domain CORE

add_pdn_stripe -grid stdcell_grid -layer met1 -width 0.48 -followpins

# Hook the strap drawing + macro power binding in AFTER pdngen runs: pdn.tcl
# sources this file (read_pdn_cfg) and then invokes `pdngen`, so wrap the
# command -- the real pdngen executes, then pdn_patch.tcl draws the hand met4
# geometry on the finished grid (it places the met1-rail-to-strap via stacks
# that add_pdn_connect would only have made for pdngen-owned stripes).
# Sourced at global level; idempotent.
if { [info commands ::_ankhdjet_real_pdngen] eq "" } {
    rename ::pdngen ::_ankhdjet_real_pdngen
    proc ::pdngen {args} {
        set r [uplevel 1 ::_ankhdjet_real_pdngen {*}$args]
        uplevel #0 [list source [file join $::env(DESIGN_DIR) pdn_patch.tcl]]
        return $r
    }
}
