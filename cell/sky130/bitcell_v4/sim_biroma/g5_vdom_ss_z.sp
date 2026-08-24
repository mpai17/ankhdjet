* voltage-domain 3-level read feasibility: selected weight delivers 0.9V to a
* merged sensed node precharged to VDD/2; 63 off-cells leak to 0.0V.
.lib /home/mohnishp/.ciel/ciel/sky130/versions/8afc8346a57fe1ab7934ba5a6056ea8b43078e71/sky130A/libs.tech/ngspice/sky130.lib.spice ss
.temp 100
.param vdd=1.8
Vdd vdd 0 dc {vdd}
* wordline: selected row fires at 1ns
Vwl wl 0 pwl(0 0 1n 0 1.2n {vdd})
Voff woff 0 dc 0   $ unselected rows held low
* merged sensed node (3 met3 lines merged + junctions): ~120fF, precharged to VDD/2
Csns sns 0 120f ic={vdd/2}
* driven reference rail for the selected cell, held at the weight level via 1k rail Z
Vdrv drv0 0 dc 0.9
Rrail drv0 drv 1k
* far-side line RC (5 lumps) between cell source and the rail
Xsel sns wl n1 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
R1 n1 n2 1.0
C1 n2 0 8f
R2 n2 n3 1.0
C2 n3 0 8f
R3 n3 n4 1.0
C3 n4 0 8f
R4 n4 drv 1.0
* 63 off-cells: drain on sns, source on a line at 0.0V, gate low (leakage)
Vleak vleak 0 dc 0.0
Xoff0 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff1 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff2 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff3 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff4 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff5 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff6 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff7 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff8 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff9 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff10 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff11 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff12 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff13 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff14 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff15 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff16 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff17 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff18 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff19 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff20 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff21 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff22 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff23 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff24 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff25 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff26 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff27 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff28 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff29 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff30 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff31 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff32 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff33 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff34 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff35 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff36 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff37 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff38 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff39 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff40 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff41 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff42 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff43 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff44 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff45 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff46 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff47 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff48 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff49 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff50 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff51 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff52 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff53 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff54 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff55 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff56 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff57 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff58 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff59 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff60 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff61 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Xoff62 sns woff vleak 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
.tran 0.02n 12n uic
.control
run
meas tran v_settle find v(sns) at=6n
meas tran v_late find v(sns) at=11n
quit
.endc
.end
