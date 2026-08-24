#!/usr/bin/env bash
# Behavioral regression for tt_um_darga_cirom (digital-tier tile: digital
# bitline sampling + on-die ternary MAC). Runs a full matrix-vector multiply
# and raw row reads against the checker pattern and a zero-heavy pattern,
# checking bit-exactness against a golden model computed from the same memh.
# Persists a timestamped result log. Run from anywhere.
set -u
cd "$(dirname "$0")/../../.." || exit 1
OUT=rtl/tt_digital/sim/build
mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG="$OUT/tt_um_digital_tb_${STAMP}.log"
SRC="rtl/tt_digital/tt_um_darga_cirom.sv rtl/tt_digital/cirom_dig_ctrl.sv rtl/tt_digital/sim/cirom_dig_afe_beh.sv rtl/chip/sim/macro_array_beh.sv rtl/tt_digital/sim/tb_tt_um_digital.sv"

run_one () {  # $1 = memh base, $2 = label
    iverilog -g2012 -DANKHDJET_WEIGHTS_MEMH_BASE="\"$1\"" -o "$OUT/ttdig.vvp" $SRC 2> "$OUT/ttdig_compile.log" \
        || { echo "$2: FAIL (compile)"; cat "$OUT/ttdig_compile.log"; return 1; }
    vvp "$OUT/ttdig.vvp" 2>&1 | grep -vE "readmem|VCD" | grep -E "checked|col|row|TB (PASS|FAIL)" | sed "s|^|$2: |"
}

# zero-heavy pattern (same generator as the analog tile's bench)
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
    echo "tt_um_darga_cirom (digital sense + on-die MAC) regression $STAMP"
    echo "---"
    run_one "macro/sky130/abstracts/macro_array_pc_64x32_checker" "checker(+/-1)"
    run_one "$BASE" "zero-heavy"
    echo "---"
} | tee "$LOG"
if grep -q "FAIL" "$LOG"; then echo "RESULT: FAIL" | tee -a "$LOG"; else echo "RESULT: PASS" | tee -a "$LOG"; fi
echo "logged -> $LOG"
