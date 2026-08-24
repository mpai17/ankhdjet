* DC characterization fs 100C vdd=1.8
.lib /home/mohnishp/.ciel/sky130A/libs.tech/ngspice/sky130.lib.spice fs
.temp 100
.param vdd=1.8
VDD vdd 0 {vdd}
* --- cell ON current, Vds=0.9 / 0.2 / 0.1 (0V ammeters in series) ---
Vg g 0 {vdd}
Vd9 d9m 0 0.9
Vamd9 d9m d9 0
Xc9 d9 g 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17
Vd2 d2m 0 0.2
Vamd2 d2m d2 0
Xc2 d2 g 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17
Vd1 d1m 0 0.1
Vamd1 d1m d1 0
Xc1 d1 g 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17
* --- cell OFF leakage, Vds=vdd, m=64 ---
Vdoff doffm 0 {vdd}
Vamoff doffm doff 0
Xoff doff 0 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17 m=64
* --- off precharge pmos leakage into BL held at 0.9 (gate=vdd) ---
Vblh blhm 0 0.9
Vamblh blhm blh 0
Xpoff blh vdd vdd vdd sky130_fd_pr__pfet_01v8 W=1.0 L=0.15
* --- pseudo-NMOS dividers: pull-up W=0.42, L in {0.5,1,2,4,8}, cell on ---
Xpu1 bl1 0 vdd vdd sky130_fd_pr__pfet_01v8 W=0.42 L=0.5
Xnd1 bl1 g 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17
Xpu2 bl2 0 vdd vdd sky130_fd_pr__pfet_01v8 W=0.42 L=1
Xnd2 bl2 g 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17
Xpu3 bl3 0 vdd vdd sky130_fd_pr__pfet_01v8 W=0.42 L=2
Xnd3 bl3 g 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17
Xpu4 bl4 0 vdd vdd sky130_fd_pr__pfet_01v8 W=0.42 L=4
Xnd4 bl4 g 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17
Xpu5 bl5 0 vdd vdd sky130_fd_pr__pfet_01v8 W=0.42 L=8
Xnd5 bl5 g 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17
* pull-up DC current with BL forced to 0 (static power ceiling per conducting BL)
Vbl0 bl0m 0 0
Vambl0 bl0m bl0 0
Xpu0 bl0 0 vdd vdd sky130_fd_pr__pfet_01v8 W=0.42 L=2
.control
op
echo RESULT corner=fs T=100 vdd=1.8
echo ION_VDS0.9 = "$&i(Vamd9)"
echo ION_VDS0.2 = "$&i(Vamd2)"
echo ION_VDS0.1 = "$&i(Vamd1)"
echo IOFF_64CELLS = "$&i(Vamoff)"
echo IPRE_PMOS_OFFLEAK = "$&i(Vamblh)"
echo VOL_L0.5 = "$&v(bl1)"
echo VOL_L1 = "$&v(bl2)"
echo VOL_L2 = "$&v(bl3)"
echo VOL_L4 = "$&v(bl4)"
echo VOL_L8 = "$&v(bl5)"
echo ISTAT_PULLUP_L2_BL0 = "$&i(Vambl0)"
quit
.endc
.end
