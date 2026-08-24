* BiROMA gate 1: BL development with the far-side line in the path.
* Old path: cell source hard-grounded. New path: cell source -> far-side
* digit line (RC of ~83um met3 at the projected 2.1um pitch, 64 rows)
* -> per-column pulldown NMOS. Compare discharge of a 40fF bitline.
.lib /home/mohnishp/.ciel/ciel/sky130/versions/1e931c9417df0478df9ee6b7289202f3e87440ab/sky130A/libs.tech/ngspice/sky130.lib.spice ss
.temp 100
.param vdd=1.62

Vdd vdd 0 dc {vdd}
Vwl wl 0 pwl(0 0 1n 0 1.2n {vdd})

* old path: direct ground
Cbl_old bl_old 0 40f ic={vdd}
Xc_old bl_old wl 0 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17

* new path: far-side line RC (5 lumps) + pulldown (W=1.0 ON)
Cbl_new bl_new 0 40f ic={vdd}
Xc_new bl_new wl n1 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
R1 n1 n2 1.0
C1 n2 0 8f
R2 n2 n3 1.0
C2 n3 0 8f
R3 n3 n4 1.0
C3 n4 0 8f
R4 n4 n5 1.0
C4 n5 0 8f
Xpd n5 vdd 0 0 sky130_fd_pr__nfet_01v8 w=1.0 l=0.15

.tran 0.02n 12n uic
.control
run
meas tran t_old when v(bl_old)=0.81 fall=1
meas tran t_new when v(bl_new)=0.81 fall=1
meas tran t_old3 when v(bl_old)=0.3 fall=1
meas tran t_new3 when v(bl_new)=0.3 fall=1
quit
.endc
.end
