#!/usr/bin/env bash
# Full single-ended sense validation, run with LOW parallelism.
#
# Lesson learned: ngspice silently produces a DC-operating-point-only log
# (no transient, no .measure output) under core oversubscription, which
# looks like a sense failure but is an infrastructure artifact. Cap
# concurrency well below core count so every transient actually runs.
#
# Also: WEIGHT and VDD_V already exist as .param in the templates, so an
# override MUST sed-replace them in place -- a prepended ".param X=" does
# not win (ngspice takes the LAST definition = the template's). This was a
# real bug that made an entire earlier run read every w=0 case as w=1.
#
#   bash run_validation.sh                 # default 250 MC trials/weight
#   ANKHDJET_MC_TRIALS=1000 ANKHDJET_JOBS=4 bash run_validation.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
LIB="$HOME/.ciel/sky130A/libs.tech/ngspice/sky130.lib.spice"
OUT=build_val
TRIALS="${ANKHDJET_MC_TRIALS:-250}"
JOBS="${ANKHDJET_JOBS:-4}"
rm -rf "$OUT"; mkdir -p "$OUT"

# write_deck <out.sp> <corner> <tmpl> <weight> [vdd] [temp] [extra-header...]
write_deck () {
  local out="$1" corner="$2" tmpl="$3" weight="$4" vdd="${5:-}" temp="${6:-}"
  shift $(( $# < 6 ? $# : 6 ))
  {
    echo ".lib \"$LIB\" $corner"
    echo '.include "../sense_col_schematic.spice"'
    [ -n "$temp" ] && echo ".temp $temp"
    local e; for e in "$@"; do echo "$e"; done
    sed -E \
      -e "s/^\.param[[:space:]]+WEIGHT[[:space:]]*=.*/.param WEIGHT = $weight/" \
      ${vdd:+-e "s/^\.param[[:space:]]+VDD_V[[:space:]]*=.*/.param VDD_V = $vdd/"} \
      "$tmpl"
  } > "$out"
}

throttle () { while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n 2>/dev/null || sleep 0.2; done; }

echo "[1/4] dynamic per-corner (tt/ss/ff x w=1,0)"
for c in tt ss ff; do for w in 1 0; do
  d="$OUT/dyn_${c}_w${w}.sp"
  write_deck "$d" "$c" test_dynamic.sp "$w"
  throttle; ngspice -b -o "${d%.sp}.log" "$d" >/dev/null 2>&1 &
done; done; wait

echo "[2/4] divider-VREF per-corner (tt/ss/ff x w=1,0)"
for c in tt ss ff; do for w in 1 0; do
  d="$OUT/vd_${c}_w${w}.sp"
  write_deck "$d" "$c" test_vref_divider.sp "$w"
  throttle; ngspice -b -o "${d%.sp}.log" "$d" >/dev/null 2>&1 &
done; done; wait

echo "[3/4] V/T/process sweep (ss,ff x 1.62/1.80/1.98 x -40/25/125 x w=1,0)"
for c in ss ff; do for v in 1.62 1.80 1.98; do for t in -40 25 125; do for w in 1 0; do
  d="$OUT/vt_${c}_v${v}_t${t}_w${w}.sp"
  write_deck "$d" "$c" test_vref_divider.sp "$w" "$v" "$t"
  throttle; ngspice -b -o "${d%.sp}.log" "$d" >/dev/null 2>&1 &
done; done; done; done; wait

echo "[4/4] dynamic Monte Carlo, SS + mismatch, $TRIALS trials/weight (incl WEIGHT=0)"
for w in 1 0; do for s in $(seq 1 "$TRIALS"); do
  d="$OUT/dmc_w${w}_s${s}.sp"
  write_deck "$d" ss test_dynamic.sp "$w" "" "" ".param mc_mm_switch=1" ".option seed=$((s*7919))"
  throttle; ngspice -b -o "${d%.sp}.log" "$d" >/dev/null 2>&1 &
done; done; wait

echo "DONE -> $OUT  (parse with: uv run parse_results.py)"
