// cirom_chip_analog: structural chip-level top wrapping the analog hard macros
// (one 64x32 mask-programmed NOR array + 64 single-ended sense amps, two
// per column) with a small RTL controller that runs the precharge/
// evaluate/strobe cycle and exposes the sense outputs to chip pins.
//
// Cycle (one row read):
//   T0  precharge:  start=1, wl=0, strobe=0  -> macro precharges all BLs
//   T1  evaluate:   start=0, wl=one-hot,     -> selected NMOS discharges its BL
//   T2  strobe:     start=0, wl=one-hot,     -> each sa_se latches BL<VREF
//   T3  hold:       valid=1                  -> sa_out_pos / sa_out_neg stable
//
// Two sa_se comparators per column share STROBE and VREF. Each senses one
// bit-line against VREF ("did this BL discharge?"), so POS_HIT/NEG_HIT
// independently encode the ternary read (+1/-1/0). Popcount, scale,
// activation, and shift-accumulate all live outside this top -- this is
// the silicon slice that gets hard-macro placed by LibreLane.

`default_nettype none

// The mask-programmed array variant. The default is the checker test
// pattern; weight builds override this (and the matching .memh views)
// from the flow config / simulation runner.
`ifndef ANKHDJET_ARRAY_MODULE
`define ANKHDJET_ARRAY_MODULE macro_array_pc_64x32_checker
`endif

module cirom_chip_analog (
`ifdef USE_POWER_PINS
    inout  wire        VPWR,             // chip power rail
    inout  wire        VGND,             // chip ground rail
`endif
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,            // pulse high to begin one row read
    input  wire [5:0]  wl_addr,          // row index 0..63
    input  wire        vref,             // ~VDD/2 sense reference ("did BL discharge?")
    output reg  [31:0] sa_out_pos,       // POS_HIT per column: BLP discharged (w=+1)
    output reg  [31:0] sa_out_neg,       // NEG_HIT per column: BLN discharged (w=-1)
    output reg         valid             // pulses high in T3
);

    // Read FSM, one state per cycle of the read protocol. The bitlines
    // precharge whenever no WL is asserted (the macro's pull-ups), so
    // S_PRECHARGE simply guarantees a WL-free cycle; S_HOLD gives the
    // sense latches a settled cycle before valid pulses.
    typedef enum logic [2:0] {
        S_IDLE,        // waiting for start
        S_PRECHARGE,   // T0: no WL asserted, bitlines pull high
        S_EVALUATE,    // T1: WL one-hot, programmed bitline discharges
        S_STROBE,      // T2: WL held, sense amps latch BL < VREF
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
    // Active-low precharge: the macro's pull-up pair per column is ON
    // (bitlines parked high) in every state except evaluate/strobe --
    // the contract from docs/precharge_design.md.
    wire pre_n = eval_enable || strobe_pulse;

    // 6 -> 64 one-hot WL decoder. Only asserted during eval + strobe so the
    // BLs precharge cleanly in T0.
    wire [63:0] wl_dec;
    genvar i;
    generate
        for (i = 0; i < 64; i = i + 1) begin : g_wl
            assign wl_dec[i] = (wl_addr == i[5:0]) && (eval_enable || strobe_pulse);
        end
    endgenerate

    // BLP/BLN nets between the macro and the 32 SAs.
    wire [31:0] blp;
    wire [31:0] bln;

    // Raw sense outputs. The sa_se StrongARM resets HIT/HITB high while
    // STROBE is low, so the hits are only valid during S_STROBE: capture
    // them on the clock edge that ends S_STROBE (strobe is still high at
    // that edge; it falls a clock-to-Q later) and present the registered
    // copy with valid.
    wire [31:0] hit_pos;
    wire [31:0] hit_neg;

    // Kept buffer per HIT net: the band pin must see < 60 fF (the
    // measured StrongARM output-load-imbalance cliff is 150 fF; the
    // unbuffered band-to-core route reached ~105 fF, and the resizer
    // cannot repair macro-pin nets it underestimates). The buffer
    // splits the route and its input cap restores HIT/HITB balance.
    wire [31:0] hit_pos_b;
    wire [31:0] hit_neg_b;
    generate
        for (genvar gi = 0; gi < 32; gi = gi + 1) begin : g_hitbuf
`ifdef ANKHDJET_SYNTH
            (* keep *) sky130_fd_sc_hd__buf_4 u_bp (.A(hit_pos[gi]), .X(hit_pos_b[gi]));
            (* keep *) sky130_fd_sc_hd__buf_4 u_bn (.A(hit_neg[gi]), .X(hit_neg_b[gi]));
`else
            assign hit_pos_b[gi] = hit_pos[gi];
            assign hit_neg_b[gi] = hit_neg[gi];
`endif
        end
    endgenerate

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sa_out_pos <= 32'd0;
            sa_out_neg <= 32'd0;
        end else if (state == S_STROBE) begin
            sa_out_pos <= hit_pos_b;
            sa_out_neg <= hit_neg_b;
        end
    end

    // Hard macro: 64x32 NOR array + per-column precharge.
    // Power nets VPWR/VGND are not RTL signals -- LibreLane's PDN step
    // wires them via the standard cell library's power pins
    // (SCL_POWER_PINS / SCL_GROUND_PINS). The macro pg_pin connections
    // below leave the named nets undriven in RTL; they get tied to the
    // chip's VPWR/VGND rails during PnR.
    // Note: BLP/BLN ordering must match the bb.v auto-generated pin list.
    `ANKHDJET_ARRAY_MODULE u_macro (
        .PRE_N(pre_n),
        .WL_0(wl_dec[0]),   .WL_1(wl_dec[1]),   .WL_2(wl_dec[2]),   .WL_3(wl_dec[3]),
        .WL_4(wl_dec[4]),   .WL_5(wl_dec[5]),   .WL_6(wl_dec[6]),   .WL_7(wl_dec[7]),
        .WL_8(wl_dec[8]),   .WL_9(wl_dec[9]),   .WL_10(wl_dec[10]), .WL_11(wl_dec[11]),
        .WL_12(wl_dec[12]), .WL_13(wl_dec[13]), .WL_14(wl_dec[14]), .WL_15(wl_dec[15]),
        .WL_16(wl_dec[16]), .WL_17(wl_dec[17]), .WL_18(wl_dec[18]), .WL_19(wl_dec[19]),
        .WL_20(wl_dec[20]), .WL_21(wl_dec[21]), .WL_22(wl_dec[22]), .WL_23(wl_dec[23]),
        .WL_24(wl_dec[24]), .WL_25(wl_dec[25]), .WL_26(wl_dec[26]), .WL_27(wl_dec[27]),
        .WL_28(wl_dec[28]), .WL_29(wl_dec[29]), .WL_30(wl_dec[30]), .WL_31(wl_dec[31]),
        .WL_32(wl_dec[32]), .WL_33(wl_dec[33]), .WL_34(wl_dec[34]), .WL_35(wl_dec[35]),
        .WL_36(wl_dec[36]), .WL_37(wl_dec[37]), .WL_38(wl_dec[38]), .WL_39(wl_dec[39]),
        .WL_40(wl_dec[40]), .WL_41(wl_dec[41]), .WL_42(wl_dec[42]), .WL_43(wl_dec[43]),
        .WL_44(wl_dec[44]), .WL_45(wl_dec[45]), .WL_46(wl_dec[46]), .WL_47(wl_dec[47]),
        .WL_48(wl_dec[48]), .WL_49(wl_dec[49]), .WL_50(wl_dec[50]), .WL_51(wl_dec[51]),
        .WL_52(wl_dec[52]), .WL_53(wl_dec[53]), .WL_54(wl_dec[54]), .WL_55(wl_dec[55]),
        .WL_56(wl_dec[56]), .WL_57(wl_dec[57]), .WL_58(wl_dec[58]), .WL_59(wl_dec[59]),
        .WL_60(wl_dec[60]), .WL_61(wl_dec[61]), .WL_62(wl_dec[62]), .WL_63(wl_dec[63]),
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

    // Single-ended sense: 4 abutted 16-cell bands replace the 64 discrete
    // sa_se cells. Two bands sense the BLP columns (w=+1), two the BLN (w=-1);
    // each band's VDD(met4)/VGND(met4) bind to the chip PDN, and its narrow
    // vertical signal pins + merged nwell avoid the discrete design's VGND<->VPWR
    // extraction fuse. HITB is unused (single-ended). VREF/STROBE shared per the
    // sense scheme (all columns sense against one VREF, latched by one STROBE).
    sa_se_band16 u_band_p_lo (
        .BL_0(blp[0]),
        .VREF_0(vref),
        .STROBE_0(strobe_pulse),
        .HIT_0(hit_pos[0]),
        .BL_1(blp[1]),
        .VREF_1(vref),
        .STROBE_1(strobe_pulse),
        .HIT_1(hit_pos[1]),
        .BL_2(blp[2]),
        .VREF_2(vref),
        .STROBE_2(strobe_pulse),
        .HIT_2(hit_pos[2]),
        .BL_3(blp[3]),
        .VREF_3(vref),
        .STROBE_3(strobe_pulse),
        .HIT_3(hit_pos[3]),
        .BL_4(blp[4]),
        .VREF_4(vref),
        .STROBE_4(strobe_pulse),
        .HIT_4(hit_pos[4]),
        .BL_5(blp[5]),
        .VREF_5(vref),
        .STROBE_5(strobe_pulse),
        .HIT_5(hit_pos[5]),
        .BL_6(blp[6]),
        .VREF_6(vref),
        .STROBE_6(strobe_pulse),
        .HIT_6(hit_pos[6]),
        .BL_7(blp[7]),
        .VREF_7(vref),
        .STROBE_7(strobe_pulse),
        .HIT_7(hit_pos[7]),
        .BL_8(blp[8]),
        .VREF_8(vref),
        .STROBE_8(strobe_pulse),
        .HIT_8(hit_pos[8]),
        .BL_9(blp[9]),
        .VREF_9(vref),
        .STROBE_9(strobe_pulse),
        .HIT_9(hit_pos[9]),
        .BL_10(blp[10]),
        .VREF_10(vref),
        .STROBE_10(strobe_pulse),
        .HIT_10(hit_pos[10]),
        .BL_11(blp[11]),
        .VREF_11(vref),
        .STROBE_11(strobe_pulse),
        .HIT_11(hit_pos[11]),
        .BL_12(blp[12]),
        .VREF_12(vref),
        .STROBE_12(strobe_pulse),
        .HIT_12(hit_pos[12]),
        .BL_13(blp[13]),
        .VREF_13(vref),
        .STROBE_13(strobe_pulse),
        .HIT_13(hit_pos[13]),
        .BL_14(blp[14]),
        .VREF_14(vref),
        .STROBE_14(strobe_pulse),
        .HIT_14(hit_pos[14]),
        .BL_15(blp[15]),
        .VREF_15(vref),
        .STROBE_15(strobe_pulse),
        .HIT_15(hit_pos[15])
`ifdef USE_POWER_PINS
        , .VDD(VPWR), .VGND(VGND)
`endif
    );
    sa_se_band16 u_band_p_hi (
        .BL_0(blp[16]),
        .VREF_0(vref),
        .STROBE_0(strobe_pulse),
        .HIT_0(hit_pos[16]),
        .BL_1(blp[17]),
        .VREF_1(vref),
        .STROBE_1(strobe_pulse),
        .HIT_1(hit_pos[17]),
        .BL_2(blp[18]),
        .VREF_2(vref),
        .STROBE_2(strobe_pulse),
        .HIT_2(hit_pos[18]),
        .BL_3(blp[19]),
        .VREF_3(vref),
        .STROBE_3(strobe_pulse),
        .HIT_3(hit_pos[19]),
        .BL_4(blp[20]),
        .VREF_4(vref),
        .STROBE_4(strobe_pulse),
        .HIT_4(hit_pos[20]),
        .BL_5(blp[21]),
        .VREF_5(vref),
        .STROBE_5(strobe_pulse),
        .HIT_5(hit_pos[21]),
        .BL_6(blp[22]),
        .VREF_6(vref),
        .STROBE_6(strobe_pulse),
        .HIT_6(hit_pos[22]),
        .BL_7(blp[23]),
        .VREF_7(vref),
        .STROBE_7(strobe_pulse),
        .HIT_7(hit_pos[23]),
        .BL_8(blp[24]),
        .VREF_8(vref),
        .STROBE_8(strobe_pulse),
        .HIT_8(hit_pos[24]),
        .BL_9(blp[25]),
        .VREF_9(vref),
        .STROBE_9(strobe_pulse),
        .HIT_9(hit_pos[25]),
        .BL_10(blp[26]),
        .VREF_10(vref),
        .STROBE_10(strobe_pulse),
        .HIT_10(hit_pos[26]),
        .BL_11(blp[27]),
        .VREF_11(vref),
        .STROBE_11(strobe_pulse),
        .HIT_11(hit_pos[27]),
        .BL_12(blp[28]),
        .VREF_12(vref),
        .STROBE_12(strobe_pulse),
        .HIT_12(hit_pos[28]),
        .BL_13(blp[29]),
        .VREF_13(vref),
        .STROBE_13(strobe_pulse),
        .HIT_13(hit_pos[29]),
        .BL_14(blp[30]),
        .VREF_14(vref),
        .STROBE_14(strobe_pulse),
        .HIT_14(hit_pos[30]),
        .BL_15(blp[31]),
        .VREF_15(vref),
        .STROBE_15(strobe_pulse),
        .HIT_15(hit_pos[31])
`ifdef USE_POWER_PINS
        , .VDD(VPWR), .VGND(VGND)
`endif
    );
    sa_se_band16 u_band_n_lo (
        .BL_0(bln[0]),
        .VREF_0(vref),
        .STROBE_0(strobe_pulse),
        .HIT_0(hit_neg[0]),
        .BL_1(bln[1]),
        .VREF_1(vref),
        .STROBE_1(strobe_pulse),
        .HIT_1(hit_neg[1]),
        .BL_2(bln[2]),
        .VREF_2(vref),
        .STROBE_2(strobe_pulse),
        .HIT_2(hit_neg[2]),
        .BL_3(bln[3]),
        .VREF_3(vref),
        .STROBE_3(strobe_pulse),
        .HIT_3(hit_neg[3]),
        .BL_4(bln[4]),
        .VREF_4(vref),
        .STROBE_4(strobe_pulse),
        .HIT_4(hit_neg[4]),
        .BL_5(bln[5]),
        .VREF_5(vref),
        .STROBE_5(strobe_pulse),
        .HIT_5(hit_neg[5]),
        .BL_6(bln[6]),
        .VREF_6(vref),
        .STROBE_6(strobe_pulse),
        .HIT_6(hit_neg[6]),
        .BL_7(bln[7]),
        .VREF_7(vref),
        .STROBE_7(strobe_pulse),
        .HIT_7(hit_neg[7]),
        .BL_8(bln[8]),
        .VREF_8(vref),
        .STROBE_8(strobe_pulse),
        .HIT_8(hit_neg[8]),
        .BL_9(bln[9]),
        .VREF_9(vref),
        .STROBE_9(strobe_pulse),
        .HIT_9(hit_neg[9]),
        .BL_10(bln[10]),
        .VREF_10(vref),
        .STROBE_10(strobe_pulse),
        .HIT_10(hit_neg[10]),
        .BL_11(bln[11]),
        .VREF_11(vref),
        .STROBE_11(strobe_pulse),
        .HIT_11(hit_neg[11]),
        .BL_12(bln[12]),
        .VREF_12(vref),
        .STROBE_12(strobe_pulse),
        .HIT_12(hit_neg[12]),
        .BL_13(bln[13]),
        .VREF_13(vref),
        .STROBE_13(strobe_pulse),
        .HIT_13(hit_neg[13]),
        .BL_14(bln[14]),
        .VREF_14(vref),
        .STROBE_14(strobe_pulse),
        .HIT_14(hit_neg[14]),
        .BL_15(bln[15]),
        .VREF_15(vref),
        .STROBE_15(strobe_pulse),
        .HIT_15(hit_neg[15])
`ifdef USE_POWER_PINS
        , .VDD(VPWR), .VGND(VGND)
`endif
    );
    sa_se_band16 u_band_n_hi (
        .BL_0(bln[16]),
        .VREF_0(vref),
        .STROBE_0(strobe_pulse),
        .HIT_0(hit_neg[16]),
        .BL_1(bln[17]),
        .VREF_1(vref),
        .STROBE_1(strobe_pulse),
        .HIT_1(hit_neg[17]),
        .BL_2(bln[18]),
        .VREF_2(vref),
        .STROBE_2(strobe_pulse),
        .HIT_2(hit_neg[18]),
        .BL_3(bln[19]),
        .VREF_3(vref),
        .STROBE_3(strobe_pulse),
        .HIT_3(hit_neg[19]),
        .BL_4(bln[20]),
        .VREF_4(vref),
        .STROBE_4(strobe_pulse),
        .HIT_4(hit_neg[20]),
        .BL_5(bln[21]),
        .VREF_5(vref),
        .STROBE_5(strobe_pulse),
        .HIT_5(hit_neg[21]),
        .BL_6(bln[22]),
        .VREF_6(vref),
        .STROBE_6(strobe_pulse),
        .HIT_6(hit_neg[22]),
        .BL_7(bln[23]),
        .VREF_7(vref),
        .STROBE_7(strobe_pulse),
        .HIT_7(hit_neg[23]),
        .BL_8(bln[24]),
        .VREF_8(vref),
        .STROBE_8(strobe_pulse),
        .HIT_8(hit_neg[24]),
        .BL_9(bln[25]),
        .VREF_9(vref),
        .STROBE_9(strobe_pulse),
        .HIT_9(hit_neg[25]),
        .BL_10(bln[26]),
        .VREF_10(vref),
        .STROBE_10(strobe_pulse),
        .HIT_10(hit_neg[26]),
        .BL_11(bln[27]),
        .VREF_11(vref),
        .STROBE_11(strobe_pulse),
        .HIT_11(hit_neg[27]),
        .BL_12(bln[28]),
        .VREF_12(vref),
        .STROBE_12(strobe_pulse),
        .HIT_12(hit_neg[28]),
        .BL_13(bln[29]),
        .VREF_13(vref),
        .STROBE_13(strobe_pulse),
        .HIT_13(hit_neg[29]),
        .BL_14(bln[30]),
        .VREF_14(vref),
        .STROBE_14(strobe_pulse),
        .HIT_14(hit_neg[30]),
        .BL_15(bln[31]),
        .VREF_15(vref),
        .STROBE_15(strobe_pulse),
        .HIT_15(hit_neg[31])
`ifdef USE_POWER_PINS
        , .VDD(VPWR), .VGND(VGND)
`endif
    );

endmodule

`default_nettype wire
