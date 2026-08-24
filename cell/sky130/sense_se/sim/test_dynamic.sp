* Dynamic read validation for the single-ended sense (sa_se).
*
* Unlike test_3state.sp (which forced BL to a STATIC level), this models
* the real read sequence end to end:
*   1. precharge BL to VDD (switch closed, t < 0.95 ns)
*   2. release precharge; assert WL
*   3. the active NOR cell discharges BL through its NMOS (w=+/-1), OR
*      no cell drives it and BL stays high (w=0)
*   4. fire STROBE at a fixed delay; the sa_se latch resolves
* The bitline carries the (N-1) sibling drain+wire capacitance, matching
* cell/sky130/bitcell_v4/sim/test_harness.sp. VREF is an ideal VDD/2 here
* (real divider/replica validated separately).
*
* WEIGHT selects the case:
*   WEIGHT=1  -> active cell present, WL pulses -> BL discharges -> HIT=1
*   WEIGHT=0  -> no active cell (WL stays low) -> BL stays high -> HIT=0
* (w=-1 is symmetric to w=+1 on the other comparator; same BL behaviour.)

.param N            = 128
.param VDD_V        = 1.8
.param VREF_V       = 0.9
.param C_DRAIN_F    = 0.6e-15
.param C_WIRE_F     = 0.262e-15
.param WL_DELAY     = 1n
.param STROBE_DELAY = 3n      ; fire after BL has crossed VDD/2 at SS (t_50pct~1.74ns)
.param T_RISE       = 50p
.param WEIGHT       = 1        ; 1 = active cell, 0 = quiet (weight-0)

Vvdd  vdd 0 'VDD_V'
Vvgnd vgnd 0 0
Vvref vref 0 'VREF_V'

* WL pulse: only fires when an active cell exists (WEIGHT=1). For WEIGHT=0
* the gate stays low so the cell never conducts -> BL stays precharged.
Vwl wl 0 PULSE(0 'WEIGHT*VDD_V' 'WL_DELAY' 'T_RISE' 'T_RISE' 90n 200n)

* Active NOR cell: drain=BL, gate=WL, source=VGND (bitcell_v4 dims).
Xcell bl wl vgnd vgnd sky130_fd_pr__nfet_01v8 w=0.42 l=0.15
+   ad=0.1218 pd=1.42 as=0.1218 ps=1.42

* (N-1) sibling drain + wire capacitance lumped on BL.
Cbl bl 0 '(N-1)*(C_DRAIN_F + C_WIRE_F)'

* Precharge BL to VDD until just before WL (t > 0.95 ns releases it).
Vprech_en pre_en 0 PULSE(1 0 0.9n 1p 1p 100n 100n)
.model SWPRE sw vt=0.5 vh=0.1 ron=100 roff=1G
Spre bl vdd pre_en 0 SWPRE

* Strobe pulse for the sense latch.
Vstrobe strobe 0 PULSE(0 'VDD_V' 'STROBE_DELAY' 'T_RISE' 'T_RISE' 90n 200n)

* Device under test: single-ended comparator sensing BL vs VREF.
Xuut bl vref hit hitb strobe vdd vgnd sa_se
Chit  hit  0 5f
Chitb hitb 0 5f

.tran 5p 12n
.measure tran v_bl_at_strobe  FIND v(bl)  AT='STROBE_DELAY'
.measure tran v_hit_final     FIND v(hit) AT=11.5n
.measure tran v_hitb_final    FIND v(hitb) AT=11.5n
.print tran v(bl) v(wl) v(strobe) v(hit) v(hitb)
.end
