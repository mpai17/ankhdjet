// Self-checking bench for tt_um_darga_cirom: drives the TT pin contract
// through a full matrix-vector multiply and raw row reads, and compares
// against a golden model computed from the same weight memh files the
// behavioral array macro loads.
//
// Compile with -DANKHDJET_STREAM_ACTS to drive the streamed-activation
// variant (STORE_ACTS=0 tile): the MVM stimulus then re-streams the
// activation vector once per column-group pass (ANKHDJET_TB_PASSES,
// default 4) instead of loading the on-die store once.
`timescale 1ns/1ps
`default_nettype none

`ifndef ANKHDJET_TB_PASSES
 `define ANKHDJET_TB_PASSES 4
`endif
`ifndef ANKHDJET_TB_NCOLS
 `define ANKHDJET_TB_NCOLS 32
`endif

module tb_tt_um_digital;
    localparam int N_ROWS = 64;
    localparam int N_COLS = `ANKHDJET_TB_NCOLS;
    localparam int RAWB   = (2 * N_COLS + 7) / 8;   // raw-mode bytes

    logic clk = 0, rst_n = 0;
    logic [7:0] ui_in = '0, uio_in = '0;
    wire  [7:0] uo_out, uio_out, uio_oe;

    tt_um_darga_cirom dut (
        .ui_in(ui_in), .uo_out(uo_out),
        .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(1'b1), .clk(clk), .rst_n(rst_n)
    );

    always #25 clk = ~clk;   // 20 MHz

    wire result_valid = uio_out[5];
    wire done         = uio_out[7];

    // golden weights from the same memh files the macro loads
    logic [31:0] wpos [0:N_ROWS-1];
    logic [31:0] wneg [0:N_ROWS-1];
    initial begin
        $readmemh({`ANKHDJET_WEIGHTS_MEMH_BASE, ".wpos.memh"}, wpos);
        $readmemh({`ANKHDJET_WEIGHTS_MEMH_BASE, ".wneg.memh"}, wneg);
    end

    logic [3:0]  act [0:N_ROWS-1];
    logic [7:0]  rx  [0:127];
    int          errors = 0;

    task automatic cfg_load(input [15:0] word);
        for (int b = 15; b >= 0; b--) begin
            uio_in[3] <= 1'b1;         // cfg_mode
            uio_in[4] <= word[b];      // cfg_in
            @(posedge clk);
        end
        uio_in[3] <= 1'b0; uio_in[4] <= 1'b0;
        @(posedge clk);
    endtask

    task automatic load_acts();
        for (int i = 0; i < N_ROWS/2; i++) begin
            ui_in     <= {act[2*i+1], act[2*i]};
            uio_in[0] <= 1'b1;         // act_wr
            @(posedge clk);
        end
        uio_in[0] <= 1'b0;
        @(posedge clk);
    endtask

`ifdef ANKHDJET_STREAM_ACTS
    // streamed variant: one byte per row pair, re-sent every pass, paced
    // well below the consumption rate (the controller stalls when starved,
    // so slower is always safe)
    task automatic stream_acts_all_passes();
        for (int p = 0; p < `ANKHDJET_TB_PASSES; p++) begin
            for (int i = 0; i < N_ROWS/2; i++) begin
                repeat (4) @(posedge clk);
                ui_in     <= {act[2*i+1], act[2*i]};
                uio_in[0] <= 1'b1;     // act_wr
                @(posedge clk);
                uio_in[0] <= 1'b0;
                repeat (24) @(posedge clk);
            end
        end
    endtask
`endif

    task automatic pulse_start(input logic mode);
        uio_in[2] <= mode;
        uio_in[1] <= 1'b1;
        @(posedge clk);
        uio_in[1] <= 1'b0;
    endtask

    task automatic collect(input int nbytes);
        int k;
        k = 0;
        while (k < nbytes) begin
            @(posedge clk);
            if (result_valid) begin rx[k] = uo_out; k++; end
        end
        wait (done);
        @(posedge clk);
    endtask

    int signed   golden, got;
    logic [2*N_COLS-1:0] exp_hits, got_hits;

    initial begin
        // reset, then config: strobe_delay=2, pre_width=2
        repeat (4) @(posedge clk);
        rst_n = 1;
        repeat (2) @(posedge clk);
        cfg_load(16'h0022);

        // deterministic activation vector: act[r] = (r*7+3) mod 16
        for (int r = 0; r < N_ROWS; r++) act[r] = 4'((r*7 + 3) % 16);

        // full MVM
`ifdef ANKHDJET_STREAM_ACTS
        pulse_start(1'b0);
        fork
            stream_acts_all_passes();
            collect(2*N_COLS);
        join
`else
        load_acts();
        pulse_start(1'b0);
        collect(2*N_COLS);
`endif
        for (int c = 0; c < N_COLS; c++) begin
            golden = 0;
            for (int r = 0; r < N_ROWS; r++) begin
                if (wpos[r][c])      golden += int'(act[r]);
                else if (wneg[r][c]) golden -= int'(act[r]);
            end
            got = int'(signed'({rx[2*c+1], rx[2*c]}));
            if (got !== golden) begin
                errors++;
                $display("MVM col %0d: got %0d expected %0d", c, got, golden);
            end
        end
        $display("MVM: %0d columns checked", N_COLS);

        // raw row reads on a sample of rows; {neg_hit, pos_hit} streams low
        // byte first (RAWB bytes at N_COLS sensed columns)
        for (int r = 0; r < N_ROWS; r += 1) begin
            ui_in <= 8'(r);
            pulse_start(1'b1);
            collect(RAWB);
            exp_hits = {wneg[r][N_COLS-1:0], wpos[r][N_COLS-1:0]};
            got_hits = '0;
            for (int b = 0; b < RAWB; b++) got_hits |= (2*N_COLS)'(rx[b]) << (8*b);
            if (got_hits !== exp_hits) begin
                errors++;
                $display("raw row %0d: got %016x expected %016x", r, got_hits, exp_hits);
            end
        end
        $display("raw reads: all 64 rows checked");

        if (errors == 0) $display("TB PASS");
        else             $display("TB FAIL: %0d errors", errors);
        $finish;
    end
endmodule

`default_nettype wire
