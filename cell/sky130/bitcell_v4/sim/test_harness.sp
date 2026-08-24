* BL discharge sweep deck (parameterized by N and PVT corner).
*
* Models a single cirom cell driving a column-shared BL+ that has
* (N-1) inactive sibling cells contributing only their drain
* parasitic capacitance + segment of M2 BL wire. Measures the time
* for BL+ to droop from VDD to VDD/2 once WL is asserted.
*
* The PARAM N is the column height (cells per BL). C_DRAIN is the
* per-cell drain-to-substrate capacitance from Magic extraction.
* C_WIRE_PER_CELL is the BL M2 wire capacitance per cell pitch.
* VDD set inside corner section.
*
* Updated for bitcell_v4 (W=0.42 um, 0.89 um row pitch):
*   - C_DRAIN at minimum-W bitcell_v4 dimensions: ndiff drain area
*     0.42 * 0.18 = 0.076 um^2; with via1 to BL adds ~0.6 fF total.
*   - C_WIRE scaled from 0.2 fF/cell at 0.68 um pitch to
*     0.2 * 0.89/0.68 = 0.262 fF/cell at 0.89 um pitch.

.param N         = 128
.param VDD_V     = 1.8
.param C_DRAIN_F = 0.6e-15
.param C_WIRE_F  = 0.262e-15
.param T_RISE_S  = 50p
.param T_WL_HI_S = 5n

* WL pulse: 0 -> VDD at t=1ns
Vwl wl 0 PULSE(0 'VDD_V' 1n 'T_RISE_S' 'T_RISE_S' 'T_WL_HI_S' 100n)

* Power rails
Vvdd vdd 0 'VDD_V'
Vgnd vgnd 0 0

* Active cell - the one driving the BL
* Drain on bl, gate on wl, source on vgnd. ad/pd/as/ps from the
* parasitic-extracted v3 cell (cell/sky130/bitcell_v3/bitcell_v3.spice):
* X0 S a_n15_n110# D VSUBS sky130_fd_pr__nfet_01v8 ad=0.2436 pd=2.26 as=0.2436 ps=2.26 w=0.84 l=0.15
Xact bl wl vgnd vgnd sky130_fd_pr__nfet_01v8 w=0.42 l=0.15 ad=0.1218 pd=1.42 as=0.1218 ps=1.42

* Aggregated sibling parasitics:
*   - (N-1) drains each contributing C_DRAIN to (BL, GND)
*   - (N-1) wire segments contributing C_WIRE to (BL, GND)
* Combine into a single lumped cap.
Cbl bl 0 '(N-1)*(C_DRAIN_F + C_WIRE_F)'

* Precharge: the BL is held high until a moment before the WL pulse.
* Model with a PMOS-equivalent ideal switch: at t<0.95ns, BL=VDD via Rprech;
* at t>0.95ns, switch opens (Rprech goes high). Easiest: a piecewise
* voltage source with a high-Z phase implemented via a switch.
*
* In ngspice, use a controlled switch with a precharge enable that is
* high during the precharge phase and low during the read phase.
Vprech_en pre_en 0 PULSE(1 0 0.9n 1p 1p 100n 100n)
* Switch model: closed when pre_en > 0.5
.model SWPRE sw vt=0.5 vh=0.1 ron=100 roff=1G
Spre bl vdd pre_en 0 SWPRE

* --- Measurements ---
.tran 5p 8n
.measure tran v_bl_at_wl_start FIND v(bl) AT=1n
.measure tran t_drop_to_half_vdd
+   WHEN v(bl)='0.5*VDD_V' RISE=1 TD=1n CROSS=1
+   FALL=1
* The above measure can't combine RISE and FALL; use a simpler approach:
* find when v(bl) first crosses 0.9V (which is VDD/2 for VDD=1.8) after WL goes high.
.measure tran t_50pct WHEN v(bl)='0.5*VDD_V' FALL=1 TD=1n
.measure tran v_bl_at_2ns FIND v(bl) AT=2n
.measure tran v_bl_at_3ns FIND v(bl) AT=3n
.measure tran v_bl_at_5ns FIND v(bl) AT=5n

.print tran v(bl) v(wl) v(pre_en)

.end
