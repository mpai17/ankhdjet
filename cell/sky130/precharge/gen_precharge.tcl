# Precharge cell — clocked PMOS bitline pull-up (see
# docs/precharge_design.md): sky130 pfet_01v8 W=1.0 L=0.15, gate on
# PRE_N. The macro stacks two rows of these per column (one row pulls
# BL+ up, one BL-).
#
# The gate comb gets a hand-painted contact stack (poly cap + polycont
# + li + viali + met1) above the device, so the macro-level drain jogs
# (which run at the device y-range) never share an x-budget with it.
#
# Run via:
#   cd build && magic -dnull -noconsole -T sky130A < ../gen_precharge.tcl

drc off
file delete -force precharge.mag precharge.gds precharge.ext
load precharge -quiet
select top cell
cellname rename "(UNNAMED)" precharge

box position 0 0
box size 0 0
::sky130::sky130_fd_pr__pfet_01v8_draw [dict merge \
    [::sky130::sky130_fd_pr__pfet_01v8_defaults] \
    {w 1.0 l 0.15 nf 1 m 1 \
     glc 0 grc 0 gtc 0 gbc 0 \
     topc 0 botc 0 \
     diffcov 100 polycov 100 tbcov 100 rlcov 100 \
     viasrc 100 viadrn 100 viagate 0 \
     guard 0 doverlap 0 poverlap 0}]

# Gate-top contact stack (the PCell gtc flag is for guard rings):
# poly cap bridging the 0.15 stub, licon >= 0.19 above the pdiff top
# (licon.14), li + viali + met1 pad for the row-level PRE_N bus. The
# met1 pad starts 0.15 above the drain/source plates (met1.2), so the
# macro drain jogs at the device y-range never touch the gate net.
box -0.135um 0.63um 0.135um 1.01um
paint poly
box -0.085um 0.76um 0.085um 0.93um
paint polycont
box -0.165um 0.69um 0.165um 1.00um
paint locali
box -0.085um 0.76um 0.085um 0.93um
paint viali
box -0.135um 0.70um 0.135um 1.03um
paint metal1

# Ports: D (drain, ties a bitline), S (source, ties VPWR), G (PRE_N).
# Labels pinned to metal1 (an unqualified label here would attach to
# the nwell, which spans both plates and shorts D to S in extraction).
box -0.32um -0.1um -0.12um 0.1um
label D c metal1
port make
box 0.12um -0.1um 0.32um 0.1um
label S c metal1
port make
box -0.05um 0.95um 0.05um 1.0um
label G c metal1
port make

select top cell
puts "PCELL BBOX: [box values]"

drc on
drc check
drc catchup
puts "DRC=[drc list count total]"
puts "WHY=[drc list why]"

save precharge

puts "===== precharge generation summary ====="
puts "1 x sky130_fd_pr__pfet_01v8 W=1.0 L=0.15, gate-top PRE_N contact"
puts "========================================="
