// M-channel between-layer block: applies per-tensor scale + activation +
// K-bit unsigned quantization to the flat signed accumulator bus.
//
// Bus layout:
//   acc_flat: channel j at bits [WACC*(j+1)-1 -: WACC], signed
//   out_flat: channel j at bits [K*(j+1)-1 -: K],       unsigned

`default_nettype none

module between_layer #(
    parameter int M          = 16,
    parameter int WACC       = 24,
    parameter int SCALE_W    = 16,
    parameter int Q_FRAC     = 8,
    parameter int K          = 8,
    parameter [SCALE_W-1:0] SCALE_Q = {{(SCALE_W-1){1'b0}}, 1'b1} << Q_FRAC,
    parameter int ACTIVATION = 0
)(
    input  logic [WACC*M-1:0] acc_flat,
    output logic [K*M-1:0]    out_flat
);
    genvar j;
    generate
        for (j = 0; j < M; j = j + 1) begin : ch
            logic signed [WACC-1:0] acc_j;
            logic [K-1:0]           out_j;
            assign acc_j = $signed(acc_flat[WACC*(j+1)-1 -: WACC]);
            requantize #(
                .WACC      (WACC),
                .SCALE_W   (SCALE_W),
                .Q_FRAC    (Q_FRAC),
                .K         (K),
                .SCALE_Q   (SCALE_Q),
                .ACTIVATION(ACTIVATION)
            ) u_rq (
                .acc(acc_j),
                .out(out_j)
            );
            assign out_flat[K*(j+1)-1 -: K] = out_j;
        end
    endgenerate
endmodule

`default_nettype wire
