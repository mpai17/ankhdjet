* StrongARM sense-amp test harness — drives BLP/BLN/STROBE and measures
* strobe-to-output resolution for a single (corner, VIN_DIFF) point.
*
* The SA itself is sourced from a `.subckt strongarm` provided by an
* .include line that the runner prepends:
*   - schematic mode: includes cell/sky130/strongarm/strongarm_schematic.spice
*   - extracted mode:  includes cell/sky130/strongarm/build/strongarm_extracted_rcc.spice
* Both sources export the same pin order (BLP BLN OUTP OUTM STROBE VDD VGND);
* the PMOS bodies are tied to VDD inside the subckt, so there is no VPB pin.
*
* Pass criterion: when STROBE goes high, OUT+/OUT- must diverge in the
* correct direction with strobe-to-output <= 500 ps.

.param VIN_DIFF_V    = 0.100
.param VIN_CM_V      = 1.700
.param VDD_V         = 1.8
.param STROBE_DELAY  = 1n
.param T_STROBE_RISE = 50p

* Power rails (PMOS bodies are tied to VDD inside the subckt — no VPB pin)
Vvdd vdd 0 'VDD_V'
Vvgnd vgnd 0 0

* Differential inputs (held constant for the measurement window)
Vblp blp 0 'VIN_CM_V + VIN_DIFF_V/2'
Vbln bln 0 'VIN_CM_V - VIN_DIFF_V/2'

* Strobe pulse: 0 -> VDD at t = STROBE_DELAY, held high for 90 ns
* (well beyond the 10 ns sim window) so the SA latch has time to resolve
* even at metastable trials without the reset PMOS pulling outputs back.
Vstrobe strobe 0 PULSE(0 'VDD_V' 'STROBE_DELAY' 'T_STROBE_RISE' 'T_STROBE_RISE' 90n 200n)

* The runner prepends the .include line for the strongarm subckt source.
* Pin order matches schematic: BLP BLN OUTP OUTM STROBE VDD VGND
Xsa blp bln outp outm strobe vdd vgnd strongarm

* Output load (downstream gate cap)
Coutp outp 0 5f
Coutm outm 0 5f

* Simulation window 10 ns: the SS-mismatch-validated SA (W=10/L=2 input
* pair) takes ~2-3 ns to resolve typical at SS, with metastable trials
* taking up to ~8 ns. v_*_final captured at 9.5 ns to let metastable
* trials fully settle before the resolved/wrong decision.
.tran 5p 10n
.measure tran t_outp_high WHEN v(outp)='0.9*VDD_V' RISE=1 TD='STROBE_DELAY'
.measure tran t_outm_high WHEN v(outm)='0.9*VDD_V' RISE=1 TD='STROBE_DELAY'
.measure tran t_outp_low  WHEN v(outp)='0.1*VDD_V' FALL=1 TD='STROBE_DELAY'
.measure tran t_outm_low  WHEN v(outm)='0.1*VDD_V' FALL=1 TD='STROBE_DELAY'
.measure tran v_outp_final FIND v(outp) AT=9.5n
.measure tran v_outm_final FIND v(outm) AT=9.5n

.print tran v(outp) v(outm) v(strobe) v(blp) v(bln)

.end
