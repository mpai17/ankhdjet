// Behavioral front end for the digital tile simulation: the behavioral
// array macro with its raw bitlines exposed. There is no sense amplifier
// here; cirom_dig_ctrl samples the bitlines into flops at its SAMPLE state.
// Compile this INSTEAD of rtl/tt_digital/cirom_dig_afe.sv.
`default_nettype none

module cirom_dig_afe #(
    parameter int N_ROWS = 64,
    parameter int N_COLS = 32
)(
    input  wire [N_ROWS-1:0] wl,
    input  wire              pre_n,
    output wire [N_COLS-1:0] blp,
    output wire [N_COLS-1:0] bln
);
    wire [31:0] blp_all, bln_all;
    wire vpwr = 1'b1, vgnd = 1'b0;

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
        .BLP_0(blp_all[0]), .BLP_1(blp_all[1]), .BLP_2(blp_all[2]), .BLP_3(blp_all[3]), .BLP_4(blp_all[4]), .BLP_5(blp_all[5]), .BLP_6(blp_all[6]), .BLP_7(blp_all[7]), .BLP_8(blp_all[8]), .BLP_9(blp_all[9]), .BLP_10(blp_all[10]), .BLP_11(blp_all[11]), .BLP_12(blp_all[12]), .BLP_13(blp_all[13]), .BLP_14(blp_all[14]), .BLP_15(blp_all[15]), .BLP_16(blp_all[16]), .BLP_17(blp_all[17]), .BLP_18(blp_all[18]), .BLP_19(blp_all[19]), .BLP_20(blp_all[20]), .BLP_21(blp_all[21]), .BLP_22(blp_all[22]), .BLP_23(blp_all[23]), .BLP_24(blp_all[24]), .BLP_25(blp_all[25]), .BLP_26(blp_all[26]), .BLP_27(blp_all[27]), .BLP_28(blp_all[28]), .BLP_29(blp_all[29]), .BLP_30(blp_all[30]), .BLP_31(blp_all[31]),
        .BLN_0(bln_all[0]), .BLN_1(bln_all[1]), .BLN_2(bln_all[2]), .BLN_3(bln_all[3]), .BLN_4(bln_all[4]), .BLN_5(bln_all[5]), .BLN_6(bln_all[6]), .BLN_7(bln_all[7]), .BLN_8(bln_all[8]), .BLN_9(bln_all[9]), .BLN_10(bln_all[10]), .BLN_11(bln_all[11]), .BLN_12(bln_all[12]), .BLN_13(bln_all[13]), .BLN_14(bln_all[14]), .BLN_15(bln_all[15]), .BLN_16(bln_all[16]), .BLN_17(bln_all[17]), .BLN_18(bln_all[18]), .BLN_19(bln_all[19]), .BLN_20(bln_all[20]), .BLN_21(bln_all[21]), .BLN_22(bln_all[22]), .BLN_23(bln_all[23]), .BLN_24(bln_all[24]), .BLN_25(bln_all[25]), .BLN_26(bln_all[26]), .BLN_27(bln_all[27]), .BLN_28(bln_all[28]), .BLN_29(bln_all[29]), .BLN_30(bln_all[30]), .BLN_31(bln_all[31]),
        .VPWR(vpwr), .VGND(vgnd)
    );

    assign blp = blp_all[N_COLS-1:0];
    assign bln = bln_all[N_COLS-1:0];
endmodule

`default_nettype wire
