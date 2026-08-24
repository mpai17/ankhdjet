// Blackbox for the VREF divider macro (cell/sky130/vref): two 180k
// res_xhigh_po legs in series, VPWR -> VREF -> VGND, tap = VDD/2.
// Passive analog -- no timing arcs; LibreLane treats it as a placed macro.
(* blackbox *)
module vref (VPWR, VREF, VGND);
    inout VPWR;
    inout VREF;
    inout VGND;
endmodule
