* 3-state read validation for the single-ended sense column.
* Drives one comparator (sa_se) with BL at the three per-cell levels and
* checks HIT decodes correctly. The runner sweeps which level via VBL_V:
*   VBL_V = 0.0  -> BL fully discharged (cell drove it)  -> HIT=1
*   VBL_V = VDD  -> BL stayed precharged (quiet)          -> HIT=0
* VREF = VDD/2. The weight=0 case is "both BLs quiet" = HIT=0 on both
* comparators -> (pos,neg)=(0,0), which the differential SA could not do.
*
* The runner prepends .lib + .include sense_col_schematic.spice.

.param VDD_V   = 1.8
.param VREF_V  = 0.9
.param VBL_V   = 0.0
.param STROBE_DELAY = 1n
.param T_RISE  = 50p

Vvdd  vdd 0 'VDD_V'
Vvgnd vgnd 0 0
Vvref vref 0 'VREF_V'
Vbl   bl  0 'VBL_V'
Vstrobe strobe 0 PULSE(0 'VDD_V' 'STROBE_DELAY' 'T_RISE' 'T_RISE' 90n 200n)

Xuut bl vref hit hitb strobe vdd vgnd sa_se
Chit  hit  0 5f
Chitb hitb 0 5f

.tran 5p 10n
.measure tran v_hit_final  FIND v(hit)  AT=9.5n
.measure tran v_hitb_final FIND v(hitb) AT=9.5n
.print tran v(hit) v(hitb) v(bl) v(vref) v(strobe)
.end
