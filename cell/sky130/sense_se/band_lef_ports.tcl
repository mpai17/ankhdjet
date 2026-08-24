# Emit the band LEF from the KLayout band GDS. The GDS carries its port labels on
# the metal PIN datatype (signals 70/16, power 68/16/69/16/71/16), which cifinput
# reads as ports -- so `lef write` emits full-riser met3 signal pins plus the
# nwell/li1/met1..met4 obstruction comb directly. Power pins come out clipped
# (lef write trims full-width rails / ring edges), so author_band_lef.py rewrites
# VDD/VGND from the manifest afterwards.
#   in:  sa_se_band16_kl.gds
#   out: sa_se_band16_kl.lef
drc off
gds read sa_se_band16_kl.gds
load sa_se_band16 -quiet
lef write sa_se_band16_kl -hide
puts "BAND_LEF_DONE"
quit -noprompt
