// Structural implementation of the cirom_tt_afe analog front-end. The tile
// hardening flow compiles this file in place of the empty blackbox view
// (rtl/tt_analog/cirom_tt_afe.sv); both declare module cirom_tt_afe.
//
// Mirrors the signed-off chip sense (rtl/chip/cirom_chip_analog.sv), reduced to
// the TT vehicle: the 64x32 mask-programmed array + 2 sa_se_band16 bands (the
// low 16 columns; BLP -> pos_hit, BLN -> neg_hit). VREF (the shared VDD/2
// reference) is an INPUT pin driven externally from the tile's ua[0] analog
// pad; there is no on-die reference. All columns
// sense against one shared VREF, latched by one shared STROBE. The
// digital controller (cirom_tt_ctrl) drives wl/pre_n/strobe and consumes
// pos_hit/neg_hit.
//
// VREF/BLP_PROBE/BLN_PROBE are exposed to the tile's ua[2:0] analog pins for
// observability. This file is read by the tile hardening flow and the AFE
// lint/synth gates; the controller synth gate reads the same-named blackbox
// instead.
`default_nettype none

`ifndef ANKHDJET_ARRAY_MODULE
`define ANKHDJET_ARRAY_MODULE macro_array_pc_64x32_test0
`endif

module cirom_tt_afe #(
    parameter int N_ROWS = 64,
    parameter int N_COLS = 16
)(
`ifdef USE_POWER_PINS
    inout  wire              VPWR,        // analog 1.8V (tile VDPWR)
    inout  wire              VGND,        // tile ground
`endif
    input  wire [N_ROWS-1:0] wl,          // one-hot wordline from the controller
    input  wire              pre_n,        // active-low precharge
    input  wire              strobe,       // shared sense strobe
    input  wire              VREF,         // shared VDD/2 sense ref from the tile vref divider; also ua0
    inout  wire              BLP_PROBE,    // column-0 BLP -> ua1
    inout  wire              BLN_PROBE,    // column-0 BLN -> ua2
    output wire [N_COLS-1:0] pos_hit,      // BLP_c discharged (weight +1)
    output wire [N_COLS-1:0] neg_hit       // BLN_c discharged (weight -1)
);
    // The array exposes 32 ternary columns; the TT vehicle wires the low 16 to
    // the two sense bands. blp[31:16]/bln[31:16] are intentionally left
    // unsensed (dangling) on this vehicle.
    wire [31:0] blp;
    wire [31:0] bln;
    wire        vref_net;   // alias of the VREF input pin (shared sense reference)

    assign vref_net  = VREF;
    assign BLP_PROBE = blp[0];
    assign BLN_PROBE = bln[0];

    // VREF is the shared VDD/2 reference, an INPUT driven externally through
    // the tile's ua0 analog pin (no on-die reference; an on-die divider
    // design is recorded in the VREF design doc). The bands sense each
    // bitline against vref_net.

    // Hard macro: 64x32 NOR array + per-column precharge. Power nets bind to
    // the tile rails during PnR (PDN_MACRO_CONNECTIONS); BLP/BLN ordering
    // matches the bb.v auto-generated pin list.
    `ANKHDJET_ARRAY_MODULE u_macro (
        .PRE_N(pre_n),
        .WL_0(wl[0]),   .WL_1(wl[1]),   .WL_2(wl[2]),   .WL_3(wl[3]),
        .WL_4(wl[4]),   .WL_5(wl[5]),   .WL_6(wl[6]),   .WL_7(wl[7]),
        .WL_8(wl[8]),   .WL_9(wl[9]),   .WL_10(wl[10]), .WL_11(wl[11]),
        .WL_12(wl[12]), .WL_13(wl[13]), .WL_14(wl[14]), .WL_15(wl[15]),
        .WL_16(wl[16]), .WL_17(wl[17]), .WL_18(wl[18]), .WL_19(wl[19]),
        .WL_20(wl[20]), .WL_21(wl[21]), .WL_22(wl[22]), .WL_23(wl[23]),
        .WL_24(wl[24]), .WL_25(wl[25]), .WL_26(wl[26]), .WL_27(wl[27]),
        .WL_28(wl[28]), .WL_29(wl[29]), .WL_30(wl[30]), .WL_31(wl[31]),
        .WL_32(wl[32]), .WL_33(wl[33]), .WL_34(wl[34]), .WL_35(wl[35]),
        .WL_36(wl[36]), .WL_37(wl[37]), .WL_38(wl[38]), .WL_39(wl[39]),
        .WL_40(wl[40]), .WL_41(wl[41]), .WL_42(wl[42]), .WL_43(wl[43]),
        .WL_44(wl[44]), .WL_45(wl[45]), .WL_46(wl[46]), .WL_47(wl[47]),
        .WL_48(wl[48]), .WL_49(wl[49]), .WL_50(wl[50]), .WL_51(wl[51]),
        .WL_52(wl[52]), .WL_53(wl[53]), .WL_54(wl[54]), .WL_55(wl[55]),
        .WL_56(wl[56]), .WL_57(wl[57]), .WL_58(wl[58]), .WL_59(wl[59]),
        .WL_60(wl[60]), .WL_61(wl[61]), .WL_62(wl[62]), .WL_63(wl[63]),
        .BLP_0(blp[0]),   .BLN_0(bln[0]),   .BLP_1(blp[1]),   .BLN_1(bln[1]),
        .BLP_2(blp[2]),   .BLN_2(bln[2]),   .BLP_3(blp[3]),   .BLN_3(bln[3]),
        .BLP_4(blp[4]),   .BLN_4(bln[4]),   .BLP_5(blp[5]),   .BLN_5(bln[5]),
        .BLP_6(blp[6]),   .BLN_6(bln[6]),   .BLP_7(blp[7]),   .BLN_7(bln[7]),
        .BLP_8(blp[8]),   .BLN_8(bln[8]),   .BLP_9(blp[9]),   .BLN_9(bln[9]),
        .BLP_10(blp[10]), .BLN_10(bln[10]), .BLP_11(blp[11]), .BLN_11(bln[11]),
        .BLP_12(blp[12]), .BLN_12(bln[12]), .BLP_13(blp[13]), .BLN_13(bln[13]),
        .BLP_14(blp[14]), .BLN_14(bln[14]), .BLP_15(blp[15]), .BLN_15(bln[15]),
        .BLP_16(blp[16]), .BLN_16(bln[16]), .BLP_17(blp[17]), .BLN_17(bln[17]),
        .BLP_18(blp[18]), .BLN_18(bln[18]), .BLP_19(blp[19]), .BLN_19(bln[19]),
        .BLP_20(blp[20]), .BLN_20(bln[20]), .BLP_21(blp[21]), .BLN_21(bln[21]),
        .BLP_22(blp[22]), .BLN_22(bln[22]), .BLP_23(blp[23]), .BLN_23(bln[23]),
        .BLP_24(blp[24]), .BLN_24(bln[24]), .BLP_25(blp[25]), .BLN_25(bln[25]),
        .BLP_26(blp[26]), .BLN_26(bln[26]), .BLP_27(blp[27]), .BLN_27(bln[27]),
        .BLP_28(blp[28]), .BLN_28(bln[28]), .BLP_29(blp[29]), .BLN_29(bln[29]),
        .BLP_30(blp[30]), .BLN_30(bln[30]), .BLP_31(blp[31]), .BLN_31(bln[31])
`ifdef USE_POWER_PINS
        , .VPWR(VPWR), .VGND(VGND)
`endif
    );

    // Per-HIT buffer: keep the band output pin < 60 fF (the StrongARM
    // output-load-imbalance cliff is 150 fF; the unbuffered band-to-pin route
    // would exceed it). Mirrors the signed-off chip; hand-placed in the config.
    wire [N_COLS-1:0] hit_pos;
    wire [N_COLS-1:0] hit_neg;
    generate
        for (genvar gi = 0; gi < N_COLS; gi = gi + 1) begin : g_hitbuf
`ifdef ANKHDJET_SYNTH
            (* keep *) sky130_fd_sc_hd__buf_4 u_bp (.A(hit_pos[gi]), .X(pos_hit[gi]));
            (* keep *) sky130_fd_sc_hd__buf_4 u_bn (.A(hit_neg[gi]), .X(neg_hit[gi]));
`else
            assign pos_hit[gi] = hit_pos[gi];
            assign neg_hit[gi] = hit_neg[gi];
`endif
        end
    endgenerate

    // Shared STROBE spine: one strong RTL driver for all 32 SA strobe pins
    // (~0.5 pF of met3 strip). Instantiated here -- with the net dont-touched
    // in the config -- so the resizer never splits the strobe into per-pin
    // max-cap buffer legs, whose far-away placement forces routing through the
    // band's met3 pin jungle.
    wire strobe_drv;
`ifdef ANKHDJET_SYNTH
    (* keep *) sky130_fd_sc_hd__buf_16 u_strobe_buf (.A(strobe), .X(strobe_drv));
`else
    assign strobe_drv = strobe;
`endif

    // BLP band -> pos_hit (16 columns). Each SA senses BLP_c < VREF, latched by
    // the shared STROBE; HITB is unused (single-ended).
    sa_se_band16 u_band_p (
        .BL_0(blp[0]),   .VREF_0(vref_net),  .STROBE_0(strobe_drv),  .HIT_0(hit_pos[0]),
        .BL_1(blp[1]),   .VREF_1(vref_net),  .STROBE_1(strobe_drv),  .HIT_1(hit_pos[1]),
        .BL_2(blp[2]),   .VREF_2(vref_net),  .STROBE_2(strobe_drv),  .HIT_2(hit_pos[2]),
        .BL_3(blp[3]),   .VREF_3(vref_net),  .STROBE_3(strobe_drv),  .HIT_3(hit_pos[3]),
        .BL_4(blp[4]),   .VREF_4(vref_net),  .STROBE_4(strobe_drv),  .HIT_4(hit_pos[4]),
        .BL_5(blp[5]),   .VREF_5(vref_net),  .STROBE_5(strobe_drv),  .HIT_5(hit_pos[5]),
        .BL_6(blp[6]),   .VREF_6(vref_net),  .STROBE_6(strobe_drv),  .HIT_6(hit_pos[6]),
        .BL_7(blp[7]),   .VREF_7(vref_net),  .STROBE_7(strobe_drv),  .HIT_7(hit_pos[7]),
        .BL_8(blp[8]),   .VREF_8(vref_net),  .STROBE_8(strobe_drv),  .HIT_8(hit_pos[8]),
        .BL_9(blp[9]),   .VREF_9(vref_net),  .STROBE_9(strobe_drv),  .HIT_9(hit_pos[9]),
        .BL_10(blp[10]), .VREF_10(vref_net), .STROBE_10(strobe_drv), .HIT_10(hit_pos[10]),
        .BL_11(blp[11]), .VREF_11(vref_net), .STROBE_11(strobe_drv), .HIT_11(hit_pos[11]),
        .BL_12(blp[12]), .VREF_12(vref_net), .STROBE_12(strobe_drv), .HIT_12(hit_pos[12]),
        .BL_13(blp[13]), .VREF_13(vref_net), .STROBE_13(strobe_drv), .HIT_13(hit_pos[13]),
        .BL_14(blp[14]), .VREF_14(vref_net), .STROBE_14(strobe_drv), .HIT_14(hit_pos[14]),
        .BL_15(blp[15]), .VREF_15(vref_net), .STROBE_15(strobe_drv), .HIT_15(hit_pos[15])
`ifdef USE_POWER_PINS
        , .VDD(VPWR), .VGND(VGND)
`endif
    );

    // BLN band -> neg_hit (16 columns).
    sa_se_band16 u_band_n (
        .BL_0(bln[0]),   .VREF_0(vref_net),  .STROBE_0(strobe_drv),  .HIT_0(hit_neg[0]),
        .BL_1(bln[1]),   .VREF_1(vref_net),  .STROBE_1(strobe_drv),  .HIT_1(hit_neg[1]),
        .BL_2(bln[2]),   .VREF_2(vref_net),  .STROBE_2(strobe_drv),  .HIT_2(hit_neg[2]),
        .BL_3(bln[3]),   .VREF_3(vref_net),  .STROBE_3(strobe_drv),  .HIT_3(hit_neg[3]),
        .BL_4(bln[4]),   .VREF_4(vref_net),  .STROBE_4(strobe_drv),  .HIT_4(hit_neg[4]),
        .BL_5(bln[5]),   .VREF_5(vref_net),  .STROBE_5(strobe_drv),  .HIT_5(hit_neg[5]),
        .BL_6(bln[6]),   .VREF_6(vref_net),  .STROBE_6(strobe_drv),  .HIT_6(hit_neg[6]),
        .BL_7(bln[7]),   .VREF_7(vref_net),  .STROBE_7(strobe_drv),  .HIT_7(hit_neg[7]),
        .BL_8(bln[8]),   .VREF_8(vref_net),  .STROBE_8(strobe_drv),  .HIT_8(hit_neg[8]),
        .BL_9(bln[9]),   .VREF_9(vref_net),  .STROBE_9(strobe_drv),  .HIT_9(hit_neg[9]),
        .BL_10(bln[10]), .VREF_10(vref_net), .STROBE_10(strobe_drv), .HIT_10(hit_neg[10]),
        .BL_11(bln[11]), .VREF_11(vref_net), .STROBE_11(strobe_drv), .HIT_11(hit_neg[11]),
        .BL_12(bln[12]), .VREF_12(vref_net), .STROBE_12(strobe_drv), .HIT_12(hit_neg[12]),
        .BL_13(bln[13]), .VREF_13(vref_net), .STROBE_13(strobe_drv), .HIT_13(hit_neg[13]),
        .BL_14(bln[14]), .VREF_14(vref_net), .STROBE_14(strobe_drv), .HIT_14(hit_neg[14]),
        .BL_15(bln[15]), .VREF_15(vref_net), .STROBE_15(strobe_drv), .HIT_15(hit_neg[15])
`ifdef USE_POWER_PINS
        , .VDD(VPWR), .VGND(VGND)
`endif
    );

endmodule

`default_nettype wire
