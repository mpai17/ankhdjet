// Digital-tier controller for the mask-programmed CiROM array: readout is
// a clocked digital sample of each bitline (no comparators, no reference),
// and the tile carries the ternary MAC on die.
//
// Two modes:
//   MVM (mode=0): N_COLS/N_ACC passes; each pass sweeps all N_ROWS rows
//     (precharge -> evaluate -> sample -> accumulate) with the N_ACC signed
//     ACC_W-bit accumulators muxed onto that pass's column group, then
//     streams the group's accumulators out as 2 bytes each, low byte first
//     (sign-extended above ACC_W-8). Groups stream in ascending column
//     order, so the full result is column 0..N_COLS-1 regardless of N_ACC.
//   Raw row read (mode=1): read one addressed row and stream the captured
//     {neg_hit, pos_hit} bytes, matching the analog tile's readout so the
//     same bench scripts regress both tiles.
//
// Activation source (STORE_ACTS parameter):
//   1: on-die N_ROWS x ACT_W store, loaded once before start (two
//      activations per act_wr byte, low nibble = even row); MVM runs at
//      speed with no host interaction.
//   0: no store; the host streams the same bytes just in time, one per
//      row pair, re-sent each pass. The controller stalls in S_WAIT_ACT
//      until act_wr, so any slower-than-consumption host is safe; a byte
//      arriving outside S_WAIT_ACT during an MVM is dropped (the stream
//      contract is at most one byte per row-pair time).
//
// Read timing follows the shared read discipline: WL one-hot, PRE_N low for
// pre_width+1 cycles, evaluate for strobe_delay+1 cycles, then a one-cycle
// SAMPLE pulse captures hit = ~BL into flops. Config (strobe_delay,
// pre_width, bypass_pre) loads through the same serial register scheme as
// the analog tile: hold cfg_mode high, clock CFG_BITS bits in on cfg_in.
`default_nettype none

module cirom_dig_ctrl #(
    parameter int N_ROWS     = 64,
    parameter int N_COLS     = 32,
    parameter int N_ACC      = 8,
    parameter int ACC_W      = 12,
    parameter int ACT_W      = 4,
    parameter int OUT_W      = 8,
    parameter int CFG_BITS   = 16,
    parameter int STORE_ACTS = 1
)(
    input  logic                      clk,
    input  logic                      rst_n,
    // host command
    input  logic [7:0]                ui,          // act byte (load) / row_addr (raw mode)
    input  logic                      act_wr,      // write two 4-bit activations from ui
    input  logic                      start,
    input  logic                      mode,        // 0 = MVM, 1 = raw row read
    // serial config
    input  logic                      cfg_mode,
    input  logic                      cfg_in,
    // array interface (digital sense: raw bitlines in, sampled here)
    output logic [N_ROWS-1:0]         wl,
    output logic                      pre_n,
    input  logic [N_COLS-1:0]         blp,
    input  logic [N_COLS-1:0]         bln,
    // serialized result out
    output logic [OUT_W-1:0]          result,
    output logic                      result_valid,
    output logic                      busy,
    output logic                      done
);
    localparam int RB     = $clog2(N_ROWS);
    localparam int NHIT   = 2 * N_COLS;
    localparam int RAWB   = (NHIT + OUT_W - 1) / OUT_W;   // raw-mode bytes
    localparam int PASSES = N_COLS / N_ACC;               // column groups
    localparam int GRPB   = 2 * N_ACC;                    // bytes per group
    localparam int MVMB   = 2 * N_COLS;                   // total MVM bytes

    typedef enum logic [3:0] {
        S_IDLE, S_PRECHG, S_EVAL, S_SAMPLE, S_ACC, S_NEXT, S_SHIFT,
        S_NEXTGRP, S_DONE, S_WAIT_ACT
    } state_t;
    state_t state, next;

    // config register (same scheme and fields as the analog tile)
    logic [CFG_BITS-1:0] cfg_reg;
    wire  [3:0] cfg_strobe_delay = cfg_reg[3:0];
    wire  [3:0] cfg_pre_width    = cfg_reg[7:4];
    wire        cfg_bypass_pre   = cfg_reg[8];
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)        cfg_reg <= '0;
        else if (cfg_mode) cfg_reg <= {cfg_reg[CFG_BITS-2:0], cfg_in};
    end

    logic                mode_q;
    logic [RB-1:0]       row_q;
    logic [3:0]          cnt;
    logic [N_COLS-1:0]   pos_hit, neg_hit;   // sampled at S_SAMPLE
    logic signed [ACC_W-1:0] acc [0:N_ACC-1];
    logic [$clog2(MVMB)-1:0] byte_q;
    logic [$clog2(PASSES):0] grp_q;   // column group of the current pass
    wire  [RB-1:0]       raw_row   = ui[RB-1:0];
    wire                 last_row  = (row_q == N_ROWS - 1);
    wire                 last_grp  = (grp_q == PASSES - 1);
    wire  [$clog2(MVMB)-1:0] last_b = mode_q ? RAWB - 1 : GRPB - 1;

    // activation source: the current row's ACT_W-bit magnitude.
    // STORE_ACTS=1: N_ROWS x ACT_W packed-flat store, loaded one byte per
    //   ui beat (two activations per byte, low nibble = even row). The
    //   write decode is an unrolled loop of constant part-selects and the
    //   read is a packed part-select shift, keeping synthesis to plain
    //   registers and muxes (no memory inference, no dynamic-select
    //   helper wires).
    // STORE_ACTS=0: one row-pair register, latched from ui in S_WAIT_ACT;
    //   the host re-streams the vector each pass.
    wire [ACT_W-1:0] act_nib;
    generate if (STORE_ACTS != 0) begin : g_act_store
        logic [N_ROWS*ACT_W-1:0]     act_mem;
        logic [$clog2(N_ROWS/2)-1:0] act_ptr;
        integer b;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                act_ptr <= '0;
            end else if (act_wr && state == S_IDLE) begin
                for (b = 0; b < N_ROWS/2; b = b + 1)
                    if (act_ptr == b)
                        act_mem[b*2*ACT_W +: 2*ACT_W] <= ui[2*ACT_W-1:0];
                act_ptr <= act_ptr + 1'b1;
            end else if (start && state == S_IDLE) begin
                act_ptr <= '0;
            end
        end
        assign act_nib = act_mem[row_q*ACT_W +: ACT_W];
    end else begin : g_act_stream
        logic [2*ACT_W-1:0] act_cur;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n)                             act_cur <= '0;
            else if (state == S_WAIT_ACT && act_wr) act_cur <= ui[2*ACT_W-1:0];
        end
        assign act_nib = row_q[0] ? act_cur[2*ACT_W-1:ACT_W]
                                  : act_cur[ACT_W-1:0];
    end endgenerate

    integer i;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; row_q <= '0; cnt <= '0; mode_q <= 1'b0;
            pos_hit <= '0; neg_hit <= '0; byte_q <= '0; grp_q <= '0;
            for (i = 0; i < N_ACC; i = i + 1) acc[i] <= '0;
        end else begin
            state <= next;
            case (state)
                S_IDLE: if (start) begin
                    mode_q <= mode;
                    row_q  <= mode ? raw_row : '0;
                    cnt    <= cfg_pre_width;
                    byte_q <= '0;
                    grp_q  <= '0;
                    if (!mode) for (i = 0; i < N_ACC; i = i + 1) acc[i] <= '0;
                end
                S_PRECHG: if (cnt == 0) cnt <= cfg_strobe_delay; else cnt <= cnt - 1'b1;
                S_EVAL:   if (cnt != 0) cnt <= cnt - 1'b1;
                S_SAMPLE: begin
                    pos_hit <= ~blp;   // discharged bitline reads as a hit
                    neg_hit <= ~bln;
                end
                S_ACC: begin
                    for (i = 0; i < N_ACC; i = i + 1) begin
                        case ({pos_hit[grp_q[$clog2(PASSES)-1:0]*N_ACC + i],
                               neg_hit[grp_q[$clog2(PASSES)-1:0]*N_ACC + i]})
                            2'b10: acc[i] <= acc[i] + $signed({{(ACC_W-ACT_W){1'b0}}, act_nib});
                            2'b01: acc[i] <= acc[i] - $signed({{(ACC_W-ACT_W){1'b0}}, act_nib});
                            default: ;
                        endcase
                    end
                end
                S_NEXT: begin row_q <= row_q + 1'b1; cnt <= cfg_pre_width; end
                S_SHIFT: byte_q <= byte_q + 1'b1;
                S_NEXTGRP: begin
                    grp_q  <= grp_q + 1'b1;
                    row_q  <= '0;
                    cnt    <= cfg_pre_width;
                    byte_q <= '0;
                    for (i = 0; i < N_ACC; i = i + 1) acc[i] <= '0;
                end
                default: ;
            endcase
        end
    end

    always_comb begin
        next = state;
        case (state)
            S_IDLE:   if (start) begin
                          if (STORE_ACTS == 0 && !mode) next = S_WAIT_ACT;
                          else if (cfg_bypass_pre) next = S_EVAL; else next = S_PRECHG;
                      end
            S_WAIT_ACT: if (act_wr) begin
                          if (cfg_bypass_pre) next = S_EVAL; else next = S_PRECHG;
                      end
            S_PRECHG: if (cnt == 0) next = S_EVAL;
            S_EVAL:   if (cnt == 0) next = S_SAMPLE;
            S_SAMPLE: if (mode_q) next = S_SHIFT; else next = S_ACC;
            S_ACC:    if (last_row) next = S_SHIFT; else next = S_NEXT;
            S_NEXT:   begin
                          // row_q increments this state; the incoming row is
                          // even (a new byte) exactly when the current is odd
                          if (STORE_ACTS == 0 && !mode_q && row_q[0]) next = S_WAIT_ACT;
                          else if (cfg_bypass_pre) next = S_EVAL; else next = S_PRECHG;
                      end
            S_SHIFT:  if (byte_q == last_b) begin
                          if (mode_q || last_grp) next = S_DONE;
                          else next = S_NEXTGRP;
                      end
            S_NEXTGRP: begin
                          if (STORE_ACTS == 0) next = S_WAIT_ACT;
                          else if (cfg_bypass_pre) next = S_EVAL; else next = S_PRECHG;
                      end
            S_DONE:   next = S_IDLE;
            default:  next = S_IDLE;
        endcase
    end

    // wordline: one-hot during precharge-evaluate-sample of the active row
    wire reading = (state == S_PRECHG) || (state == S_EVAL) || (state == S_SAMPLE);
    always_comb begin
        wl = '0;
        if (reading) wl[row_q] = 1'b1;
    end
    assign pre_n = (state == S_PRECHG) ? 1'b0 : 1'b1;

    // result mux: raw hit bytes, or accumulator low/high bytes
    wire [NHIT-1:0] captured = {neg_hit, pos_hit};
    wire [$clog2(N_ACC)-1:0] acc_idx = byte_q[$clog2(GRPB)-1:1];
    wire            acc_hi   = byte_q[0];
    wire signed [ACC_W-1:0] acc_sel = acc[acc_idx];
    wire [OUT_W-1:0] raw_byte = captured[byte_q[$clog2(RAWB)-1:0]*OUT_W +: OUT_W];
    wire [OUT_W-1:0] acc_lo_b = acc_sel[7:0];
    wire [OUT_W-1:0] acc_hi_b = {{(16-ACC_W){acc_sel[ACC_W-1]}}, acc_sel[ACC_W-1:8]};
    assign result = mode_q ? raw_byte : (acc_hi ? acc_hi_b : acc_lo_b);
    assign result_valid = (state == S_SHIFT);
    assign busy         = (state != S_IDLE);
    assign done         = (state == S_DONE);

endmodule

`default_nettype wire
