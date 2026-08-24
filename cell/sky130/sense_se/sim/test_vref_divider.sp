* Concrete VREF divider + sa_se, dynamic read.
* Replaces the ideal VREF source with a real two-resistor VDD/2 divider
* (ratiometric -> tracks VDD, exact VDD/2 in DC) plus a small decap.
* Checks (a) VREF settles to VDD/2, and (b) the comparator's strobe
* kickback does not disturb VREF enough to flip the decision -- the real
* concern with a high-impedance reference.
*
* WEIGHT=1 -> active cell discharges BL -> HIT=1 ; WEIGHT=0 -> HIT=0.

.param VDD_V        = 1.8
.param C_DRAIN_F    = 0.6e-15
.param C_WIRE_F     = 0.262e-15
.param N            = 128
.param WL_DELAY     = 1n
.param STROBE_DELAY = 3n
.param T_RISE       = 50p
.param WEIGHT       = 1
.param RDIV         = 500k    ; each leg; high-Z on purpose (worst case for kickback)
.param CVREF_F      = 50f     ; VREF decoupling cap

Vvdd  vdd 0 'VDD_V'
Vvgnd vgnd 0 0

* Two-equal-resistor divider -> VREF = VDD/2 (ratiometric). High-Z legs
* to stress kickback; CVREF holds it during strobe.
R_top vdd  vref 'RDIV'
R_bot vref vgnd 'RDIV'
Cvref vref 0 'CVREF_F'

* WL + active NOR cell + BL caps + precharge (same as test_dynamic.sp)
Vwl wl 0 PULSE(0 'WEIGHT*VDD_V' 'WL_DELAY' 'T_RISE' 'T_RISE' 90n 200n)
Xcell bl wl vgnd vgnd sky130_fd_pr__nfet_01v8 w=0.42 l=0.15
+   ad=0.1218 pd=1.42 as=0.1218 ps=1.42
Cbl bl 0 '(N-1)*(C_DRAIN_F + C_WIRE_F)'
Vprech_en pre_en 0 PULSE(1 0 0.9n 1p 1p 100n 100n)
.model SWPRE sw vt=0.5 vh=0.1 ron=100 roff=1G
Spre bl vdd pre_en 0 SWPRE
Vstrobe strobe 0 PULSE(0 'VDD_V' 'STROBE_DELAY' 'T_RISE' 'T_RISE' 90n 200n)

Xuut bl vref hit hitb strobe vdd vgnd sa_se
Chit  hit  0 5f
Chitb hitb 0 5f

.tran 5p 12n
.measure tran vref_dc        FIND v(vref) AT=0.9n          ; settled pre-read
.measure tran vref_min       MIN v(vref) FROM=3n TO=4n     ; worst dip during strobe
.measure tran vref_max       MAX v(vref) FROM=3n TO=4n
.measure tran v_hit_final    FIND v(hit) AT=11.5n
.print tran v(vref) v(bl) v(strobe) v(hit)
.end
