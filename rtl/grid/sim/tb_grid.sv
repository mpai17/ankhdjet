// Self-checking bench for an emitted grid top: loads N activations, runs
// the tiled matrix-vector multiply across the macro grid, and compares the
// M streamed results against a golden vector computed in the reference.
// N, M, and the top module name arrive as defines from the runner.
`timescale 1ns/1ps
`default_nettype none

`ifndef ANKHDJET_GRID_TOP
 `define ANKHDJET_GRID_TOP ankhdjet_grid
`endif

module tb_grid;
    localparam int N = `ANKHDJET_N;
    localparam int M = `ANKHDJET_M;

    logic clk = 0, rst_n = 0;
    logic [7:0] ui = '0;
    logic       act_wr = 0, start = 0;
    wire  [7:0] result;
    wire        result_valid, busy, done;

    `ANKHDJET_GRID_TOP dut (
        .clk(clk), .rst_n(rst_n), .ui(ui), .act_wr(act_wr), .start(start),
        .result(result), .result_valid(result_valid), .busy(busy), .done(done)
    );

    always #25 clk = ~clk;

    logic [7:0]  act    [0:N-1];
    logic [15:0] golden [0:M-1];
    logic [7:0]  rx     [0:2*M-1];
    logic [15:0] got;
    int          errors = 0;

    initial begin
        $readmemh("act.memh", act);
        $readmemh("golden.memh", golden);

        repeat (4) @(posedge clk);
        rst_n = 1;
        repeat (2) @(posedge clk);

        // load N activations, one per write
        for (int i = 0; i < N; i++) begin
            ui <= act[i]; act_wr <= 1'b1;
            @(posedge clk);
        end
        act_wr <= 1'b0;
        @(posedge clk);

        start <= 1'b1; @(posedge clk); start <= 1'b0;

        for (int k = 0; k < 2*M; ) begin
            @(posedge clk); #1;   // sample after the NBA region settles
            if (result_valid) begin rx[k] = result; k++; end
        end
        wait (done);

        for (int c = 0; c < M; c++) begin
            got = {rx[2*c+1], rx[2*c]};
            if (got !== golden[c]) begin
                errors++;
                $display("col %0d: got %0d expected %0d",
                         c, $signed(got), $signed(golden[c]));
            end
        end
        $display("grid MVM: %0d columns checked", M);
        if (errors == 0) $display("TB PASS"); else $display("TB FAIL: %0d", errors);
        $finish;
    end
endmodule

`default_nettype wire
