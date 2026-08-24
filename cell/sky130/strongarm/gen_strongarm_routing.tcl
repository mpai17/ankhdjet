# StrongARM SA routing for the vertical (3.40 um pitch-doubled) stack.
# All device S/D/gate terminals are already on metal1 (the PCell brings
# them up). Routing connects those M1 patches per net; M2 vertical rails
# carry the nets that span many devices (outp/outm/vdd/strobe), passing
# over M1 terminals and dropping a via1 only where a terminal joins.
#
# Net tracks (x in um):
#   outp      M2 @ 0.30   (left)
#   intm/vdd-left M2 @ 0.645 (left; intm y34..43, vdd-left y60..72)
#   blp/bln   M2 pads @ 1.29 (center, at the input gates)
#   vdd-right M2 @ 1.935 (right)
#   outm      M2 @ 2.40  (right)
#   strobe    M2 @ 2.80  (right edge; clears the intp/intm crossing)
#
# Placed terminal coordinates (um) come from the flipped stack in
# gen_strongarm_top.tcl. See that file for the per-device net mapping.

load strongarm
drc off

proc m1v {x y0 y1} { box [expr $x-0.07]um ${y0}um [expr $x+0.07]um ${y1}um ; paint metal1 }
proc m1h {y x0 x1} { box ${x0}um [expr $y-0.07]um ${x1}um [expr $y+0.07]um ; paint metal1 }
proc m2v {x y0 y1} { box [expr $x-0.07]um ${y0}um [expr $x+0.07]um ${y1}um ; paint metal2 }
proc m2h {y x0 x1} { box ${x0}um [expr $y-0.07]um ${x1}um [expr $y+0.07]um ; paint metal2 }

# via1 stack: 0.26x0.26 region (via.1a min), 0.38x0.38 M1/M2 pads
# (0.06 enclosure > via.4a 0.055).
proc via1 {x y} {
    box [expr $x-0.19]um [expr $y-0.19]um [expr $x+0.19]um [expr $y+0.19]um
    paint metal1
    box [expr $x-0.13]um [expr $y-0.13]um [expr $x+0.13]um [expr $y+0.13]um
    paint via1
    box [expr $x-0.19]um [expr $y-0.19]um [expr $x+0.19]um [expr $y+0.19]um
    paint metal2
}

# ---------------------------------------------------------------------
# VGND -- bottom rail (M1) + tail source down + substrate taps
box -0.3um 0.20um 2.9um 0.70um
paint metal1
box -0.3um 0.20um 2.9um 0.70um
label VGND
port make
m1v 1.935 0.50 12.14   ;# tail/S (y5.12,12.14) down to rail

# p-substrate taps (NMOS bulk + latch-up), labelled VGND, at the far
# right (x>=2.86, >=0.28 um clear of the widest device edge at 2.58).
# psubdiff 0.50 wide, psc 0.24 (licon.7 enclosure 0.13), li1 0.42
# (li.5 overlap 0.09). y=8/24/40 keep every NMOS diffusion within 15 um.
foreach ty {8.0 24.0 40.0} {
    box 2.86um [expr $ty-0.5]um 3.36um [expr $ty+0.5]um
    paint psubdiff
    box 2.99um [expr $ty-0.4]um 3.23um [expr $ty+0.4]um
    paint psc
    box 2.90um [expr $ty-0.45]um 3.32um [expr $ty+0.45]um
    paint li1
    box 2.90um [expr $ty-0.45]um 3.32um [expr $ty+0.45]um
    label VGND
    port make
    port use ground
}

# ---------------------------------------------------------------------
# VDD -- top rail (M2) + source verticals + nwell tap
box -0.3um 72.30um 2.9um 72.80um
paint metal2
box -0.3um 72.30um 2.9um 72.80um
label VDD
port make
# vdd-right M2: xc_p_0/S (y53.3), rst_0/S (y68.7) -> rail; extends down
# to y47.7 to receive the n-well tap jog.
m2v 1.935 47.7 72.6
via1 1.935 53.30
via1 1.935 68.73
# vdd-left M2: xc_p_1/S (y62.8), rst_1/S (y71.2) -> rail
m2v 0.645 60.0 72.6
via1 0.645 62.81
via1 0.645 71.23
# n-well tap -> VDD, placed in the NMOS/PMOS well-boundary gap (y47.6,
# inside nwell which starts at 47.5, below xc_p_0 at y49). It ties to
# the vdd-right rail through an M1 jog that runs UNDER the outm (2.40)
# and strobe (2.80) M2 rails -- M1/M2 are different layers, so no short.
box 2.55um 47.60um 2.95um 48.60um
paint ntap
box 2.66um 47.75um 2.86um 48.45um
paint nsc
box 2.58um 47.65um 2.92um 48.55um
paint li1
box 2.69um 47.93um 2.86um 48.10um
paint viali
box 2.64um 47.70um 2.92um 48.50um
paint metal1
m1h 48.10 1.935 2.92   ;# jog to vdd-right rail, under outm/strobe M2
via1 1.935 48.10

# ---------------------------------------------------------------------
# tail -- tail/D (0.645, y5-12) + inp_0/S, inp_1/S (0.145, y19-32).
# The bridging horizontal spans the full outer width of both verticals
# (0.075..0.715) so the corners have no sub-0.14 notch.
m1v 0.145 16.2 32.7    ;# inp sources
m1v 0.645 5.0 16.2     ;# tail/D up to jog
m1h 16.2 0.075 0.715   ;# jog spanning both verticals

# ---------------------------------------------------------------------
# intp (M1) -- inp_0 right (2.435, y19-23) + xc_n_0 right (1.935, y37-39).
# Runs in the x=2.06 corridor between the inp gate-contact right flank
# (1.75..1.81) and the inp_1 right contact (2.32..2.55), clearing both
# by >=0.18; jogs to the contacts at top and bottom where no flank sits.
m1v 2.435 19.0 22.0
m1h 21.0 2.02 2.505
m1v 2.09 21.0 38.0
# wide patch merges the corridor with xc_n_0/S (1.935) so the two
# near-parallel verticals share copper instead of leaving a sliver.
box 1.865um 37.00um 2.16um 39.70um
paint metal1

# intm (M2 traverse) -- inp_1/D (2.435,y28-32) -> xc_n_1/S (0.645,y43-45)
m1v 2.50 28.5 32.7     ;# inp_1 right contact (right edge), clears intp corridor
via1 2.50 31.0
m2v 2.50 30.8 34.1     ;# carry via pad up to the horizontal jog
m2h 34.0 0.575 2.575   ;# spans both end verticals (no notch); over intp/bln M1
m2v 0.645 34.0 43.2
via1 0.645 43.10
m1v 0.645 43.0 45.2

# ---------------------------------------------------------------------
# outp -- M2 @ 0.20 (left of the 0.645 drains so its 0.38 via pads keep
#         >=0.17 to the vdd-left rail at 0.645) ; drains xc_n_0/D,
#         xc_p_0/D, rst_0/D (0.645) + gates xc_n_1/G, xc_p_1/G (1.29)
m2v 0.20 37.4 68.9
foreach {dy} {38.6 53.3 68.73} {
    m1h $dy 0.20 0.715
    via1 0.20 $dy
}
# gate xc_n_1/G @ (1.29,46.405)
m1h 46.405 0.20 1.29
via1 0.20 46.405
# gate xc_p_1/G @ (1.29,67.13)
m1h 67.13 0.20 1.29
via1 0.20 67.13

# ---------------------------------------------------------------------
# outm -- M2 @ 2.40 ; drains xc_n_1/D, xc_p_1/D, rst_1/D (1.935) +
#         gates xc_n_0/G, xc_p_0/G (1.29)
m2v 2.40 40.0 71.5
foreach {dy} {44.13 62.81 71.23} {
    m1h $dy 1.935 2.40
    via1 2.40 $dy
}
# gate xc_n_0/G @ (1.29,40.905)
m1h 40.905 1.29 2.40
via1 2.40 40.905
# gate xc_p_0/G @ (1.29,57.63)
m1h 57.63 1.29 2.40
via1 2.40 57.63

# ---------------------------------------------------------------------
# strobe -- M2 @ 2.94 (right edge; >=0.14 clear of the intm via pad at
# 2.435->2.625) ; tail/G (1.29,15.9), rst_0/G (1.29,69.47), rst_1/G
# (1.29,71.97)
m2v 2.94 15.9 72.0
m1h 15.905 1.29 2.94
via1 2.94 15.905
m1h 69.47 1.29 2.94
via1 2.94 69.47
m1h 71.97 1.29 2.94
via1 2.94 71.97

# ---------------------------------------------------------------------
# blp / bln input ports (M2 pads at the input-pair gates)
via1 1.29 25.405
box 1.15um 25.10um 1.43um 25.70um
paint metal2
box 1.15um 25.10um 1.43um 25.70um
label BLP
port make

via1 1.29 34.905
box 1.15um 34.60um 1.43um 35.20um
paint metal2
box 1.15um 34.60um 1.43um 35.20um
label BLN
port make

# ---------------------------------------------------------------------
# OUTP / OUTM output ports (label the M2 rails)
box 0.06um 37.4um 0.34um 37.9um
paint metal2
box 0.06um 37.4um 0.34um 37.9um
label OUTP
port make
box 2.26um 40.0um 2.54um 40.5um
paint metal2
box 2.26um 40.0um 2.54um 40.5um
label OUTM
port make

# ---------------------------------------------------------------------
# STROBE port (TAIL is an internal common-source node -- not a pin)
box 2.80um 16.0um 3.08um 16.5um
paint metal2
box 2.80um 16.0um 3.08um 16.5um
label STROBE
port make

drc on
drc check
drc catchup
puts "DRC=[drc list count total]"
select top cell
puts "BBOX=[box values]"

save strongarm

extract no all
extract do local
extract no capacitance
extract no resistance
extract all
ext2spice lvs
ext2spice cthresh infinite
ext2spice rthresh infinite
ext2spice subcircuit on
ext2spice -o strongarm_extracted.spice
puts "Extracted strongarm_extracted.spice"
