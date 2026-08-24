// TinyTapeout top for the Azara CiROM read demonstrator, mirroring the
// signed-off chip's full-parallel sense (no mux). Maps the tile pin contract
// to cirom_tt_ctrl + the analog front end (cirom_tt_afe: array slice + per-
// column single-ended SAs + shared VREF). One read latches all 2*N_COLS hits
// at once; they stream out as bytes on uo_out.
//
// Pin map:
//   ui_in[5:0]  row address        uo_out[7:0]  result byte (captured hits)
//   ui_in[6]    start              uio_out[2:1] result byte index
//   ui_in[7]    cfg_mode           uio_out[3]   result_valid
//   uio_in[0]   cfg_in (serial)    uio_out[4]   busy
//                                  uio_out[5]   done
//
// One file, two views via USE_POWER_PINS. The analog tile pins ua[7:0] are always
// ports (the DEF template places them); USE_POWER_PINS additionally exposes the
// VGND/VDPWR power ports and wires the AFE's power/VREF(ua0)/BLP(ua1)/BLN(ua2) --
// wired; without it (verification) it is the digital-only view (AFE blackbox/
// behavioral, digital ports only). The hardened GDS of this top = gds/tt_um_azara_cirom.gds.
`default_nettype none

module tt_um_azara_cirom (
`ifdef USE_POWER_PINS
    inout  wire       VGND,
    inout  wire       VDPWR,
    inout  wire [7:0] ua,      // analog tile pins: ua0=VREF, ua1=BLP, ua2=BLN
`else
    // Synthesis view: ua is analog and connects to nothing digital, but the
    // ua[7:0] pins MUST survive to the layout (the TT template places them).
    // An unconnected inout is dropped by synthesis, so declare it an input here
    // (an input can be read with no driver) and sink it below to force keeping.
    input  wire [7:0] ua,
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
    localparam int N_COLS = 16;

    wire [5:0] row_addr = ui_in[5:0];
    wire       start    = ui_in[6];
    wire       cfg_mode = ui_in[7];
    wire       cfg_in   = uio_in[0];

    wire [63:0]        wl;
    wire               pre_n, strobe;
    wire [N_COLS-1:0]  pos_hit, neg_hit;
    wire [7:0]         result;
    wire [1:0]         result_byte;
    wire               result_valid, busy, done;

    cirom_tt_ctrl #(.N_ROWS(64), .N_COLS(N_COLS)) u_ctrl (
        .clk(clk), .rst_n(rst_n),
        .row_addr(row_addr), .start(start),
        .cfg_mode(cfg_mode), .cfg_in(cfg_in),
        .wl(wl), .pre_n(pre_n), .strobe(strobe),
        .pos_hit(pos_hit), .neg_hit(neg_hit),
        .result(result), .result_byte(result_byte),
        .result_valid(result_valid), .busy(busy), .done(done)
    );

    // The analog SIGNAL interface (VREF/probes on ua) is part of the AFE
    // contract in every view -- hiding it under USE_POWER_PINS lets the
    // synthesis view see vref undriven and tie all 32 band VREF pins LOW
    // (dead sense amps). Only the power pins are view-dependent.
    cirom_tt_afe #(.N_ROWS(64), .N_COLS(N_COLS)) u_afe (
`ifdef USE_POWER_PINS
        .VPWR(VDPWR), .VGND(VGND),
`endif
        .VREF(ua[0]), .BLP_PROBE(ua[1]), .BLN_PROBE(ua[2]),
        .wl(wl), .pre_n(pre_n), .strobe(strobe),
        .pos_hit(pos_hit), .neg_hit(neg_hit)
    );

    assign uo_out  = result;
    assign uio_out = {2'b00, done, busy, result_valid, result_byte, 1'b0};
    assign uio_oe  = 8'b0011_1110;   // [5:1] drive status/index, [0] cfg_in input

    // ua[2:0] feed the AFE; sink the spare analog pins so synthesis keeps the
    // full ua[7:0] port (ApplyDEFTemplate places all 8 template pins).
    wire _unused = &{ena, uio_in[7:1], ua[7:3], 1'b0};
endmodule

`default_nettype wire
