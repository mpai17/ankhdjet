* StrongARM with oversized input pair for SKY130 mismatch margin.
*
* Background: bare StrongARM with input pair W=2/L=0.3 has empirical
* sigma_offset ≈ 130 mV at SS corner (Monte Carlo against
* sky130_fd_pr__nfet_01v8__mismatch.corner with mc_mm_switch=1).
* That is too much offset to resolve TriMLA-style reference
* comparisons even with end-of-accumulation BL signal.
*
* The fix: oversize the input pair (and to a lesser degree the
* cross-coupled latch transistors) so per-device sigma_VTH drops
* via Pelgrom: sigma = vth0_slope / sqrt(W*L).
*
* Sizing here:
*   tail NMOS:    W=14.0 L=0.15 (proportional to input current)
*   input NMOS:   W=10.0 L=2.0  → area 20 um^2, sigma_VTH=0.75 mV/dev
*   xc NMOS:      W= 4.0 L=1.0  → area 4 um^2,  sigma_VTH=1.68 mV/dev
*   xc PMOS:      W= 8.0 L=1.0
*   reset PMOS:   W= 0.84 L=0.15
*
* Per-SA area ≈ 50 um^2. With 32 SAs per array: 1600 um^2 = 1.6% of
* the cirom_array macro at 256x256 cells. Acceptable cost at SKY130.
*
* At advanced nodes (28 nm, 7 nm) where sigma_VTH per device drops
* ~3-5x, the oversize factor needed shrinks; node-shrink relaxes the
* SA-area cost. At very advanced nodes, auto-zero offset cancellation
* (capacitive offset capture) becomes the area-efficient choice
* instead of oversized devices. Both topologies are valid.

.param VIN_DIFF_V    = 0.100
.param VIN_CM_V      = 1.700
.param VDD_V         = 1.8
.param STROBE_DELAY  = 1n
.param T_STROBE_RISE = 50p

Vvdd vdd 0 'VDD_V'
Vvgnd vgnd 0 0
Vblp blp 0 'VIN_CM_V + VIN_DIFF_V/2'
Vbln bln 0 'VIN_CM_V - VIN_DIFF_V/2'
Vstrobe strobe 0 PULSE(0 'VDD_V' 'STROBE_DELAY' 'T_STROBE_RISE' 'T_STROBE_RISE' 5n 100n)

Xtail   tail strobe vgnd vgnd sky130_fd_pr__nfet_01v8 w=14.0 l=0.15
Xinp    intp blp tail vgnd sky130_fd_pr__nfet_01v8 w=8.0 l=2.0
Xinm    intm bln tail vgnd sky130_fd_pr__nfet_01v8 w=8.0 l=2.0
Xncxp   outp outm intp vgnd sky130_fd_pr__nfet_01v8 w=4.0 l=1.0
Xncxm   outm outp intm vgnd sky130_fd_pr__nfet_01v8 w=4.0 l=1.0
Xpcxp   outp outm vdd vdd sky130_fd_pr__pfet_01v8 w=8.0 l=1.0
Xpcxm   outm outp vdd vdd sky130_fd_pr__pfet_01v8 w=8.0 l=1.0
Xprstp  outp strobe vdd vdd sky130_fd_pr__pfet_01v8 w=0.84 l=0.15
Xprstm  outm strobe vdd vdd sky130_fd_pr__pfet_01v8 w=0.84 l=0.15

* Larger output load reflects the bigger driver fanout in real layout
Coutp outp 0 10f
Coutm outm 0 10f

.tran 5p 5n
.measure tran t_outm_high WHEN v(outm)='0.9*VDD_V' RISE=1 TD='STROBE_DELAY'
.measure tran t_outp_low  WHEN v(outp)='0.1*VDD_V' FALL=1 TD='STROBE_DELAY'
.measure tran v_outp_final FIND v(outp) AT=4.5n
.measure tran v_outm_final FIND v(outm) AT=4.5n

.print tran v(outp) v(outm) v(strobe) v(blp) v(bln)

.end
