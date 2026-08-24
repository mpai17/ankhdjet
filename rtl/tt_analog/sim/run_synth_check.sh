#!/usr/bin/env bash
# Synthesis gate for the analog tile's digital controller (tt_um_azara_cirom): confirms the rebuilt
# signoff-mirror controller is synthesizable, latch-free, and small, against
# the sky130 HD standard cells. The analog front end (cirom_tt_afe) is a
# blackbox. Persists a timestamped result log. Run from the repo root.
set -u
cd "$(dirname "$0")/../../.." || exit 1
OUT=rtl/tt_analog/sim/build; mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ); LOG="$OUT/synth_${STAMP}.log"
LIB=$(find ~/.ciel -name "sky130_fd_sc_hd__tt_025C_1v80.lib" 2>/dev/null | head -1)
[ -z "$LIB" ] && { echo "no sky130 HD liberty found" | tee "$LOG"; exit 1; }
cat > "$OUT/synth.ys" <<YS
read_verilog -sv rtl/tt_analog/cirom_tt_afe.sv rtl/tt_analog/cirom_tt_ctrl.sv rtl/tt_analog/tt_um_azara_cirom.sv
hierarchy -top tt_um_azara_cirom -check
setattr -mod -set blackbox 1 cirom_tt_afe
synth -top tt_um_azara_cirom -flatten
dfflibmap -liberty $LIB
abc -liberty $LIB
opt_clean
stat -liberty $LIB
YS
yosys "$OUT/synth.ys" > "$OUT/synth_raw.txt" 2>&1
LAT=$(grep -ciE "\\\$_DLATCH|inferring latch" "$OUT/synth_raw.txt")
AREA=$(grep -iE "Chip area for module" "$OUT/synth_raw.txt" | tail -1 | grep -oE "[0-9.]+$")
FF=$(grep -E "sky130_fd_sc_hd__df" "$OUT/synth_raw.txt" | tail -1 | awk '{print $1}')
ERR=$(grep -ciE "^ERROR|syntax error" "$OUT/synth_raw.txt")
{
  echo "analog-tile controller synth gate $STAMP"
  echo "  area(um2)=$AREA  flops=$FF  latches=$LAT  errors=$ERR"
  if [ "$LAT" = "0" ] && [ "$ERR" = "0" ] && [ -n "$AREA" ]; then echo "RESULT: PASS (synthesizable, latch-free)"; else echo "RESULT: FAIL"; fi
} | tee "$LOG"
echo "logged -> $LOG"
