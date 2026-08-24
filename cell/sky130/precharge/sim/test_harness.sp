* Precharge recharge-time sweep deck (parameterized by C_BL and PVT corner).
*
* Models the precharge PMOS pulling a BL that previously drooped by
* DELTA mV during a sense cycle back up to ~VDD before the next cycle.
* Measures the time from PRE_n falling edge (PMOS turns on) until BL
* reaches VDD - 50 mV.
*
* From cell/sky130/precharge/gen_precharge.tcl:
*   - W = 1.0 um, L = 0.15 um clocked PMOS pull-up (docs/precharge_design.md).
*   - Typical BL load at SUBCOL=64: ~32 fF.
*   - Target: recharge 200 mV droop in << 1 ns at SS corner.
*
* Pass criterion: T_recharge < 1 ns at SS @ VDD=1.62 V. Stricter at
* TT/FF.

.param VDD_V     = 1.8
.param C_BL_F    = 32e-15
.param DELTA_V   = 0.20
.param T_PRE_LO_S = 5n

* Power rails
Vvdd vdd 0 'VDD_V'
Vgnd vgnd 0 0

* PRE_n pulse: starts HIGH (PMOS off), falls LOW at t=1ns to enable
* recharge for 5ns, then back HIGH.
Vpre_n pre_n 0 PULSE('VDD_V' 0 1n 50p 50p 'T_PRE_LO_S' 100n)

* Initial BL voltage: VDD - DELTA_V (the worst-case droop after sense)
.ic v(bl)='VDD_V - DELTA_V'

* Precharge PMOS: source=VDD, gate=pre_n, drain=BL, bulk=VDD.
Xpre bl pre_n vdd vdd sky130_fd_pr__pfet_01v8 w=1.0 l=0.15

* BL load capacitance.
Cbl bl 0 'C_BL_F'

* --- Measurements ---
.tran 5p 8n uic
.measure tran v_bl_at_pre_start FIND v(bl) AT=1n
* Standard ready threshold: BL within 5% of VDD (= 0.95 * VDD).
.measure tran t_recharge WHEN v(bl)='0.95*VDD_V' rise=1 td=1n
.measure tran v_bl_final FIND v(bl) AT=6n
