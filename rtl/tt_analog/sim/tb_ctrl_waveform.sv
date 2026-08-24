// Dumps the signoff-arch cirom_tt_ctrl control waveform (PRE_N, WL[0], WL[1],
// STROBE) to a VCD so the mixed-signal confirm can drive the extracted analog
// with the REAL (rebuilt, no-mux) controller's timing. pos_hit/neg_hit are
// tied off (they don't affect the controller's timing). Reading row 0 then
// row 1 gives a +1 and a -1 column-0 read against the extracted macro + SAs.
`default_nettype none
`timescale 1ns/1ps

`ifndef TCLK
`define TCLK 15.0
`endif
`ifndef CFGVAL
`define CFGVAL 17   // 0x11: strobe_delay=1, pre_width=1 -> 30ns precharge/eval at 15ns
`endif

module tb_ctrl_waveform;
    logic clk = 0, rst_n = 0;
    logic [5:0] row_addr = 0;
    logic start = 0, cfg_mode = 0, cfg_in = 0;
    wire [63:0] wl;
    wire        pre_n, strobe;
    logic [15:0] pos_hit = '0, neg_hit = '0;
    wire [7:0]  result;
    wire [1:0]  result_byte;
    wire        result_valid, busy, done;

    always #(`TCLK/2.0) clk = ~clk;

    cirom_tt_ctrl #(.N_ROWS(64), .N_COLS(16)) dut (
        .clk(clk), .rst_n(rst_n), .row_addr(row_addr), .start(start),
        .cfg_mode(cfg_mode), .cfg_in(cfg_in),
        .wl(wl), .pre_n(pre_n), .strobe(strobe),
        .pos_hit(pos_hit), .neg_hit(neg_hit),
        .result(result), .result_byte(result_byte),
        .result_valid(result_valid), .busy(busy), .done(done)
    );

    // analog-driving nets (names match the VCD parser: pre_n_w/wl0_w/wl1_w/strobe_w)
    wire pre_n_w  = pre_n;
    wire wl0_w    = wl[0];
    wire wl1_w    = wl[1];
    wire strobe_w = strobe;

    task shift_cfg(input [15:0] v);
        cfg_mode = 1;
        for (int i = 15; i >= 0; i--) begin cfg_in = v[i]; @(posedge clk); end
        cfg_mode = 0; cfg_in = 0;
    endtask

    task read_row(input [5:0] r);
        row_addr = r; @(posedge clk);
        start = 1; @(posedge clk); start = 0;
        wait (done); @(posedge clk);
    endtask

    initial begin
        $dumpfile("rtl/tt_analog/sim/build/ctrl_wave.vcd");
        $dumpvars(0, tb_ctrl_waveform);
        rst_n = 0; repeat (4) @(posedge clk); rst_n = 1; @(posedge clk);
        shift_cfg(16'(`CFGVAL));
        read_row(0);          // col 0 = +1 -> BLP_0 discharges
        read_row(1);          // col 0 = -1 -> BLN_0 discharges
        repeat (4) @(posedge clk);
        $finish;
    end
endmodule

`default_nettype wire
