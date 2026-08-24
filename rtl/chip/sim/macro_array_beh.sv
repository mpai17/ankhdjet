// SystemVerilog behavioral model of a macro_array_pc_64x32_<variant>
// array macro for chip-level functional simulation (module name set by
// ANKHDJET_ARRAY_MODULE, contents by ANKHDJET_WEIGHTS_MEMH_BASE).
// Encodes the macro's intended contract:
//   - while no WL is asserted, the per-column precharge pulls every
//     bitline high;
//   - while WL_r is asserted, each column's programmed bitline
//     discharges (+1 -> BLP, -1 -> BLN per the loaded memh views) and
//     the unprogrammed bitline holds its precharged level dynamically.
// Power pins are modeled as plain inouts and ignored.
`default_nettype none

`ifndef ANKHDJET_ARRAY_MODULE
`define ANKHDJET_ARRAY_MODULE macro_array_pc_64x32_checker
`endif
`ifndef ANKHDJET_WEIGHTS_MEMH_BASE
`define ANKHDJET_WEIGHTS_MEMH_BASE "macro/sky130/abstracts/macro_array_pc_64x32_checker"
`endif

module `ANKHDJET_ARRAY_MODULE (
    input  logic PRE_N,
    input  logic WL_0,  input logic WL_1,  input logic WL_2,  input logic WL_3,
    input  logic WL_4,  input logic WL_5,  input logic WL_6,  input logic WL_7,
    input  logic WL_8,  input logic WL_9,  input logic WL_10, input logic WL_11,
    input  logic WL_12, input logic WL_13, input logic WL_14, input logic WL_15,
    input  logic WL_16, input logic WL_17, input logic WL_18, input logic WL_19,
    input  logic WL_20, input logic WL_21, input logic WL_22, input logic WL_23,
    input  logic WL_24, input logic WL_25, input logic WL_26, input logic WL_27,
    input  logic WL_28, input logic WL_29, input logic WL_30, input logic WL_31,
    input  logic WL_32, input logic WL_33, input logic WL_34, input logic WL_35,
    input  logic WL_36, input logic WL_37, input logic WL_38, input logic WL_39,
    input  logic WL_40, input logic WL_41, input logic WL_42, input logic WL_43,
    input  logic WL_44, input logic WL_45, input logic WL_46, input logic WL_47,
    input  logic WL_48, input logic WL_49, input logic WL_50, input logic WL_51,
    input  logic WL_52, input logic WL_53, input logic WL_54, input logic WL_55,
    input  logic WL_56, input logic WL_57, input logic WL_58, input logic WL_59,
    input  logic WL_60, input logic WL_61, input logic WL_62, input logic WL_63,
    output logic BLP_0,  output logic BLN_0,  output logic BLP_1,  output logic BLN_1,
    output logic BLP_2,  output logic BLN_2,  output logic BLP_3,  output logic BLN_3,
    output logic BLP_4,  output logic BLN_4,  output logic BLP_5,  output logic BLN_5,
    output logic BLP_6,  output logic BLN_6,  output logic BLP_7,  output logic BLN_7,
    output logic BLP_8,  output logic BLN_8,  output logic BLP_9,  output logic BLN_9,
    output logic BLP_10, output logic BLN_10, output logic BLP_11, output logic BLN_11,
    output logic BLP_12, output logic BLN_12, output logic BLP_13, output logic BLN_13,
    output logic BLP_14, output logic BLN_14, output logic BLP_15, output logic BLN_15,
    output logic BLP_16, output logic BLN_16, output logic BLP_17, output logic BLN_17,
    output logic BLP_18, output logic BLN_18, output logic BLP_19, output logic BLN_19,
    output logic BLP_20, output logic BLN_20, output logic BLP_21, output logic BLN_21,
    output logic BLP_22, output logic BLN_22, output logic BLP_23, output logic BLN_23,
    output logic BLP_24, output logic BLN_24, output logic BLP_25, output logic BLN_25,
    output logic BLP_26, output logic BLN_26, output logic BLP_27, output logic BLN_27,
    output logic BLP_28, output logic BLN_28, output logic BLP_29, output logic BLN_29,
    output logic BLP_30, output logic BLN_30, output logic BLP_31, output logic BLN_31,
    inout  wire VPWR,
    inout  wire VGND
);

    logic [63:0] wl;
    assign wl = {WL_63, WL_62, WL_61, WL_60, WL_59, WL_58, WL_57, WL_56,
                      WL_55, WL_54, WL_53, WL_52, WL_51, WL_50, WL_49, WL_48,
                      WL_47, WL_46, WL_45, WL_44, WL_43, WL_42, WL_41, WL_40,
                      WL_39, WL_38, WL_37, WL_36, WL_35, WL_34, WL_33, WL_32,
                      WL_31, WL_30, WL_29, WL_28, WL_27, WL_26, WL_25, WL_24,
                      WL_23, WL_22, WL_21, WL_20, WL_19, WL_18, WL_17, WL_16,
                      WL_15, WL_14, WL_13, WL_12, WL_11, WL_10, WL_9,  WL_8,
                      WL_7,  WL_6,  WL_5,  WL_4,  WL_3,  WL_2,  WL_1,  WL_0};

    // Weight matrix views generated alongside the macro abstracts: one
    // bit per (row, col) and polarity. w=0 cells appear in neither.
    logic [31:0] wpos [0:63];
    logic [31:0] wneg [0:63];
    initial begin
        $readmemh({`ANKHDJET_WEIGHTS_MEMH_BASE, ".wpos.memh"}, wpos);
        $readmemh({`ANKHDJET_WEIGHTS_MEMH_BASE, ".wneg.memh"}, wneg);
    end

    logic [31:0] blp_q = 32'hFFFF_FFFF;
    logic [31:0] bln_q = 32'hFFFF_FFFF;
    int r;

    always @(wl or PRE_N) begin
        if (!PRE_N) begin
            // precharge: the clocked pull-up pair drives every bitline high
            blp_q <= 32'hFFFF_FFFF;
            bln_q <= 32'hFFFF_FFFF;
        end else if (wl != 64'd0) begin
            // evaluate (PRE_N high): every asserted row discharges its
            // programmed lines; unprogrammed lines hold dynamically
            for (r = 0; r < 64; r = r + 1) begin
                if (wl[r]) begin
                    blp_q <= blp_q & ~wpos[r];
                    bln_q <= bln_q & ~wneg[r];
                end
            end
        end
    end

    assign {BLP_31, BLP_30, BLP_29, BLP_28, BLP_27, BLP_26, BLP_25, BLP_24,
            BLP_23, BLP_22, BLP_21, BLP_20, BLP_19, BLP_18, BLP_17, BLP_16,
            BLP_15, BLP_14, BLP_13, BLP_12, BLP_11, BLP_10, BLP_9,  BLP_8,
            BLP_7,  BLP_6,  BLP_5,  BLP_4,  BLP_3,  BLP_2,  BLP_1,  BLP_0} = blp_q;
    assign {BLN_31, BLN_30, BLN_29, BLN_28, BLN_27, BLN_26, BLN_25, BLN_24,
            BLN_23, BLN_22, BLN_21, BLN_20, BLN_19, BLN_18, BLN_17, BLN_16,
            BLN_15, BLN_14, BLN_13, BLN_12, BLN_11, BLN_10, BLN_9,  BLN_8,
            BLN_7,  BLN_6,  BLN_5,  BLN_4,  BLN_3,  BLN_2,  BLN_1,  BLN_0} = bln_q;

endmodule

`default_nettype wire
