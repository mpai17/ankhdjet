* Full-sense-path SPICE integration: bitcell_v4 -> precharge -> StrongARM SA
* composed end-to-end into one ngspice deck. Drives a complete
* precharge/read/sense cycle and measures whether the SA latches the
* correct polarity for a known weight on a 64-row-loaded BL pair.
*
* This is the smallest macro-level SPICE test that exercises the
* electrical interaction of the three custom cells in series. It does
* NOT model:
*   - the row decoder, accumulator, adder tree (those are stdcell-
*     synthesizable; their integration is validated at the Verilator
*     wrapper level)
*   - the full N x M array (would require a hand-laid-out macro
*     layout that doesn't exist yet; deferred-tapeout work)
*
* Sibling-cell parasitics on each BL are lumped per the bitcell
* test_harness.sp values: SUBCOL=64, C_DRAIN=0.6 fF/cell, C_WIRE=
* 0.262 fF/cell -> ~55 fF total per BL. Closely matches the 32 fF
* used in the precharge functional test; both are within the ~30-60
* fF range a real SUBCOL=64 BL sees.
*
* Pass criterion: at t=8 ns,
*   weight=+1 (active cell on BL+): OUTP - OUTM > +0.9 V
*   weight=-1 (active cell on BL-): OUTM - OUTP > +0.9 V

.param VDD_V       = 1.8
.param N           = 64
.param C_DRAIN_F   = 0.6e-15
.param C_WIRE_F    = 0.262e-15
.param T_RISE_S    = 50p
.param SCEN        = 1   ; +1 -> active on BL+ ; -1 -> active on BL- ; 0 -> none

* Power
Vvdd vdd 0 'VDD_V'
Vgnd vgnd 0 0

* ---- Stimulus ----
* PRE_n: low t=0..1ns (PMOS on, both BLs precharged high), then high.
Vpre_n pre_n 0 PULSE('VDD_V' 0 0  'T_RISE_S' 'T_RISE_S' 0.95n 100n)
* WL  : rises 1.05ns (right after precharge ends).
Vwl   wl    0 PULSE(0 'VDD_V' 1.05n 'T_RISE_S' 'T_RISE_S' 6n 100n)
* STROBE: rises 3 ns (after BL has time to develop a differential).
Vstrobe strobe 0 PULSE(0 'VDD_V' 3n 'T_RISE_S' 'T_RISE_S' 90n 100n)

* ---- Precharge cell on BL+ and BL- ----
* W=0.42 L=0.15 PMOS, gate=pre_n, source=vdd, drain=BL.
Xpre_p blp pre_n vdd vdd sky130_fd_pr__pfet_01v8 w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42
Xpre_n bln pre_n vdd vdd sky130_fd_pr__pfet_01v8 w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42

* ---- Active bitcell ----
* bitcell_v4: W=0.42 L=0.15 NMOS. Drain on BLP for weight=+1, BLN for
* weight=-1. Use B-source (behavioral) to gate the WL into whichever
* active cell matches SCEN; the unmatched cell's gate is tied LOW.
.if (SCEN > 0)
Xact_p blp wl   vgnd vgnd sky130_fd_pr__nfet_01v8 w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42
Xact_n bln vgnd vgnd vgnd sky130_fd_pr__nfet_01v8 w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42
.elseif (SCEN < 0)
Xact_p blp vgnd vgnd vgnd sky130_fd_pr__nfet_01v8 w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42
Xact_n bln wl   vgnd vgnd sky130_fd_pr__nfet_01v8 w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42
.else
Xact_p blp vgnd vgnd vgnd sky130_fd_pr__nfet_01v8 w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42
Xact_n bln vgnd vgnd vgnd sky130_fd_pr__nfet_01v8 w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42
.endif

* ---- Sibling-cell lumped parasitics (N-1 cells per BL) ----
* Each off-cell contributes drain cap + wire-segment cap to (BL, GND).
Cbl_p blp 0 '(N-1)*(C_DRAIN_F + C_WIRE_F)'
Cbl_n bln 0 '(N-1)*(C_DRAIN_F + C_WIRE_F)'

* ---- StrongARM SA from the project's schematic ----
.include "../../../../cell/sky130/strongarm/strongarm_schematic.spice"
Xsa blp bln outp outm strobe vdd vgnd strongarm

* ---- Measurements ----
.tran 5p 8n
.measure tran v_blp_at_strobe FIND v(blp) AT=2.95n
.measure tran v_bln_at_strobe FIND v(bln) AT=2.95n
.measure tran v_outp_final    FIND v(outp) AT=7.5n
.measure tran v_outm_final    FIND v(outm) AT=7.5n
