#!/usr/bin/env bash
# Behavioral regression for tt_um_azara_cirom (signoff-mirror, no-mux parallel
# read). Runs the checker pattern (all +/-1) and a generated zero-heavy pattern
# (exercises the zero decode: neither pos_hit nor neg_hit), reading all 64 rows
# through the TT pin contract. Persists a timestamped result log. Run from repo root.
set -u
cd "$(dirname "$0")/../../.." || exit 1
OUT=rtl/tt_analog/sim/build
mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG="$OUT/tt_um_tb_${STAMP}.log"
SRC="rtl/tt_analog/tt_um_azara_cirom.sv rtl/tt_analog/cirom_tt_ctrl.sv rtl/tt_analog/sim/cirom_tt_afe_beh.sv rtl/chip/sim/macro_array_beh.sv rtl/tt_analog/sim/tb_tt_um.sv"

run_one () {  # $1 = memh base, $2 = label
    iverilog -g2012 -DANKHDJET_WEIGHTS_MEMH_BASE="\"$1\"" -o "$OUT/ttum.vvp" $SRC 2> "$OUT/ttum_compile.log" \
        || { echo "$2: FAIL (compile)"; cat "$OUT/ttum_compile.log"; return 1; }
    vvp "$OUT/ttum.vvp" 2>&1 | grep -vE "readmem|VCD" | grep -E "rows=|TB (PASS|FAIL)" | sed "s|^|$2: |"
}

# zero-heavy pattern (~50% zeros, 25% +1, 25% -1) for the macro + golden
BASE="$OUT/beh_test"
uv run python3 - "$BASE" <<'PYEOF'
import sys
b=sys.argv[1]; wpos=[]; wneg=[]
for r in range(64):
    p=n=0
    for c in range(32):
        m=(r*131+c*17+7)%4
        if m==1: p|=1<<c
        elif m==2: n|=1<<c
    wpos.append(f"{p:08x}"); wneg.append(f"{n:08x}")
open(b+".wpos.memh","w").write("\n".join(wpos)+"\n")
open(b+".wneg.memh","w").write("\n".join(wneg)+"\n")
PYEOF

{
    echo "tt_um_azara_cirom (signoff-mirror, no-mux parallel read) regression $STAMP"
    echo "---"
    run_one "macro/sky130/abstracts/macro_array_pc_64x32_checker" "checker(+/-1)"
    run_one "$BASE" "zero-heavy"
    echo "---"
} | tee "$LOG"
if grep -q "FAIL" "$LOG"; then echo "RESULT: FAIL" | tee -a "$LOG"; else echo "RESULT: PASS" | tee -a "$LOG"; fi
echo "logged -> $LOG"
