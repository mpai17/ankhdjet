// cirom_chip_digital: the fully digital chip-level top. Same read
// contract and FSM timing as the banded chip top (start / wl_addr in,
// sa_out_pos / sa_out_neg / valid out, one row per 4-state cycle), with
// the readout swapped to full-swing bitline sampling: each BLP/BLN lands
// on a capture flop through synthesized buffers. No comparators, no VREF
// pin, no analog signoff surface; a discharged bitline reads as a hit.

`default_nettype none

`ifndef ANKHDJET_ARRAY_MODULE
`define ANKHDJET_ARRAY_MODULE macro_array_pc_64x32_checker
`endif

module cirom_chip_digital (
`ifdef USE_POWER_PINS
    inout  wire        VPWR,
    inout  wire        VGND,
`endif
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,            // pulse high to begin one row read
    input  wire [5:0]  wl_addr,          // row index 0..63
    output reg  [31:0] sa_out_pos,       // BLP discharged (w=+1)
    output reg  [31:0] sa_out_neg,       // BLN discharged (w=-1)
    output reg         valid             // pulses high in T3
);

    typedef enum logic [2:0] {
        S_IDLE,
        S_PRECHARGE,   // T0: no WL asserted, bitlines pull high
        S_EVALUATE,    // T1: WL one-hot, programmed bitline discharges
        S_STROBE,      // T2: WL held, samplers capture the bitlines
        S_HOLD         // T3: outputs settled; valid pulses next cycle
    } state_e;

    state_e state;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            valid <= 1'b0;
        end else begin
            valid <= 1'b0;
            unique case (state)
                S_IDLE:      if (start) state <= S_PRECHARGE;
                S_PRECHARGE: state <= S_EVALUATE;
                S_EVALUATE:  state <= S_STROBE;
                S_STROBE:    state <= S_HOLD;
                S_HOLD:      begin
                                 valid <= 1'b1;
                                 state <= S_IDLE;
                             end
                default:     state <= S_IDLE;
            endcase
        end
    end

    wire eval_enable  = (state == S_EVALUATE);
    wire strobe_pulse = (state == S_STROBE);
    // Active-low precharge: pull-ups ON in every state except
    // evaluate/strobe (the contract from the precharge design record).
    wire pre_n = eval_enable || strobe_pulse;

    wire [63:0] wl_dec;
    genvar i;
    generate
        for (i = 0; i < 64; i = i + 1) begin : g_wl
            assign wl_dec[i] = (wl_addr == i[5:0]) && (eval_enable || strobe_pulse);
        end
    endgenerate

    wire [31:0] blp;
    wire [31:0] bln;

`ifdef USE_POWER_PINS
    wire vpwr = VPWR;
    wire vgnd = VGND;
`endif

    `ANKHDJET_ARRAY_MODULE u_macro (
        .PRE_N(pre_n),
        .WL_0(wl_dec[0]), .WL_1(wl_dec[1]), .WL_2(wl_dec[2]), .WL_3(wl_dec[3]), .WL_4(wl_dec[4]), .WL_5(wl_dec[5]), .WL_6(wl_dec[6]), .WL_7(wl_dec[7]),
        .WL_8(wl_dec[8]), .WL_9(wl_dec[9]), .WL_10(wl_dec[10]), .WL_11(wl_dec[11]), .WL_12(wl_dec[12]), .WL_13(wl_dec[13]), .WL_14(wl_dec[14]), .WL_15(wl_dec[15]),
        .WL_16(wl_dec[16]), .WL_17(wl_dec[17]), .WL_18(wl_dec[18]), .WL_19(wl_dec[19]), .WL_20(wl_dec[20]), .WL_21(wl_dec[21]), .WL_22(wl_dec[22]), .WL_23(wl_dec[23]),
        .WL_24(wl_dec[24]), .WL_25(wl_dec[25]), .WL_26(wl_dec[26]), .WL_27(wl_dec[27]), .WL_28(wl_dec[28]), .WL_29(wl_dec[29]), .WL_30(wl_dec[30]), .WL_31(wl_dec[31]),
        .WL_32(wl_dec[32]), .WL_33(wl_dec[33]), .WL_34(wl_dec[34]), .WL_35(wl_dec[35]), .WL_36(wl_dec[36]), .WL_37(wl_dec[37]), .WL_38(wl_dec[38]), .WL_39(wl_dec[39]),
        .WL_40(wl_dec[40]), .WL_41(wl_dec[41]), .WL_42(wl_dec[42]), .WL_43(wl_dec[43]), .WL_44(wl_dec[44]), .WL_45(wl_dec[45]), .WL_46(wl_dec[46]), .WL_47(wl_dec[47]),
        .WL_48(wl_dec[48]), .WL_49(wl_dec[49]), .WL_50(wl_dec[50]), .WL_51(wl_dec[51]), .WL_52(wl_dec[52]), .WL_53(wl_dec[53]), .WL_54(wl_dec[54]), .WL_55(wl_dec[55]),
        .WL_56(wl_dec[56]), .WL_57(wl_dec[57]), .WL_58(wl_dec[58]), .WL_59(wl_dec[59]), .WL_60(wl_dec[60]), .WL_61(wl_dec[61]), .WL_62(wl_dec[62]), .WL_63(wl_dec[63]),
        .BLP_0(blp[0]), .BLP_1(blp[1]), .BLP_2(blp[2]), .BLP_3(blp[3]), .BLP_4(blp[4]), .BLP_5(blp[5]), .BLP_6(blp[6]), .BLP_7(blp[7]), .BLP_8(blp[8]), .BLP_9(blp[9]), .BLP_10(blp[10]), .BLP_11(blp[11]), .BLP_12(blp[12]), .BLP_13(blp[13]), .BLP_14(blp[14]), .BLP_15(blp[15]), .BLP_16(blp[16]), .BLP_17(blp[17]), .BLP_18(blp[18]), .BLP_19(blp[19]), .BLP_20(blp[20]), .BLP_21(blp[21]), .BLP_22(blp[22]), .BLP_23(blp[23]), .BLP_24(blp[24]), .BLP_25(blp[25]), .BLP_26(blp[26]), .BLP_27(blp[27]), .BLP_28(blp[28]), .BLP_29(blp[29]), .BLP_30(blp[30]), .BLP_31(blp[31]),
        .BLN_0(bln[0]), .BLN_1(bln[1]), .BLN_2(bln[2]), .BLN_3(bln[3]), .BLN_4(bln[4]), .BLN_5(bln[5]), .BLN_6(bln[6]), .BLN_7(bln[7]), .BLN_8(bln[8]), .BLN_9(bln[9]), .BLN_10(bln[10]), .BLN_11(bln[11]), .BLN_12(bln[12]), .BLN_13(bln[13]), .BLN_14(bln[14]), .BLN_15(bln[15]), .BLN_16(bln[16]), .BLN_17(bln[17]), .BLN_18(bln[18]), .BLN_19(bln[19]), .BLN_20(bln[20]), .BLN_21(bln[21]), .BLN_22(bln[22]), .BLN_23(bln[23]), .BLN_24(bln[24]), .BLN_25(bln[25]), .BLN_26(bln[26]), .BLN_27(bln[27]), .BLN_28(bln[28]), .BLN_29(bln[29]), .BLN_30(bln[30]), .BLN_31(bln[31])
`ifdef USE_POWER_PINS
        , .VPWR(vpwr), .VGND(vgnd)
`endif
    );

    // Full-swing sample at the end of S_STROBE: a discharged bitline is a
    // hit. The capture flops plus their synthesized input buffers ARE the
    // readout; there is nothing else between the macro and the register.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sa_out_pos <= 32'd0;
            sa_out_neg <= 32'd0;
        end else if (state == S_STROBE) begin
            sa_out_pos <= ~blp;
            sa_out_neg <= ~bln;
        end
    end

endmodule

`default_nettype wire
