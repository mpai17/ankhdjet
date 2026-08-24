// Chip-level functional testbench serving both SKY130 chip tops:
// cirom_chip_digital (compile with -DCIROM_DIGITAL) or cirom_chip_analog
// (without it). Drives the read FSM through every row and checks the
// ternary readout against the selected mask program's memh views
// (sa_out_pos mirrors the w=+1 bits, sa_out_neg the w=-1 bits). Also
// checks the FSM contract: precharge happens with no WL asserted before
// every evaluate, valid is a single-cycle pulse, and outputs are stable
// while valid.
`timescale 1ns/1ps

`ifndef ANKHDJET_WEIGHTS_MEMH_BASE
`define ANKHDJET_WEIGHTS_MEMH_BASE "macro/sky130/abstracts/macro_array_pc_64x32_checker"
`endif
`default_nettype none

module tb_cirom_chip;

    reg         clk = 1'b0;
    reg         rst_n = 1'b0;
    reg         start = 1'b0;
    reg  [5:0]  wl_addr = 6'd0;
    reg         vref = 1'b1;       // analog reference; digitally a placeholder
    wire [31:0] sa_out_pos;
    wire [31:0] sa_out_neg;
    wire        valid;

    wire vpwr = 1'b1;
    wire vgnd = 1'b0;

`ifdef CIROM_DIGITAL
    cirom_chip_digital dut (
`ifdef USE_POWER_PINS
        .VPWR(vpwr), .VGND(vgnd),
`endif
        .clk(clk), .rst_n(rst_n), .start(start), .wl_addr(wl_addr),
        .sa_out_pos(sa_out_pos), .sa_out_neg(sa_out_neg),
        .valid(valid)
    );
    wire _unused_vref = vref;
`else
    cirom_chip_analog dut (
`ifdef USE_POWER_PINS
        .VPWR(vpwr), .VGND(vgnd),
`endif
        .clk(clk), .rst_n(rst_n), .start(start), .wl_addr(wl_addr),
        .vref(vref), .sa_out_pos(sa_out_pos), .sa_out_neg(sa_out_neg),
        .valid(valid)
    );
`endif

    always #12.5 clk = ~clk;   // 25ns cycle

    logic [31:0] exp_pos [0:63];
    logic [31:0] exp_neg [0:63];
    initial begin
        $readmemh({`ANKHDJET_WEIGHTS_MEMH_BASE, ".wpos.memh"}, exp_pos);
        $readmemh({`ANKHDJET_WEIGHTS_MEMH_BASE, ".wneg.memh"}, exp_neg);
    end

    integer errors = 0;
    integer checks = 0;
    integer fd;

    task automatic check(input bit cond, input string msg);
        begin
            checks = checks + 1;
            if (!cond) begin
                errors = errors + 1;
                $display("FAIL: %s (t=%0t)", msg, $time);
                $fdisplay(fd, "FAIL: %s (t=%0t)", msg, $time);
            end
        end
    endtask

    // FSM-contract monitors
    wire [63:0] wl_vec = {dut.wl_dec};
    integer valid_cycles;

    task automatic read_row(input integer r);
        integer wait_n;
        reg [31:0] pos_at_valid, neg_at_valid;
        begin
            @(negedge clk);
            wl_addr = r[5:0];
            start = 1'b1;
            @(negedge clk);
            start = 1'b0;

            // T0 (precharge) must present no asserted WL
            check(wl_vec == 64'd0, $sformatf("row %0d: WL asserted during precharge", r));

            // wait for valid (bounded)
            wait_n = 0;
            while (!valid && wait_n < 10) begin
                @(negedge clk);
                wait_n = wait_n + 1;
            end
            check(valid, $sformatf("row %0d: valid never asserted", r));

            pos_at_valid = sa_out_pos;
            neg_at_valid = sa_out_neg;
            check(pos_at_valid == exp_pos[r],
                  $sformatf("row %0d: sa_out_pos=%h expect=%h", r, pos_at_valid, exp_pos[r]));
            check(neg_at_valid == exp_neg[r],
                  $sformatf("row %0d: sa_out_neg=%h expect=%h", r, neg_at_valid, exp_neg[r]));

            // valid must be a single-cycle pulse
            @(negedge clk);
            check(!valid, $sformatf("row %0d: valid longer than one cycle", r));
            // outputs must not have changed after valid (held by the output registers)
            check(sa_out_pos == pos_at_valid && sa_out_neg == neg_at_valid,
                  $sformatf("row %0d: outputs changed after valid", r));
        end
    endtask

    integer r;
    initial begin
        fd = $fopen(`RESULT_LOG, "w");
        $fdisplay(fd, "# tb_cirom_chip run at %0t", $time);

        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        // sweep every row
        for (r = 0; r < 64; r = r + 1)
            read_row(r);

        // back-to-back reads of two different rows
        read_row(17);
        read_row(18);

        if (errors == 0) begin
            $display("PASS: %0d checks, 0 errors", checks);
            $fdisplay(fd, "PASS: %0d checks, 0 errors", checks);
        end else begin
            $display("FAIL: %0d of %0d checks failed", errors, checks);
            $fdisplay(fd, "FAIL: %0d of %0d checks failed", errors, checks);
        end
        $fclose(fd);
        $finish;
    end

endmodule

`default_nettype wire
