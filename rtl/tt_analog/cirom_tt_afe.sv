// Analog front-end contract for the Azara CiROM TinyTapeout tile, mirroring
// the signed-off chip's sense (rtl/chip/cirom_chip_analog.sv): a slice of the
// mask-programmed array plus 2*N_COLS single-ended StrongARM sense amps (one
// per bitline), all comparing against a SHARED VREF and latched by the SHARED
// STROBE -- NO mux. pos_hit[c] = BLP_c discharged (weight +1), neg_hit[c] =
// BLN_c discharged (weight -1); neither => 0. The hardened tile implements
// this; VREF routes to a tile ua analog pin. Body is empty (a blackbox).
`default_nettype none

module cirom_tt_afe #(
    parameter int N_ROWS = 64,
    parameter int N_COLS = 16
)(
    input  wire [N_ROWS-1:0] wl,
    input  wire              pre_n,
    input  wire              strobe,
    input  wire              VREF,       // shared sense reference (tile ua0)
    inout  wire              BLP_PROBE,  // column-0 BLP probe (tile ua1)
    inout  wire              BLN_PROBE,  // column-0 BLN probe (tile ua2)
    output wire [N_COLS-1:0] pos_hit,
    output wire [N_COLS-1:0] neg_hit
);
    // blackbox: array slice + 2*N_COLS single-ended SAs + shared VREF
endmodule

`default_nettype wire
