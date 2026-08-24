#!/usr/bin/env bash
# Structural elaboration gate for the AFE implementation (cirom_tt_afe_impl.sv):
# confirms it elaborates against the array/band macro blackboxes with the
# expected instance counts (1 array + 2 bands + 32 HIT buffers) and no
# errors. Persists a timestamped result log. Run from the repo root.
set -u
cd "$(dirname "$0")/../../.." || exit 1
OUT=rtl/tt_analog/sim/build; mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ); LOG="$OUT/afe_lint_${STAMP}.log"
LIB=$(find ~/.ciel -name "sky130_fd_sc_hd__tt_025C_1v80.lib" 2>/dev/null | head -1)
[ -z "$LIB" ] && { echo "no sky130 HD liberty found" | tee "$LOG"; exit 1; }
A=macro/sky130/abstracts
cat > "$OUT/afe_lint.ys" <<YS
read_liberty -lib $LIB
read_verilog -sv -DANKHDJET_SYNTH -DUSE_POWER_PINS $A/macro_array_pc_64x32_test0.bb.v $A/sa_se_band16.bb.v rtl/tt_analog/cirom_tt_afe_impl.sv
hierarchy -top cirom_tt_afe -check
stat
YS
yosys "$OUT/afe_lint.ys" > "$OUT/afe_lint_raw.txt" 2>&1
RC=$?
ARR=$(grep -E "macro_array_pc_64x32_test0$" "$OUT/afe_lint_raw.txt" | tail -1 | awk '{print $1}')
BND=$(grep -E "sa_se_band16$" "$OUT/afe_lint_raw.txt" | tail -1 | awk '{print $1}')
BUF=$(grep -E "buf_4$" "$OUT/afe_lint_raw.txt" | tail -1 | awk '{print $1}')
ERR=$(grep -ciE "^ERROR|syntax error|not found in module|is not part of" "$OUT/afe_lint_raw.txt")
{
  echo "AFE structural elaboration gate $STAMP"
  echo "  array=$ARR bands=$BND hitbufs=$BUF errors=$ERR rc=$RC"
  if [ "$RC" = "0" ] && [ "$ERR" = "0" ] && [ "$ARR" = "1" ] && [ "$BND" = "2" ] && [ "$BUF" = "32" ]; then
    echo "RESULT: PASS (1 array + 2 bands + 32 HIT buffers, no errors)"
  else echo "RESULT: FAIL"; fi
} | tee "$LOG"
echo "logged -> $LOG"