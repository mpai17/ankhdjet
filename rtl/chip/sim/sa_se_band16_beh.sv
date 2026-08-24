// SystemVerilog behavioral model of sa_se_band16 for chip-level functional
// simulation, faithful to the StrongARM reset behavior: while STROBE is
// low the reset PMOS pair drags HIT high (the decision is NOT held), and
// at the STROBE rising edge the latch resolves HIT = (BL discharged
// below VREF) -- digitally ~BL -- held only while STROBE stays high.
// VREF is the analog reference and is ignored here (the analog margin
// is validated separately in SPICE).
`default_nettype none

module sa_se_band16 (
    input  logic BL_0,  input logic VREF_0,  input logic STROBE_0,  output wire HIT_0,
    input  logic BL_1,  input logic VREF_1,  input logic STROBE_1,  output wire HIT_1,
    input  logic BL_2,  input logic VREF_2,  input logic STROBE_2,  output wire HIT_2,
    input  logic BL_3,  input logic VREF_3,  input logic STROBE_3,  output wire HIT_3,
    input  logic BL_4,  input logic VREF_4,  input logic STROBE_4,  output wire HIT_4,
    input  logic BL_5,  input logic VREF_5,  input logic STROBE_5,  output wire HIT_5,
    input  logic BL_6,  input logic VREF_6,  input logic STROBE_6,  output wire HIT_6,
    input  logic BL_7,  input logic VREF_7,  input logic STROBE_7,  output wire HIT_7,
    input  logic BL_8,  input logic VREF_8,  input logic STROBE_8,  output wire HIT_8,
    input  logic BL_9,  input logic VREF_9,  input logic STROBE_9,  output wire HIT_9,
    input  logic BL_10, input logic VREF_10, input logic STROBE_10, output wire HIT_10,
    input  logic BL_11, input logic VREF_11, input logic STROBE_11, output wire HIT_11,
    input  logic BL_12, input logic VREF_12, input logic STROBE_12, output wire HIT_12,
    input  logic BL_13, input logic VREF_13, input logic STROBE_13, output wire HIT_13,
    input  logic BL_14, input logic VREF_14, input logic STROBE_14, output wire HIT_14,
    input  logic BL_15, input logic VREF_15, input logic STROBE_15, output wire HIT_15
`ifdef USE_POWER_PINS
    , inout wire VDD, inout wire VGND
`endif
);

    logic q_HIT_0;
    always_ff @(posedge STROBE_0) q_HIT_0 <= ~BL_0;
    assign HIT_0 = STROBE_0 ? q_HIT_0 : 1'b1;
    logic q_HIT_1;
    always_ff @(posedge STROBE_1) q_HIT_1 <= ~BL_1;
    assign HIT_1 = STROBE_1 ? q_HIT_1 : 1'b1;
    logic q_HIT_2;
    always_ff @(posedge STROBE_2) q_HIT_2 <= ~BL_2;
    assign HIT_2 = STROBE_2 ? q_HIT_2 : 1'b1;
    logic q_HIT_3;
    always_ff @(posedge STROBE_3) q_HIT_3 <= ~BL_3;
    assign HIT_3 = STROBE_3 ? q_HIT_3 : 1'b1;
    logic q_HIT_4;
    always_ff @(posedge STROBE_4) q_HIT_4 <= ~BL_4;
    assign HIT_4 = STROBE_4 ? q_HIT_4 : 1'b1;
    logic q_HIT_5;
    always_ff @(posedge STROBE_5) q_HIT_5 <= ~BL_5;
    assign HIT_5 = STROBE_5 ? q_HIT_5 : 1'b1;
    logic q_HIT_6;
    always_ff @(posedge STROBE_6) q_HIT_6 <= ~BL_6;
    assign HIT_6 = STROBE_6 ? q_HIT_6 : 1'b1;
    logic q_HIT_7;
    always_ff @(posedge STROBE_7) q_HIT_7 <= ~BL_7;
    assign HIT_7 = STROBE_7 ? q_HIT_7 : 1'b1;
    logic q_HIT_8;
    always_ff @(posedge STROBE_8) q_HIT_8 <= ~BL_8;
    assign HIT_8 = STROBE_8 ? q_HIT_8 : 1'b1;
    logic q_HIT_9;
    always_ff @(posedge STROBE_9) q_HIT_9 <= ~BL_9;
    assign HIT_9 = STROBE_9 ? q_HIT_9 : 1'b1;
    logic q_HIT_10;
    always_ff @(posedge STROBE_10) q_HIT_10 <= ~BL_10;
    assign HIT_10 = STROBE_10 ? q_HIT_10 : 1'b1;
    logic q_HIT_11;
    always_ff @(posedge STROBE_11) q_HIT_11 <= ~BL_11;
    assign HIT_11 = STROBE_11 ? q_HIT_11 : 1'b1;
    logic q_HIT_12;
    always_ff @(posedge STROBE_12) q_HIT_12 <= ~BL_12;
    assign HIT_12 = STROBE_12 ? q_HIT_12 : 1'b1;
    logic q_HIT_13;
    always_ff @(posedge STROBE_13) q_HIT_13 <= ~BL_13;
    assign HIT_13 = STROBE_13 ? q_HIT_13 : 1'b1;
    logic q_HIT_14;
    always_ff @(posedge STROBE_14) q_HIT_14 <= ~BL_14;
    assign HIT_14 = STROBE_14 ? q_HIT_14 : 1'b1;
    logic q_HIT_15;
    always_ff @(posedge STROBE_15) q_HIT_15 <= ~BL_15;
    assign HIT_15 = STROBE_15 ? q_HIT_15 : 1'b1;

    logic _unused; assign _unused = &{1'b0,
                     VREF_0, VREF_1, VREF_2,  VREF_3,  VREF_4,  VREF_5,  VREF_6,  VREF_7,
                     VREF_8, VREF_9, VREF_10, VREF_11, VREF_12, VREF_13, VREF_14, VREF_15};

endmodule

`default_nettype wire
