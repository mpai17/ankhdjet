// TinyTapeout read controller for the mask-programmed CiROM array, mirroring
// the signed-off chip's sense architecture (rtl/chip/cirom_chip_analog.sv):
// FULL-PARALLEL single-strobe read, NO mux. A one-hot wordline is asserted,
// every bitline develops, and ONE shared STROBE latches every single-ended
// sense amp against the shared VREF at once -- so the whole row's ternary
// values (pos_hit/neg_hit per column) are captured in a single cycle, exactly
// as the signed-off chip does. The only TinyTapeout-specific addition is
// DIGITAL serialization of the captured hits out the 8 output pins (off the
// analog sense path, so it adds no sense risk).
//
// Read of one row (mirrors signoff precharge/evaluate/strobe/hold):
//   WL[row] one-hot, PRE_N low for pre_width+1 cycles (precharge) ->
//   PRE_N high, wait strobe_delay+1 cycles (evaluate/develop) ->
//   STROBE high (all SAs latch pos_hit/neg_hit) -> hold ->
//   shift the 2*N_COLS captured hits out, OUT_W bits/cycle -> done.
//
// Config (strobe_delay, pre_width, bypass_pre) loads through a serial register:
// hold cfg_mode high and clock CFG_BITS bits in on cfg_in, MSB first.
`default_nettype none

module cirom_tt_ctrl #(
    parameter int N_ROWS   = 64,
    parameter int N_COLS   = 16,   // demonstrated columns (signoff array is 32)
    parameter int OUT_W    = 8,    // TT output byte width
    parameter int CFG_BITS = 16
)(
    input  logic                          clk,
    input  logic                          rst_n,
    // host command
    input  logic [$clog2(N_ROWS)-1:0]     row_addr,
    input  logic                          start,
    // serial config
    input  logic                          cfg_mode,
    input  logic                          cfg_in,
    // array + sense-amp interface (no mux; mirrors signoff)
    output logic [N_ROWS-1:0]             wl,
    output logic                          pre_n,
    output logic                          strobe,
    input  logic [N_COLS-1:0]             pos_hit,   // BLP discharged -> +1
    input  logic [N_COLS-1:0]             neg_hit,   // BLN discharged -> -1
    // serialized result out
    output logic [OUT_W-1:0]              result,
    output logic [$clog2((2*N_COLS+OUT_W-1)/OUT_W)-1:0] result_byte,
    output logic                          result_valid,
    output logic                          busy,
    output logic                          done
);
    localparam int NHIT  = 2 * N_COLS;                 // 32 hits (pos+neg)
    localparam int NBYTE = (NHIT + OUT_W - 1) / OUT_W; // 4 bytes
    localparam int BW    = $clog2(NBYTE);

    typedef enum logic [2:0] {
        S_IDLE, S_PRECHG, S_EVAL, S_STROBE, S_HOLD, S_SHIFT, S_DONE
    } state_t;
    state_t state, next;

    logic [CFG_BITS-1:0] cfg_reg;
    wire  [3:0] cfg_strobe_delay = cfg_reg[3:0];
    wire  [3:0] cfg_pre_width    = cfg_reg[7:4];
    wire        cfg_bypass_pre   = cfg_reg[8];

    logic [$clog2(N_ROWS)-1:0] row_q;
    logic [3:0]      cnt;            // precharge / evaluate down-counter
    logic [NHIT-1:0] captured;       // {neg_hit, pos_hit} latched at strobe
    logic [BW-1:0]   byte_q;         // serialize index
    wire             last_byte = (byte_q == BW'(NBYTE-1));

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) cfg_reg <= '0;
        else if (cfg_mode) cfg_reg <= {cfg_reg[CFG_BITS-2:0], cfg_in};
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; row_q <= '0; cnt <= '0;
            captured <= '0; byte_q <= '0;
        end else begin
            state <= next;
            case (state)
                S_IDLE:   if (start) begin row_q <= row_addr; cnt <= cfg_pre_width; end
                S_PRECHG: if (cnt != 0) cnt <= cnt - 4'd1; else cnt <= cfg_strobe_delay;
                S_EVAL:   if (cnt != 0) cnt <= cnt - 4'd1;
                S_STROBE: captured <= {neg_hit, pos_hit};   // full-parallel latch
                S_HOLD:   byte_q <= '0;
                S_SHIFT:  if (!last_byte) byte_q <= byte_q + BW'(1);
                default:  ;
            endcase
        end
    end

    always_comb begin
        next = state;
        case (state)
            S_IDLE:   if (start)          next = S_PRECHG;
            S_PRECHG: if (cfg_bypass_pre) next = S_EVAL;
                      else if (cnt == 0)  next = S_EVAL;
            S_EVAL:   if (cnt == 0)       next = S_STROBE;
            S_STROBE:                     next = S_HOLD;
            S_HOLD:                       next = S_SHIFT;
            S_SHIFT:  if (last_byte)      next = S_DONE;
            S_DONE:                       next = S_IDLE;
            default:                      next = S_IDLE;
        endcase
    end

    wire active = (state != S_IDLE) && (state != S_DONE);
    always_comb begin
        wl           = '0;
        pre_n        = 1'b1;
        strobe       = 1'b0;
        result       = '0;
        result_byte  = '0;
        result_valid = 1'b0;
        busy         = active;
        done         = (state == S_DONE);
        // WL held one-hot through precharge..hold (as signoff holds WL across
        // evaluate+strobe); released for shift-out and idle.
        if (state == S_PRECHG || state == S_EVAL || state == S_STROBE || state == S_HOLD)
            wl[row_q] = 1'b1;
        if (state == S_PRECHG && !cfg_bypass_pre) pre_n = 1'b0;
        if (state == S_STROBE) strobe = 1'b1;
        if (state == S_SHIFT) begin
            result       = captured[byte_q*OUT_W +: OUT_W];
            result_byte  = byte_q;
            result_valid = 1'b1;
        end
    end

endmodule

`default_nettype wire
