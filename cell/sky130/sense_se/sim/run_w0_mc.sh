#!/usr/bin/env bash
# Weight=0 dynamic MC only, 250 trials, SS + mismatch. Low parallelism.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
LIB="$HOME/.ciel/sky130A/libs.tech/ngspice/sky130.lib.spice"
OUT=build_w0; JOBS="${ANKHDJET_JOBS:-4}"; TRIALS="${ANKHDJET_MC_TRIALS:-250}"
rm -rf "$OUT"; mkdir -p "$OUT"

throttle () { while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n 2>/dev/null || sleep 0.2; done; }

for s in $(seq 1 "$TRIALS"); do
  d="$OUT/dmc_w0_s${s}.sp"
  { echo ".lib \"$LIB\" ss"
    echo '.include "../sense_col_schematic.spice"'
    echo ".param mc_mm_switch=1"
    echo ".option seed=$((s*7919))"
    sed -E "s/^\.param[[:space:]]+WEIGHT[[:space:]]*=.*/.param WEIGHT = 0/" test_dynamic.sp
  } > "$d"
  throttle; ngspice -b -o "${d%.sp}.log" "$d" >/dev/null 2>&1 &
done
wait
echo "W0_MC_DONE $(find "$OUT" -name 'dmc_w0_s*.log' | wc -l)/$TRIALS"
