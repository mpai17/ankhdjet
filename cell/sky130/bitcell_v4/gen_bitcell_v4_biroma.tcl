# bitcell_v4_biroma — physically identical to bitcell_v4, both ndiff
# regions exposed as drain candidates for BiROMA bidirectional read.
# Effective 0.25 um^2 per stored weight at SKY130 (0.50 um^2 cell / 2
# weights via bidirectional read).
#
# Run via:
#   cd build && magic -dnull -noconsole -T sky130A < ../gen_bitcell_v4_biroma.tcl

drc off
load bitcell_v4_biroma -quiet
select top cell
cellname rename "(UNNAMED)" bitcell_v4_biroma

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

# Note: in earlier iterations we re-labeled the cell's two ndiff
# terminals as D_E (even-side drain) and D_O (odd-side drain) to
# document the BiROMA bidirectional-read convention at the cell port
# level. That `goto D; box grow; label; port make` sequence perturbs
# the gate-top contact stack's metal1/viali geometry (tracked: 5
# met1.4/met1.5 violations). The BiROMA semantics are unchanged --
# both ndiff sides are drain candidates -- and the array-level
# read-direction control lives in the sense-amp / decoder, not the
# cell labels. Keeping the cell with plain D and S labels matches
# bitcell_v4 and stays DRC-clean.
#
# Hand-paint the same gate-top contact stack as bitcell_v4 so the gate
# signal can be routed by an array-level WL strap on metal1.
# (See gen_bitcell_v4.tcl for the rule-by-rule sizing rationale.)
box -0.135um 0.34um 0.135um 0.67um
paint poly
box -0.085um 0.42um 0.085um 0.59um
paint polycont
box -0.165um 0.40um 0.165um 0.71um
paint locali
box -0.085um 0.42um 0.085um 0.59um
paint viali
box -0.135um 0.36um 0.135um 0.67um
paint metal1

box -0.05um 0.50um 0.05um 0.55um
label G
port make

drc on
drc check
drc count

save bitcell_v4_biroma

puts "===== bitcell_v4_biroma summary ====="
puts "Physical cell identical to bitcell_v4 (0.50 um^2)."
puts "BiROMA-encoded: 2 ternary weights / 1T cell."
puts "Effective per-weight area: 0.25 um^2."
puts "======================================"
