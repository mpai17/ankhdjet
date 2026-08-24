// Per-channel requantize: signed accumulator -> K-bit unsigned activation.
//
// Datapath (combinational):
//   product = acc * SCALE_Q              signed (WACC + SCALE_W) bits
//   shifted = product >>> Q_FRAC         arithmetic shift right
//   if ACTIVATION==0 (relu): shifted = max(shifted, 0)
//   out     = clip(shifted, 0, 2**K - 1)
//
// SCALE_Q is unsigned Q(SCALE_W - Q_FRAC).Q_FRAC fixed-point; for unit scale
// set SCALE_Q = (1 << Q_FRAC).

`default_nettype none

module requantize #(
    parameter int WACC       = 24,
    parameter int SCALE_W    = 16,
    parameter int Q_FRAC     = 8,
    parameter int K          = 8,
    parameter [SCALE_W-1:0] SCALE_Q = {{(SCALE_W-1){1'b0}}, 1'b1} << Q_FRAC,
    parameter int ACTIVATION = 0
)(
    input  logic signed [WACC-1:0] acc,
    output logic [K-1:0]           out
);
    localparam int WFULL        = WACC + SCALE_W;
    localparam int MAX_UNSIGNED = (1 << K) - 1;

    logic signed [WFULL-1:0] product;
    logic signed [WFULL-1:0] shifted_full;
    logic signed [WFULL-1:0] activated;
    logic signed [WFULL-1:0] clipped;

    always_comb begin
        product      = acc * $signed({1'b0, SCALE_Q});
        shifted_full = product >>> Q_FRAC;

        if (ACTIVATION == 0 && shifted_full < 0)
            activated = '0;
        else
            activated = shifted_full;

        if (activated > $signed(MAX_UNSIGNED))
            clipped = MAX_UNSIGNED;
        else if (activated < $signed('0))
            clipped = '0;
        else
            clipped = activated;
    end

    assign out = clipped[K-1:0];

endmodule

`default_nettype wire
