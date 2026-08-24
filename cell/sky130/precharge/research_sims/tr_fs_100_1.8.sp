* transient: discharge / clocked precharge / pseudo-NMOS recovery  fs 100C 1.8V
.lib /home/mohnishp/.ciel/sky130A/libs.tech/ngspice/sky130.lib.spice fs
.temp 100
.param vdd=1.8
VDD vdd 0 {vdd}
Vg gon 0 {vdd}
* 1) cell discharge of 65fF from vdd (clocked precharge off, no pull-up)
Xdis bld gon 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17
Cd bld 0 65f
.ic v(bld)={vdd}
* 2) cell discharge fighting always-on pull-up W=0.42 L=1
Xdis2 bldr gon 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17
Xpur bldr 0 vdd vdd sky130_fd_pr__pfet_01v8 W=0.42 L=1
Cdr bldr 0 65f
.ic v(bldr)={vdd}
* 3) pseudo-NMOS recovery: always-on pull-up recharges BL from 0, 64 off cells attached
Xpu1 blr1 0 vdd vdd sky130_fd_pr__pfet_01v8 W=0.42 L=1
Xoff1 blr1 0 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17 m=64
Cr1 blr1 0 65f
.ic v(blr1)=0
Xpu2 blr2 0 vdd vdd sky130_fd_pr__pfet_01v8 W=0.42 L=2
Xoff2 blr2 0 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17 m=64
Cr2 blr2 0 65f
.ic v(blr2)=0
* 4) clocked precharge: full-on PMOS gate=0
Xpc1 blc1 0 vdd vdd sky130_fd_pr__pfet_01v8 W=0.42 L=0.15
Xoffc1 blc1 0 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17 m=64
Cc1 blc1 0 65f
.ic v(blc1)=0
Xpc2 blc2 0 vdd vdd sky130_fd_pr__pfet_01v8 W=1.0 L=0.15
Xoffc2 blc2 0 0 0 sky130_fd_pr__nfet_01v8 W=0.42 L=0.17 m=64
Cc2 blc2 0 65f
.ic v(blc2)=0
.tran 5p 200n uic
.meas tran tdis_x09 when v(bld)=0.9 fall=1
.meas tran tdis_x06 when v(bld)=0.6 fall=1
.meas tran tdis_x03 when v(bld)=0.3 fall=1
.meas tran tdisr_x06 when v(bldr)=0.6 fall=1
.meas tran trec_L1 when v(blr1)=1.620 rise=1
.meas tran trec_L2 when v(blr2)=1.620 rise=1
.meas tran tpre_w042 when v(blc1)=1.710 rise=1
.meas tran tpre_w1 when v(blc2)=1.710 rise=1
.end
