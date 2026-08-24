// NOR-array CiROM tile with column-tiled row-sequential readout.
//
// NOR ROM structural family (production precedent WO2025217724A1;
// academic precedent BitROM arXiv 2509.08542):
//   - 1 NMOS per ternary weight position, gate=WL, source=VGND, drain
//     mask-routed to BL+ (w=+1) / BL- (w=-1) / VGND (w=0) at fab time.
//   - Column tiled into SUBCOL_ROWS-row sub-columns, each with its own
//     precharge + readout pair. All sub-columns read in parallel each
//     cycle.
//   - Inside each sub-column the WL is one-hot: only one row is asserted
//     per cycle; the readout latches BL+/BL- digital hits at end of
//     cycle (full-swing samplers in the digital tier, comparators in
//     the analog variant).
//   - Per output column an integer MAC accumulates (pos_hit - neg_hit) *
//     act_bit << k over N rows * K bit-slices.
//
// This module is the structural model: the per-position AND between
// `wl_onehot` and the baked-in HAS_VIA_POS / HAS_VIA_NEG parameters
// reproduces what a real NOR-array would do at the gate level. Yosys
// constant-propagates the AND so positions with HAS_VIA_*=0 vanish.
//
// Cycles per dot product:
//   T = K * SUBCOL_ROWS + small_overhead  (with parallel sub-columns)
// vs the legacy parallel-WL cirom_tile which used T = K * tile_cols and
// could not be implemented with 1 NMOS / cell.

`default_nettype none

module cirom_nor_tile #(
    parameter int          N           = 256,   // total rows in this tile
    parameter int          M           = 64,    // output columns in this tile
    parameter int          K           = 8,     // activation bit width
    parameter int          SUBCOL_ROWS = 128,   // rows per sub-column
    parameter int          WACC        = 24,    // accumulator width
    parameter [N*M-1:0]    HAS_VIA_POS = {(N*M){1'b0}},  // weight = +1 mask
    parameter [N*M-1:0]    HAS_VIA_NEG = {(N*M){1'b0}}   // weight = -1 mask
) (
    input  logic                       clk,
    input  logic                       rst_n,
    input  logic                       start,
    input  logic [K*N-1:0]             act_flat,   // unsigned K-bit per row
    output logic signed [WACC*M-1:0]   acc_flat,
    output logic                       valid
);
    // Number of sub-columns and rows-per-pass (last sub-column may be partial).
    localparam int N_SUB = (N + SUBCOL_ROWS - 1) / SUBCOL_ROWS;

    // State: bit-slice index (k) and intra-subcol row index (r).
    // All sub-columns are processed in parallel, so we only iterate r and k.
    localparam int K_W = $clog2(K + 1);
    localparam int R_W = $clog2(SUBCOL_ROWS + 1);
    logic [K_W-1:0] k_idx;
    logic [R_W-1:0] r_idx;
    logic running;

    // Latched activations for the entire tile (only sampled at start).
    logic [K*N-1:0] act_latched;

    // Per-column accumulators.
    logic signed [WACC-1:0] acc [M];
    genvar gj;
    generate
        for (gj = 0; gj < M; gj++) begin : g_pack
            assign acc_flat[WACC*(gj+1)-1 -: WACC] = acc[gj];
        end
    endgenerate

    // For each output column, sum (pos_hit - neg_hit) across all sub-columns
    // for the current (r_idx, k_idx). pos_hit[s][c] = HAS_VIA_POS at the
    // global row index s*SUBCOL_ROWS + r_idx; same for neg.
    // The activation bit per sub-column is bit k_idx of that sub-column's
    // current row's activation.
    //
    // We model each sub-column's contribution and sum digitally; the
    // physical implementation has one readout pair per sub-column
    // (full-swing samplers in the digital tier) whose outputs feed a
    // small per-column adder.

    // Hit counts (one per output column), summed across sub-columns.
    // Range: -N_SUB ... +N_SUB; signed log2(N_SUB)+2 bits is safe.
    localparam int HIT_W = $clog2(N_SUB + 1) + 2;

    logic signed [HIT_W-1:0] hits [M];

    // Loop temporaries at module scope (assigned before every use in the
    // block below): explicit `automatic` lifetimes are not portable to
    // every simulator this file elaborates under.
    integer s, c;
    int   row, act_bit_idx, w_idx;
    logic a, pos, neg;
    always_comb begin
        for (c = 0; c < M; c++) begin
            hits[c] = '0;
        end
        row = 0; act_bit_idx = 0; w_idx = 0; a = 1'b0; pos = 1'b0; neg = 1'b0;
        for (s = 0; s < N_SUB; s++) begin
            // Global row index for this sub-column at the current r_idx.
            // If the sub-column is shorter than SUBCOL_ROWS (last one may
            // be partial), out-of-range indices are skipped.
            row = s * SUBCOL_ROWS + r_idx;
            if (row < N) begin
                act_bit_idx = K * row + k_idx;
                a = act_latched[act_bit_idx];
                for (c = 0; c < M; c++) begin
                    w_idx = row * M + c;
                    pos = HAS_VIA_POS[w_idx] & a;
                    neg = HAS_VIA_NEG[w_idx] & a;
                    if (pos) hits[c] = hits[c] + 1;
                    if (neg) hits[c] = hits[c] - 1;
                end
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            k_idx       <= '0;
            r_idx       <= '0;
            running     <= 1'b0;
            valid       <= 1'b0;
            act_latched <= '0;
            for (int j = 0; j < M; j++) acc[j] <= '0;
        end else begin
            valid <= 1'b0;
            if (start) begin
                act_latched <= act_flat;
                k_idx       <= '0;
                r_idx       <= '0;
                running     <= 1'b1;
                for (int j = 0; j < M; j++) acc[j] <= '0;
            end else if (running) begin
                // Accumulate this cycle's hit counts shifted by k_idx.
                for (int j = 0; j < M; j++) begin
                    acc[j] <= acc[j] + ($signed({{(WACC-HIT_W){hits[j][HIT_W-1]}}, hits[j]}) <<< k_idx);
                end

                // Advance state machine.
                if (r_idx == SUBCOL_ROWS - 1) begin
                    r_idx <= '0;
                    if (k_idx == K - 1) begin
                        valid   <= 1'b1;
                        running <= 1'b0;
                    end else begin
                        k_idx <= k_idx + 1'b1;
                    end
                end else begin
                    r_idx <= r_idx + 1'b1;
                end
            end
        end
    end

endmodule

`default_nettype wire
