// Parameterized behavioral model of one mask-programmed array chunk, for
// grid-level functional simulation. Each instance stands in for one
// hardened macro_array_pc_<MR>x<2*MC>_<chunk> block and loads its own
// programming from per-chunk memh (one MC-bit word per row: bit c set =>
// that column's weight is +1 (WPOS) / -1 (WNEG)).
//
// Contract (matching the hardened macro and rtl/chip/sim/macro_array_beh):
//   pre_n=0  -> precharge: every bitline high.
//   pre_n=1  -> the one-hot-selected row discharges its programmed
//               bitline (a +1 weight pulls blp low, a -1 pulls bln low);
//               unprogrammed and unselected columns hold high.
// The controller reads a discharged (low) bitline as a hit.
`default_nettype none

module cirom_array_beh #(
    parameter int MR = 8,
    parameter int MC = 4,
    parameter WPOS = "",
    parameter WNEG = ""
)(
    input  logic [MR-1:0] wl,
    input  logic          pre_n,
    output logic [MC-1:0] blp,
    output logic [MC-1:0] bln
);
    logic [MC-1:0] wpos [0:MR-1];
    logic [MC-1:0] wneg [0:MR-1];
    initial begin
        $readmemh(WPOS, wpos);
        $readmemh(WNEG, wneg);
    end

    integer r;
    always_comb begin
        blp = {MC{1'b1}};
        bln = {MC{1'b1}};
        if (pre_n) begin
            for (r = 0; r < MR; r = r + 1) begin
                if (wl[r]) begin
                    blp = ~wpos[r];   // +1 weight discharges blp for that column
                    bln = ~wneg[r];   // -1 weight discharges bln
                end
            end
        end
    end
endmodule

`default_nettype wire
