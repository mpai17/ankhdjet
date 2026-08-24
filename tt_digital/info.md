<!---
This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.
-->

## How it works

Darga reads a mask-programmed **ternary compute-in-ROM** array fully digitally and computes matrix-vector products on die. Ternary weights (+1 / -1 / 0) are baked into a 64x32 1T NOR array: a cell places a discharge transistor on a column's `BLP` line for +1, on its `BLN` line for -1, or on neither for 0. The baked pattern is the seeded sparse `test0` matrix, the **same mask program as the Azara CiROM analog tile** on this shuttle: the two tiles are a controlled experiment in readout style, identical array and weights, analog comparator sense versus this tile's digital sampling.

To read a row the controller precharges all 64 bitlines high, asserts the one-hot wordline so the programmed cells discharge their bitlines, waits a configured strobe delay, then samples every bitline into a standard-cell flop. A discharged `BLP` reads +1, a discharged `BLN` reads -1, neither reads 0. There is no comparator, no reference voltage, and no analog pin: full-swing sampling replaces the entire sense subsystem.

On top of the readout sits an on-die **ternary MAC**: the host streams a 64-element vector of 4-bit activation magnitudes, and for each row the sampled weight sign adds, subtracts, or skips the activation in 12-bit accumulators (4 accumulators covering the 32 columns in 8 passes). This is the first vehicle in the Ankhdjet series that computes dot products on silicon.

## How to test

1. Reset (`rst_n` low, then high). Optionally shift a 16-bit config word in on `uio_in[4]` (cfg_in) with `uio_in[3]` (cfg_mode) high: bits [3:0] strobe delay, [7:4] precharge width, [8] precharge bypass; reset defaults are the fastest timing.
2. **Matrix-vector multiply** (`uio_in[2]` = 0): pulse `uio_in[1]` (start), then stream the activation vector one byte per row pair on `ui_in` with `uio_in[0]` (act_wr) high, low nibble = even row; the vector is re-sent for each of the 8 column-group passes, and the controller stalls when starved, so any slower host is safe. After each pass, watch `uio_out[5]` (result_valid): the pass's 4 accumulators stream on `uo_out` as 2 bytes each, low byte first, 64 result bytes total in ascending column order. `uio_out[7]` (done) marks the end.
3. **Raw row read** (`uio_in[2]` = 1): drive the row address on `ui_in[5:0]` and pulse start; 8 bytes of `{neg_hit, pos_hit}` stream out, reproducing the analog tile's readout on the shared 16 columns and extending it to all 32.
4. Check results against the golden model: every row's expected weights are the corresponding line of `weights/test0.wmat` in the Ankhdjet repo, and an MVM's expected value is that matrix times the streamed vector. Sweep the clock to map the read-timing margin.

## External hardware

None: the tile is fully digital. A microcontroller or the demo board streams activations and compares results against the golden model.
