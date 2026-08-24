// TinyTapeout top for Darga, the digital-tier demonstrator: the same
// mask-programmed CiROM array as the analog tile, read by clocked digital
// bitline sampling (no comparators, no VREF, no analog pins), feeding an
// on-die ternary MAC. First vehicle that computes dot products on silicon.
//
// Pin map:
//   ui_in[7:0]   activation byte while loading (two 4-bit magnitudes, low
//                nibble = even row); row address in raw-read mode (ui[5:0])
//   uio_in[0]    act_wr: write ui_in into the activation store (32 writes
//                load a 64-element vector)
//   uio_in[1]    start
//   uio_in[2]    mode: 0 = matrix-vector multiply, 1 = raw row read
//   uio_in[3]    cfg_mode   (serial config, shared scheme with analog tile)
//   uio_in[4]    cfg_in
//   uo_out[7:0]  result byte stream (MVM: all 32 columns as 2 bytes each
//                in ascending column order, low byte first; raw: 8 bytes
//                {neg_hit, pos_hit})
//   uio_out[5]   result_valid
//   uio_out[6]   busy
//   uio_out[7]   done
`default_nettype none

module tt_um_darga_cirom (
`ifdef USE_POWER_PINS
    inout  wire       VGND,
    inout  wire       VDPWR,
`endif
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    localparam int N_ROWS = 64;
    localparam int N_COLS = 32;

    wire [N_ROWS-1:0] wl;
    wire              pre_n;
    wire [N_COLS-1:0] blp, bln;
    wire              result_valid, busy, done;

    wire _unused = &{ena, uio_in[7:5], 1'b0};

    cirom_dig_ctrl #(
        .N_ROWS(N_ROWS), .N_COLS(N_COLS)
    ) u_ctrl (
        .clk(clk), .rst_n(rst_n),
        .ui(ui_in),
        .act_wr(uio_in[0]),
        .start(uio_in[1]),
        .mode(uio_in[2]),
        .cfg_mode(uio_in[3]),
        .cfg_in(uio_in[4]),
        .wl(wl), .pre_n(pre_n),
        .blp(blp), .bln(bln),
        .result(uo_out),
        .result_valid(result_valid),
        .busy(busy),
        .done(done)
    );

    cirom_dig_afe #(
        .N_ROWS(N_ROWS), .N_COLS(N_COLS)
    ) u_afe (
`ifdef USE_POWER_PINS
        .VPWR(VDPWR), .VGND(VGND),
`endif
        .wl(wl), .pre_n(pre_n),
        .blp(blp), .bln(bln)
    );

    assign uio_out = {done, busy, result_valid, 5'b0};
    assign uio_oe  = 8'b1110_0000;

endmodule

`default_nettype wire
