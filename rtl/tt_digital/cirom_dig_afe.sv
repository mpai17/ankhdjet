// Blackbox for the digital tile's hardened front end: the mask-programmed
// array macro plus its clocked precharge, exposing the raw bitlines. There
// is no comparator and no VREF; the bitlines are sampled by standard-cell
// flops in cirom_dig_ctrl. The hardened GDS implements this module. For
// simulation compile sim/cirom_dig_afe_beh.sv instead.
`default_nettype none

module cirom_dig_afe #(
    parameter int N_ROWS = 64,
    parameter int N_COLS = 32
)(
`ifdef USE_POWER_PINS
    inout  wire              VPWR,
    inout  wire              VGND,
`endif
    input  wire [N_ROWS-1:0] wl,
    input  wire              pre_n,
    output wire [N_COLS-1:0] blp,
    output wire [N_COLS-1:0] bln
);
    // blackbox: implemented by the hardened array + precharge GDS
endmodule

`default_nettype wire
