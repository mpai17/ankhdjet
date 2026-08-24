// Grid readout + accumulation controller: computes a full tiled layer's
// matrix-vector product across a GRID_R x GRID_C grid of mask-programmed
// array chunks.
//
// A layer's (N x M) ternary weight matrix, N = GRID_R*MR input rows and
// M = GRID_C*MC output columns, is tiled into MR x MC chunks. The grid
// flattens cleanly: every row-chunk produces the same M output columns,
// so output column m at row-chunk ir reads bitline (ir*M + m), and the
// accumulator for m sums that column's contribution across all row-chunks.
// The controller therefore sweeps each of the N global rows once, firing
// its one-hot global wordline, and accumulates all M outputs in parallel
// (bit-serial add/sub/skip, sign from the chunk's BLP/BLN pair, magnitude
// from the stored activation), then streams the M accumulators as bytes.
//
// This is the single-macro digital controller (rtl/tt_digital) generalized
// to a macro grid: the wordline is global (position selects the row-chunk),
// and the bitline read is offset by row-chunk. Activations are stored
// (N deep); accumulators are M-wide parallel.
`default_nettype none

module cirom_grid_ctrl #(
    parameter int GRID_R = 2,
    parameter int GRID_C = 2,
    parameter int MR     = 8,
    parameter int MC     = 4,
    parameter int ACT_W  = 4,
    parameter int ACC_W  = 16,
    parameter int OUT_W  = 8
)(
    input  logic                 clk,
    input  logic                 rst_n,
    input  logic [7:0]           ui,        // one activation per write (ACT_W bits)
    input  logic                 act_wr,
    input  logic                 start,
    // grid interface (flattened)
    output logic [GRID_R*MR-1:0] wl,        // one-hot global wordline
    output logic                 pre_n,
    input  logic [GRID_R*(GRID_C*MC)-1:0] blp,   // row-chunk-banded bitlines
    input  logic [GRID_R*(GRID_C*MC)-1:0] bln,
    // result stream
    output logic [OUT_W-1:0]     result,
    output logic                 result_valid,
    output logic                 busy,
    output logic                 done
);
    localparam int N     = GRID_R * MR;          // input rows
    localparam int M     = GRID_C * MC;          // output cols
    localparam int NB    = 2 * M;                // result bytes
    localparam int GB    = $clog2(N);            // global row index bits
    localparam int MB    = (N > 1) ? $clog2(N) : 1;

    typedef enum logic [2:0] {
        S_IDLE, S_PRECHG, S_EVAL, S_SAMPLE, S_ACC, S_NEXT, S_SHIFT, S_DONE
    } state_t;
    state_t state, next;

    // activation store: N x ACT_W, one per write, packed flat
    logic [N*ACT_W-1:0] act_mem;
    logic [MB-1:0]      act_ptr;
    integer w;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) act_ptr <= '0;
        else if (act_wr && state == S_IDLE) begin
            for (w = 0; w < N; w = w + 1)
                if (act_ptr == w[MB-1:0])
                    act_mem[w*ACT_W +: ACT_W] <= ui[ACT_W-1:0];
            act_ptr <= act_ptr + 1'b1;
        end else if (start && state == S_IDLE) act_ptr <= '0;
    end

    logic [MB-1:0]           row_g;      // global row 0..N-1
    logic [$clog2(GRID_R+1)-1:0] ir;     // row-chunk of the current row
    logic [$clog2(MR)-1:0]   r_loc;      // local wordline within row-chunk
    logic [$clog2(M*GRID_R+1)-1:0] bl_base;  // ir*M, bitline band offset
    logic [3:0]              cnt;
    logic [M-1:0]            pos_hit, neg_hit;
    logic signed [ACC_W-1:0] acc [0:M-1];
    logic [$clog2(NB)-1:0]   byte_q;
    wire  [ACT_W-1:0]        act_cur = act_mem[row_g*ACT_W +: ACT_W];
    wire                     last_row = (row_g == N[MB-1:0] - 1'b1);
    wire                     last_b   = (byte_q == NB[$clog2(NB)-1:0] - 1'b1);

    integer i;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; row_g <= '0; ir <= '0; r_loc <= '0;
            bl_base <= '0; cnt <= '0; byte_q <= '0;
            pos_hit <= '0; neg_hit <= '0;
            for (i = 0; i < M; i = i + 1) acc[i] <= '0;
        end else begin
            state <= next;
            case (state)
                S_IDLE: if (start) begin
                    row_g <= '0; ir <= '0; r_loc <= '0; bl_base <= '0;
                    byte_q <= '0; cnt <= 4'd2;
                    for (i = 0; i < M; i = i + 1) acc[i] <= '0;
                end
                S_PRECHG: if (cnt == 0) cnt <= 4'd2; else cnt <= cnt - 1'b1;
                S_EVAL:   if (cnt != 0) cnt <= cnt - 1'b1;
                S_SAMPLE: begin
                    for (i = 0; i < M; i = i + 1) begin
                        pos_hit[i] <= ~blp[bl_base + i];
                        neg_hit[i] <= ~bln[bl_base + i];
                    end
                end
                S_ACC: begin
                    for (i = 0; i < M; i = i + 1) begin
                        if (pos_hit[i])
                            acc[i] <= acc[i] + $signed({{(ACC_W-ACT_W){1'b0}}, act_cur});
                        else if (neg_hit[i])
                            acc[i] <= acc[i] - $signed({{(ACC_W-ACT_W){1'b0}}, act_cur});
                    end
                end
                S_NEXT: begin
                    row_g <= row_g + 1'b1;
                    cnt   <= 4'd2;
                    if (r_loc == MR[$clog2(MR)-1:0] - 1'b1) begin
                        r_loc   <= '0;
                        ir      <= ir + 1'b1;
                        bl_base <= bl_base + M[$clog2(M*GRID_R+1)-1:0];
                    end else begin
                        r_loc <= r_loc + 1'b1;
                    end
                end
                S_SHIFT: byte_q <= byte_q + 1'b1;
                default: ;
            endcase
        end
    end

    always_comb begin
        next = state;
        case (state)
            S_IDLE:   if (start) next = S_PRECHG;
            S_PRECHG: if (cnt == 0) next = S_EVAL;
            S_EVAL:   if (cnt == 0) next = S_SAMPLE;
            S_SAMPLE: next = S_ACC;
            S_ACC:    next = S_NEXT;
            S_NEXT:   if (last_row) next = S_SHIFT; else next = S_PRECHG;
            S_SHIFT:  if (last_b) next = S_DONE;
            S_DONE:   next = S_IDLE;
            default:  next = S_IDLE;
        endcase
    end

    // one-hot global wordline during the read of the current row
    wire reading = (state == S_PRECHG) || (state == S_EVAL) || (state == S_SAMPLE);
    always_comb begin
        wl = '0;
        if (reading) wl[row_g] = 1'b1;
    end
    assign pre_n = (state == S_PRECHG) ? 1'b0 : 1'b1;

    // result: M accumulators, low byte then high byte, ascending column
    wire [$clog2(M)-1:0] acc_idx = byte_q[$clog2(NB)-1:1];
    wire                 acc_hi  = byte_q[0];
    wire signed [ACC_W-1:0] acc_sel = acc[acc_idx];
    wire [OUT_W-1:0] acc_lo_b = acc_sel[7:0];
    wire [OUT_W-1:0] acc_hi_b = {{(16-ACC_W){acc_sel[ACC_W-1]}}, acc_sel[ACC_W-1:8]};
    assign result       = acc_hi ? acc_hi_b : acc_lo_b;
    assign result_valid = (state == S_SHIFT);
    assign busy         = (state != S_IDLE);
    assign done         = (state == S_DONE);

endmodule

`default_nettype wire
