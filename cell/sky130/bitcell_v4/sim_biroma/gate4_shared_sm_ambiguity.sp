* BiROMA shared-minus-line AMBIGUITY proof.
* The storage nfet is SYMMETRIC (drain/source interchangeable), so a
* cell stores the UNORDERED pair {drain-target, source-target}.
* Cell A = (E=-1, O=0): drain on the shared minus line, source on the
*   grounded zero-strap.
* Cell B = (E=0, O=-1): drain on the grounded zero-strap, source on the
*   shared minus line.
* These are the IDENTICAL circuit (one terminal on SM, one on ground).
* If sensing SM cannot distinguish them, the shared line loses the E/O
* attribution and the architecture cannot read ternary weights.
.lib /home/mohnishp/.ciel/ciel/sky130/versions/8afc8346a57fe1ab7934ba5a6056ea8b43078e71/sky130A/libs.tech/ngspice/sky130.lib.spice ss
.temp 100
.param vdd=1.62

Vdd vdd 0 dc {vdd}
Vwl wl 0 pwl(0 0 1n 0 1.2n {vdd})

* Cell A: (E=-1, O=0) -> D=SM_A, S=gnd
Csa SM_A 0 40f ic={vdd/2}
XA SM_A wl 0 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17

* Cell B: (E=0, O=-1) -> D=gnd, S=SM_B
Csb SM_B 0 40f ic={vdd/2}
XB 0 wl SM_B 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17

.tran 0.02n 8n uic
.control
run
meas tran va_final find v(SM_A) at=7.9n
meas tran vb_final find v(SM_B) at=7.9n
let diff = abs(v(SM_A) - v(SM_B))
meas tran maxdiff max diff from=1n to=8n
quit
.endc
.end
