* BiROMA phase-swap coupling: a held (floating, precharged) bitline with
* 64 OFF cells whose far-side terminals all step VSS -> VDD together
* (the worst case: the opposite side re-precharging after role swap,
* every cell on this line programmed to the swapped side). WL low, so
* only Cds/junction coupling carries charge into the held node.
.lib /home/mohnishp/.ciel/ciel/sky130/versions/1e931c9417df0478df9ee6b7289202f3e87440ab/sky130A/libs.tech/ngspice/sky130.lib.spice ss
.temp 100
.param vdd=1.62

Vdd vdd 0 dc {vdd}
* held line: precharged then floating (40fF incl wire)
Chold held 0 40f ic={vdd}
* far side steps 0 -> vdd in 1ns at t=2n
Vfar far 0 pwl(0 0 2n 0 3n {vdd})
* 64 off cells bridging far -> held (gates grounded)
.subckt offcell a b
Xm a gnd_g b 0 sky130_fd_pr__nfet_01v8 w=0.42 l=0.17
Vg gnd_g 0 dc 0
.ends
X0 far held offcell
X1 far held offcell
X2 far held offcell
X3 far held offcell
X4 far held offcell
X5 far held offcell
X6 far held offcell
X7 far held offcell
X8 far held offcell
X9 far held offcell
X10 far held offcell
X11 far held offcell
X12 far held offcell
X13 far held offcell
X14 far held offcell
X15 far held offcell
X16 far held offcell
X17 far held offcell
X18 far held offcell
X19 far held offcell
X20 far held offcell
X21 far held offcell
X22 far held offcell
X23 far held offcell
X24 far held offcell
X25 far held offcell
X26 far held offcell
X27 far held offcell
X28 far held offcell
X29 far held offcell
X30 far held offcell
X31 far held offcell
X32 far held offcell
X33 far held offcell
X34 far held offcell
X35 far held offcell
X36 far held offcell
X37 far held offcell
X38 far held offcell
X39 far held offcell
X40 far held offcell
X41 far held offcell
X42 far held offcell
X43 far held offcell
X44 far held offcell
X45 far held offcell
X46 far held offcell
X47 far held offcell
X48 far held offcell
X49 far held offcell
X50 far held offcell
X51 far held offcell
X52 far held offcell
X53 far held offcell
X54 far held offcell
X55 far held offcell
X56 far held offcell
X57 far held offcell
X58 far held offcell
X59 far held offcell
X60 far held offcell
X61 far held offcell
X62 far held offcell
X63 far held offcell

.tran 0.02n 10n uic
.control
run
meas tran v_pre  find v(held) at=1.9n
meas tran v_max  max v(held) from=2n to=10n
meas tran v_end  find v(held) at=9.9n
quit
.endc
.end
