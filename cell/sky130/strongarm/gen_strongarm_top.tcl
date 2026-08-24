# Top-level StrongARM cell -- vertical device stack for a 3.40 um
# (pitch-doubled) column. NMOS at the bottom in p-substrate, PMOS at
# the top in a single merged NWELL. Each device is a scoped subcell
# (gen_strongarm_subcells.tcl) so it extracts as a distinct SPICE
# element.
#
# Devices are S-left / D-right / gate-top by construction. The "p-side"
# devices (xc_n_0, xc_p_0, rst_0 -- the ones whose drain is outp) are
# mirrored (sideways) so their drain lands on the LEFT; the "m-side"
# devices keep the default so their drain lands on the RIGHT. This
# separates the outp rail (left, x~0.6) from the outm rail (right,
# x~1.9) by ~1.3 um instead of stacking them on one side. tail is
# mirrored so tail/D (left) aligns with inp/S (left).
#   tail/D, inp_*/S            -> "tail"  net, left track
#   inp_0/D, xc_n_0/S          -> "intp"
#   inp_1/D, xc_n_1/S          -> "intm"
#   xc_n_0/D, xc_p_0/D, rst_0/D, xc_n_1/G, xc_p_1/G -> "outp" left rail
#   xc_n_1/D, xc_p_1/D, rst_1/D, xc_n_0/G, xc_p_0/G -> "outm" right rail
#   xc_*/S, rst/S              -> "vdd"   top rail
#   tail/S + all bulks         -> "vgnd"  bottom rail
#
# All devices are centered on x = 1.29 um (the half-width of the widest
# device, sa_inp). Vertical pitch leaves >= 0.9 um gaps between device
# groups for the routing rails.
#
# Run via:
#   cd build && magic -dnull -noconsole -T sky130A < ../gen_strongarm_top.tcl

drc off
load strongarm -quiet
# Start from an empty cell so re-runs do not stack geometry on a prior build.
box -1000um -1000um 1000um 1000um
select area
delete
select clear

# Helper: place subcell with lower-left at (llx, y), optionally mirrored.
proc place {name llx y flip} {
    box position ${llx}um ${y}um
    getcell $name
    select cell
    if {$flip} { sideways }
    select top cell
}

# axis x = 1.29 ; llx = 1.29 - width/2
#   tail  w1.58 -> llx 0.50   inp w2.58 -> 0.00
#   xc_n  w1.58 -> 0.50       xc_p w1.94 -> 0.32   rst w1.94 -> 0.32

# --- NMOS stack (p-substrate) ---
place sa_tail  0.50  1.5  1   ;# S=vgnd right, D=tail left, G=strobe top
place sa_inp   0.00 17.0  0   ;# S=tail left,  D=intp right, G=blp top
place sa_inp   0.00 26.5  0   ;# S=tail left,  D=intm right, G=bln top
place sa_xc_n  0.50 36.5  1   ;# (p) S=intp right, D=outp left, G=outm top
place sa_xc_n  0.50 42.0  0   ;# (m) S=intm left,  D=outm right, G=outp top

# --- PMOS stack (NWELL), ~2.4 um well gap above xc_n top (~46.57) ---
place sa_xc_p  0.32 49.0  1   ;# (p) D=outp left,  S=vdd right, G=outm top
place sa_xc_p  0.32 58.5  0   ;# (m) D=outm right, S=vdd left,  G=outp top
place sa_rst   0.32 68.0  1   ;# (p) D=outp left,  S=vdd right, G=strobe top
place sa_rst   0.32 70.5  0   ;# (m) D=outm right, S=vdd left,  G=strobe top

# --- merged NWELL over the whole PMOS region (devices x=0.32..2.26;
#     extends to 3.15 so the n-well tap at x2.55..2.95 gets its
#     diff/tap.10 0.18 enclosure). ---
box -0.3um 47.5um 3.15um 73.0um
paint nwell

drc on
drc check
drc catchup
puts "DRC=[drc list count total]"
select top cell
puts "BBOX=[box values]"

save strongarm
