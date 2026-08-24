// End-to-end behavioral test of tt_um_azara_cirom (signoff-mirror, no-mux
// full-parallel read) through its real TT pin contract. Loads config, reads
// all 64 rows -- each a single-strobe parallel sense of 16 columns -- captures
// the 4 streamed result bytes per row, reconstructs {neg_hit, pos_hit}, and
// checks against the selected weight memh views.
//
// Compile (repo root) WITH the behavioral AFE, NOT the blackbox:
//   iverilog -g2012 -o build/ttum.vvp \
//     rtl/tt_analog/tt_um_azara_cirom.sv rtl/tt_analog/cirom_tt_ctrl.sv \
//     rtl/tt_analog/sim/cirom_tt_afe_beh.sv rtl/chip/sim/macro_array_beh.sv \
//     rtl/tt_analog/sim/tb_tt_um.sv && vvp build/ttum.vvp
`default_nettype none
`timescale 1ns/1ps

`ifndef ANKHDJET_WEIGHTS_MEMH_BASE
`define ANKHDJET_WEIGHTS_MEMH_BASE "macro/sky130/abstracts/macro_array_pc_64x32_checker"
`endif

module tb_tt_um;
    localparam int N_COLS = 16;

    logic clk = 0, rst_n = 0, ena = 1;
    logic [7:0] ui_in = 0, uio_in = 0;
    wire  [7:0] uo_out, uio_out, uio_oe;

    always #5 clk = ~clk;

    tt_um_azara_cirom dut (
        .ui_in(ui_in), .uo_out(uo_out),
        .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(ena), .clk(clk), .rst_n(rst_n)
    );

    wire [1:0] result_byte  = uio_out[2:1];
    wire       result_valid = uio_out[3];
    wire       done         = uio_out[5];

    logic [31:0] wpos [0:63];
    logic [31:0] wneg [0:63];
    initial begin
        $readmemh({`ANKHDJET_WEIGHTS_MEMH_BASE, ".wpos.memh"}, wpos);
        $readmemh({`ANKHDJET_WEIGHTS_MEMH_BASE, ".wneg.memh"}, wneg);
    end

    logic [31:0] got;
    logic        capturing = 0;
    always @(posedge clk) if (capturing && result_valid)
        got[result_byte*8 +: 8] <= uo_out;

    task shift_cfg(input [15:0] v);
        ui_in[7] = 1;
        for (int i = 15; i >= 0; i--) begin uio_in[0] = v[i]; @(posedge clk); end
        ui_in[7] = 0; uio_in[0] = 0;
    endtask

    integer errors = 0, zeros = 0, pos = 0, neg = 0;

    task read_row(input [5:0] r);
        logic [31:0] golden;
        got = '0; capturing = 1;
        ui_in[5:0] = r; @(posedge clk);
        ui_in[6] = 1; @(posedge clk); ui_in[6] = 0;
        wait (done); @(posedge clk);
        capturing = 0;
        golden = {wneg[r][N_COLS-1:0], wpos[r][N_COLS-1:0]};   // {neg, pos}
        for (int c = 0; c < N_COLS; c++) begin
            if (wpos[r][c]) pos++; else if (wneg[r][c]) neg++; else zeros++;
        end
        if (got !== golden) begin
            errors++;
            $display("  ROW %0d MISMATCH got=%h golden=%h", r, got, golden);
        end
    endtask

    initial begin
        rst_n = 0; repeat (4) @(posedge clk); rst_n = 1; @(posedge clk);
        shift_cfg(16'h0011);                 // sd=1, pw=1 (timing irrelevant behaviorally)
        for (int r = 0; r < 64; r++) read_row(r[5:0]);
        $display("rows=64 cols=%0d weights: +1=%0d -1=%0d 0=%0d", N_COLS, pos, neg, zeros);
        if (errors == 0)
            $display("TB PASS: all 64 rows reconstruct through tt_um (signoff-mirror parallel read)");
        else
            $display("TB FAIL: %0d row mismatches", errors);
        $finish;
    end
endmodule

`default_nettype wire
