# Generate bitcell_v4 — 1T NOR-array bitcell with hand-painted gate-top
# contact stack for row-level WL routing.
#
# Sizing:
#   W = 0.42 um (SKY130 nfet_01v8 minimum)
#   L = 0.17 um (was 0.15 minimum; widened so the gate poly is wide
#               enough for a 0.17 x 0.17 licon1 contact. ~13% lower
#               drive than L=0.15 -- BL discharge sweep at SS@N=64
#               must still meet the 1.5 ns budget.)
#
# Gate-top contact stack (hand-painted because the SKY130 PCell `gtc`
# flag is for the GUARD-RING gate contact, not the cell-gate contact):
#   - poly stub already extends y=0.21..0.34 above cell center
#   - paint a wider "T-cap" of poly at the stub top to host the contact
#   - paint polycont on the cap (Magic auto-generates licon1+LI+poly
#     overlap meeting licon.5/licon.8 rules)
#   - paint metal1 stub above for the WL strap to land on at array level
#
# Cell array pitch: validated to 1.0 x 0.89 um in gen_array.tcl.
#
# Run via:
#   cd build && magic -dnull -noconsole -T sky130A < ../gen_bitcell_v4.tcl

drc off
load bitcell_v4 -quiet
select top cell
cellname rename "(UNNAMED)" bitcell_v4

box position 0 0
box size 0 0
::sky130::sky130_fd_pr__nfet_01v8_draw [dict merge \
    [::sky130::sky130_fd_pr__nfet_01v8_defaults] \
    {w 0.42 l 0.17 nf 1 m 1 \
     glc 0 grc 0 gtc 0 gbc 0 \
     topc 0 botc 0 \
     diffcov 100 polycov 100 tbcov 100 rlcov 100 \
     viasrc 100 viadrn 100 viagate 100 \
     guard 0 doverlap 0 poverlap 0}]

# Hand-paint the gate-top contact stack. SKY130 contact stack rules:
#   licon.1   licon1 footprint = 0.17 x 0.17 um
#   licon.8   poly overhang of licon1 >= 0.05 um on all sides
#   licon.14  licon1 spacing to diff >= 0.19 um (gate-licon to ndiff)
#   li.5      LI overhang of licon1 >= 0.08 um in one direction
#   li.6      LI minimum area >= 0.0561 um^2
#   met1.6    M1 minimum area >= 0.083 um^2
#
# Geometry (cell-internal coords; cell center at origin):
#   The gate poly stub extends y=[0.21, 0.34], x=[-0.085, 0.085]. The
#   contact stack must sit ABOVE the stub, with the licon1 spaced
#   >=0.19 from the ndiff top at y=0.21 -- so licon1 bottom >= 0.40.
#
#   Poly cap : x=[-0.135, 0.135] (0.27 wide), y=[0.34, 0.59]
#              (0.25 tall) -- includes 0.05 overhang past licon1
#              footprint and bridges to the existing 0.17-wide stub.
#   licon1   : x=[-0.085, 0.085], y=[0.42, 0.59]  (0.17 x 0.17)
#              -> bottom y=0.42 = ndiff top 0.21 + 0.21 spacing
#                 (>= 0.19 um licon.14) + small margin.
#   LI       : x=[-0.085, 0.085], y=[0.42, 0.69]  (0.17 x 0.27)
#              -> 0.08 LI overhang above licon1 (li.5) and meets
#                 li.6 area 0.17 * 0.27 = 0.0459 < 0.0561 -- need
#                 to go wider. Use x=[-0.135, 0.135] -> 0.27 wide,
#                 0.17 tall = 0.0459 still under. Use both wider
#                 AND taller: 0.27 x 0.27 = 0.0729 >= 0.0561 ok.
#   M1       : 0.29 x 0.29 = 0.0841 >= 0.083 (met1.6) at the LI top.
#
# Total contact stack height above stub: y=0.34 to y=1.06 = 0.72 um
# of additional cell extent. Row pitch must grow from 0.89 to 1.44 um
# to satisfy poly.2 between rows (0.21 um). gen_array.tcl needs to
# bump CELL_H accordingly.

# Poly cap above the gate stub. Sized for licon.8 0.05 overhang on all
# sides + licon.8a 0.08 overhang in one direction.
# Cap: x=[-0.135, 0.135] (0.27 wide), y=[0.34, 0.67] (0.33 tall).
# Licon at x=[-0.085, 0.085], y=[0.42, 0.59] -> overhang:
#   left/right: 0.05 (>= 0.05 licon.8 ok)
#   bottom: 0.08 (>= 0.08 licon.8a ok)
#   top: 0.08 (>= 0.08 licon.8a ok)
box -0.135um 0.34um 0.135um 0.67um
paint poly

# licon1 contact (poly to LI), 0.17 x 0.17 footprint.
box -0.085um 0.42um 0.085um 0.59um
paint polycont

# LI patch generously sized to envelope the polycont's auto-LI plus
# the explicit overhang. Width spans the full poly cap; height extends
# far above the polycont.
# LI: x=[-0.165, 0.165] (0.33 wide, 0.04 past poly cap which is fine
# since LI doesn't have the same poly.4 constraint), y=[0.40, 0.71]
# (0.31 tall). Area 0.33*0.31 = 0.1023 um^2.
box -0.165um 0.40um 0.165um 0.71um
paint locali

# viali (LI to M1) inside the LI patch.
box -0.085um 0.42um 0.085um 0.59um
paint viali

# M1 stub covering the viali with met1.4 0.03 overhang on all sides
# AND met1.6 area >= 0.083 um^2. M1: 0.27 x 0.31 = 0.0837 ok.
box -0.135um 0.36um 0.135um 0.67um
paint metal1

# Source M1 widening blocked: a 0.37x0.43 source plate fires met1.3b
# within the cell (the existing gate-top M1 connector at cell-local
# x=[-0.135, +0.135] sits 0.020 from the widened source M1 west edge).
# Resolution requires moving the gate-top contact stack OR repositioning
# the source pin -- a bitcell layout redesign rather than a paint
# addition. Defer.

# Label the gate as G port. Match the strongarm pattern: box +
# unqualified label + port make.
box -0.05um 0.50um 0.05um 0.55um
label G
port make

drc on
drc check
puts "DRC=[drc list count total]"

save bitcell_v4

puts "===== bitcell_v4 generation summary ====="
puts "1 x sky130_fd_pr__nfet_01v8, W=0.42, L=0.17, hand-painted gate-top contact"
puts "Gate exposed as port G on metal1 for array-level WL routing"
puts "==========================================="
