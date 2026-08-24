// Behavioral analog front end for tt_um_azara_cirom simulation, mirroring the
// signed-off sense: the behavioral array macro + 2*N_COLS single-ended SAs
// (one per bitline), all latched by the shared STROBE -- NO mux. Faithful to
// sa_se_band16_beh: hit = ~BL captured at the STROBE rising edge. pos_hit[c]
// = BLP_c discharged (+1), neg_hit[c] = BLN_c discharged (-1). Compile this
// INSTEAD of rtl/tt_analog/cirom_tt_afe.sv.
`default_nettype none

module cirom_tt_afe #(
    parameter int N_ROWS = 64,
    parameter int N_COLS = 16
)(
    input  wire [N_ROWS-1:0] wl,
    input  wire              pre_n,
    input  wire              strobe,
    input  wire              VREF,       // analog-only (tile ua0); unused behaviorally
    inout  wire              BLP_PROBE,  // analog-only (tile ua1); unused behaviorally
    inout  wire              BLN_PROBE,  // analog-only (tile ua2); unused behaviorally
    output wire [N_COLS-1:0] pos_hit,
    output wire [N_COLS-1:0] neg_hit
);
    wire [31:0] blp, bln;
    wire vpwr = 1'b1, vgnd = 1'b0;
    wire _unused_analog = &{VREF, 1'b0};

    macro_array_pc_64x32_checker u_macro (
        .PRE_N(pre_n),
        .WL_0(wl[0]),
        .WL_1(wl[1]),
        .WL_2(wl[2]),
        .WL_3(wl[3]),
        .WL_4(wl[4]),
        .WL_5(wl[5]),
        .WL_6(wl[6]),
        .WL_7(wl[7]),
        .WL_8(wl[8]),
        .WL_9(wl[9]),
        .WL_10(wl[10]),
        .WL_11(wl[11]),
        .WL_12(wl[12]),
        .WL_13(wl[13]),
        .WL_14(wl[14]),
        .WL_15(wl[15]),
        .WL_16(wl[16]),
        .WL_17(wl[17]),
        .WL_18(wl[18]),
        .WL_19(wl[19]),
        .WL_20(wl[20]),
        .WL_21(wl[21]),
        .WL_22(wl[22]),
        .WL_23(wl[23]),
        .WL_24(wl[24]),
        .WL_25(wl[25]),
        .WL_26(wl[26]),
        .WL_27(wl[27]),
        .WL_28(wl[28]),
        .WL_29(wl[29]),
        .WL_30(wl[30]),
        .WL_31(wl[31]),
        .WL_32(wl[32]),
        .WL_33(wl[33]),
        .WL_34(wl[34]),
        .WL_35(wl[35]),
        .WL_36(wl[36]),
        .WL_37(wl[37]),
        .WL_38(wl[38]),
        .WL_39(wl[39]),
        .WL_40(wl[40]),
        .WL_41(wl[41]),
        .WL_42(wl[42]),
        .WL_43(wl[43]),
        .WL_44(wl[44]),
        .WL_45(wl[45]),
        .WL_46(wl[46]),
        .WL_47(wl[47]),
        .WL_48(wl[48]),
        .WL_49(wl[49]),
        .WL_50(wl[50]),
        .WL_51(wl[51]),
        .WL_52(wl[52]),
        .WL_53(wl[53]),
        .WL_54(wl[54]),
        .WL_55(wl[55]),
        .WL_56(wl[56]),
        .WL_57(wl[57]),
        .WL_58(wl[58]),
        .WL_59(wl[59]),
        .WL_60(wl[60]),
        .WL_61(wl[61]),
        .WL_62(wl[62]),
        .WL_63(wl[63]),
        .BLP_0(blp[0]), .BLP_1(blp[1]), .BLP_2(blp[2]), .BLP_3(blp[3]), .BLP_4(blp[4]), .BLP_5(blp[5]), .BLP_6(blp[6]), .BLP_7(blp[7]), .BLP_8(blp[8]), .BLP_9(blp[9]), .BLP_10(blp[10]), .BLP_11(blp[11]), .BLP_12(blp[12]), .BLP_13(blp[13]), .BLP_14(blp[14]), .BLP_15(blp[15]), .BLP_16(blp[16]), .BLP_17(blp[17]), .BLP_18(blp[18]), .BLP_19(blp[19]), .BLP_20(blp[20]), .BLP_21(blp[21]), .BLP_22(blp[22]), .BLP_23(blp[23]), .BLP_24(blp[24]), .BLP_25(blp[25]), .BLP_26(blp[26]), .BLP_27(blp[27]), .BLP_28(blp[28]), .BLP_29(blp[29]), .BLP_30(blp[30]), .BLP_31(blp[31]),
        .BLN_0(bln[0]), .BLN_1(bln[1]), .BLN_2(bln[2]), .BLN_3(bln[3]), .BLN_4(bln[4]), .BLN_5(bln[5]), .BLN_6(bln[6]), .BLN_7(bln[7]), .BLN_8(bln[8]), .BLN_9(bln[9]), .BLN_10(bln[10]), .BLN_11(bln[11]), .BLN_12(bln[12]), .BLN_13(bln[13]), .BLN_14(bln[14]), .BLN_15(bln[15]), .BLN_16(bln[16]), .BLN_17(bln[17]), .BLN_18(bln[18]), .BLN_19(bln[19]), .BLN_20(bln[20]), .BLN_21(bln[21]), .BLN_22(bln[22]), .BLN_23(bln[23]), .BLN_24(bln[24]), .BLN_25(bln[25]), .BLN_26(bln[26]), .BLN_27(bln[27]), .BLN_28(bln[28]), .BLN_29(bln[29]), .BLN_30(bln[30]), .BLN_31(bln[31]),
        .VPWR(vpwr), .VGND(vgnd)
    );

    // per-column single-ended SAs, latched at the shared strobe rising edge
    logic [N_COLS-1:0] qpos, qneg;
    always_ff @(posedge strobe) begin
        qpos <= ~blp[N_COLS-1:0];
        qneg <= ~bln[N_COLS-1:0];
    end
    assign pos_hit = strobe ? qpos : '0;
    assign neg_hit = strobe ? qneg : '0;
endmodule

`default_nettype wire
