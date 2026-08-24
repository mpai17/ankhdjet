<!---
This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.
-->

## How it works

Azara CiROM is a mask-programmed **ternary compute-in-ROM** read demonstrator. Ternary weights (+1 / -1 / 0) are baked into a 64x32 1T NOR array: a cell places a discharge transistor on a column's `BLP` line for +1, on its `BLN` line for -1, or on neither for 0. The baked pattern is the seeded sparse `test0` matrix (500/513/1035 cells of +1/-1/0); the expected value of every row is the corresponding line of `weights/test0.wmat` in the Azara repo (one character per cell, columns 0..15 of each line are the sensed ones).

To read a row, the digital controller runs a **single-strobe, fully parallel** cycle: precharge all bitlines high, assert the one-hot wordline so the programmed cells discharge their bitlines, then pulse one shared strobe. A single-ended StrongARM sense amp on each of the 16 columns' `BLP`/`BLN` lines compares the bitline against a shared `VREF` (~VDD/2): `BLP` discharged => +1, `BLN` discharged => -1, neither => 0. All 32 hits latch at once and stream out as bytes on `uo_out`.

The analog front end (the array + 2 sense-amp bands) is a hardened custom GDS; the read controller is standard digital logic. `ua[0]` supplies `VREF` (required for reads, ~VDD/2); `ua[1]`/`ua[2]` probe the column-0 `BLP`/`BLN` bitlines.

## How to test

1. Reset (`rst_n` low, then high). Optionally shift a 16-bit config word in on `uio_in[0]` with `ui_in[7]` (cfg_mode) high to set the strobe/precharge timing.
2. Drive the row address on `ui_in[5:0]` and pulse `ui_in[6]` (start).
3. Watch `uio_out`: `busy` (bit 4) asserts, then `result_valid` (bit 3) with `result_byte` (bits 2:1) indexing each of the 4 output bytes on `uo_out`, and `done` (bit 5) at the end.
4. Reconstruct the row's 16 ternary weights from `{neg_hit, pos_hit}` across the 4 bytes.

`VREF` is REQUIRED: apply ~VDD/2 (0.9 V) on `ua[0]` (there is no on-die reference; the sense amps compare every bitline against this pin). `ua[1]`/`ua[2]` can be scoped to observe the column-0 bitline discharge. Note the probe wiring adds ~30-40 fF to column 0's bitlines, so column 0 discharges more slowly than columns 1-15: characterize the sense margin on column 0 (worst case) and treat columns 1-15 as the clean reference behavior.

## External hardware

A mid-rail voltage source (or a simple resistive divider) on `ua[0]` for `VREF` -- required for reads. A scope on `ua[1]`/`ua[2]` is optional, for characterizing the bitline discharge and sense margin.
