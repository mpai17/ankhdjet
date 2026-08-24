# Std-cell-only PDN for the Azara TT analog tile. The macros are bound by
# pdn_patch.tcl (hand-drawn met4 geometry sourced right after pdngen -- see
# ENV_PATCHES.md): pdngen cannot bind them safely because their met3 is dense
# pin strips (no room for via-stack landing pads) and the array's full-width
# met4 VPWR strip + 64 bitline risers forbid ANY met4 strap from crossing it.
#
# So: met1 followpin rails + four hand-placed vertical met4 strap pairs in
# macro-free lanes, connected met1<->met4 directly (0 channels). Lane choice
# (vs macro_tile.cfg placement: array x 14..68.6, band_p x 16.., band_n x 78..,
# template met4 pin fences at the top (digital, pitch 2.75) / bottom (ua)):
# Strap centers (die-abs; empirically pdngen -offset positions the strap
# CENTERLINE at core_left(5.52) + offset). The array sits FN at x=4..58.6 (its
# full-width met4 VPWR strip + 64 bitline risers forbid any strap crossing
# x 3.8..59), so all pdngen straps live east of it; the array's own VPWR comes
# from a patch-drawn 0.6 riser-strap at c5.2 threading the dummy-column gap
# (left of the core edge, which pdngen cannot reach).
#   VPWR c70.85 / VGND c76.35: right of the array; VGND threads the inter-band
#                              gap between the ua[4] bottom stub and the 77.7
#                              top stub (0.9 wide -- a 1.6 strap does not fit)
#   VPWR c139.85/ VGND c145.35: centered in the ui_in[0]/rst_n and clk/ena
#                              top-pin gaps (fence pitch 2.75, stub +-0.15);
#                              0.9 wide so the clk pin keeps a legal met4
#                              descent between its stub and the strap
#   VPWR c148.35/ VGND c150.35: right margin, both inside the ena(146.7)..
#                              ua[0](152.26) stub window (0.4 between them)
source $::env(SCRIPTS_DIR)/openroad/common/set_global_connections.tcl
set_global_connections

set_voltage_domain -name CORE -power $::env(VDD_NET) -ground $::env(GND_NET)

define_pdn_grid -name stdcell_grid -starts_with POWER -voltage_domain CORE

add_pdn_stripe -grid stdcell_grid -layer met1 -width 0.48 -followpins

# NO pdngen met4 stripes: with this floorplan's obstructions, pdngen silently
# RELOCATES straps it cannot place as specified to the leftmost free met4
# track (phantom stripes at c7.82/c8.74/c10.58 across tile39-41, one landing
# on the array's dummy bitline risers = a crowbar path; caught by pdn_patch's
# asserts). All met4 straps are drawn verbatim by pdn_patch.tcl, which also
# places the met1-rail-to-strap via stacks that add_pdn_connect would have
# only made for pdngen-owned stripes.

# Hook the macro power binding in AFTER pdngen runs: pdn.tcl sources this file
# (read_pdn_cfg) and then invokes `pdngen`, so wrap the command -- the real
# pdngen executes, then pdn_patch.tcl draws the hand met4 binding geometry on
# the finished grid (it discovers the generated straps and reuses pdngen's
# vias, so it MUST run after). Sourced at global level; idempotent.
if { [info commands ::_ankhdjet_real_pdngen] eq "" } {
    rename ::pdngen ::_ankhdjet_real_pdngen
    proc ::pdngen {args} {
        set r [uplevel 1 ::_ankhdjet_real_pdngen {*}$args]
        uplevel #0 [list source [file join $::env(DESIGN_DIR) pdn_patch.tcl]]
        return $r
    }
}
