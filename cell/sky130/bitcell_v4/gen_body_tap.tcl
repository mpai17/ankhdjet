# Generate the body_tap cell — a p-substrate tap (psubdiff + psubdiffcont
# + locali) shared across the array per the SKY130 latch-up rule
# (~15 um max distance from any nfet to a tap).
#
# Sized to meet SKY130 DRC minimums. The earlier 0.20x0.20 size was
# below psd.10b/licon.1/licon.7/li.5/li.6 minimums:
#   psubdiff:     0.41 x 0.29 = 0.1189 um^2  (psd.10b min 0.07011 um^2,
#                                              licon.7 0.12 / 0.06 um overlap)
#   psubdiffcont: 0.17 x 0.17               (licon.1 min 0.17 um width)
#   locali:       0.33 x 0.29 = 0.0957 um^2  (li.6 min 0.0561 um^2,
#                                              li.5 0.08 / 0.06 um overlap)
#
# Run via:
#   cd build && magic -dnull -noconsole -T sky130A < ../gen_body_tap.tcl

drc off
load body_tap -quiet
select top cell
cellname rename "(UNNAMED)" body_tap

# P-tap diff: 0.41 x 0.29 (asymmetric — wider in x to satisfy the 0.12 um
# psd-licon overlap rule; 0.06 um overlap in y)
box -0.205um -0.145um 0.205um 0.145um
paint psubdiff

# P-tap contact (licon1 on psd): square at minimum width
box -0.085um -0.085um 0.085um 0.085um
paint psubdiffcont

# Local interconnect: 0.33 x 0.29 (0.08 um overlap of the licon in x,
# 0.06 um in y)
box -0.165um -0.145um 0.165um 0.145um
paint locali

drc on
drc check
puts "DRC=[drc list count total]"

save body_tap

puts "===== body_tap generation summary ====="
puts "0.41 x 0.29 um substrate tap"
puts "shared across <= 15 um from any NMOS in the array"
puts "========================================"
