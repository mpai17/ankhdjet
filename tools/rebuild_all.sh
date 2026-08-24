#!/usr/bin/env bash
# Rebuild the full silicon stack from generators and re-verify:
#   precharge cell+row, bitcell array chain, mask programming per
#   weight set, macro, abstracts (LEF/lib/bb.v/LVS spice/memh), band
#   views, standalone macro netgen, and the functional regressions.
# The chip flow itself stays manual (run_librelane.sh) -- it takes
# ~15 min and an ECO-fill cycle; this script proves everything below
# it from sources.
#
# Usage: tools/rebuild_all.sh [weights ...]   (default: checker test0)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
WEIGHTS=("${@:-checker}")
[ $# -eq 0 ] && WEIGHTS=(checker test0)

export PDK_ROOT="${PDK_ROOT:-$HOME/.ciel}"
RC=$(find "$PDK_ROOT" -path '*magic*' -name "sky130A.magicrc" | head -1)
SETUP=$(find "$PDK_ROOT" -iname "sky130A_setup.tcl" -path "*netgen*" | head -1)
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="$ROOT/build/rebuild_${STAMP}.log"
mkdir -p "$ROOT/build"
exec > >(tee "$LOG") 2>&1
echo "== rebuild_all $STAMP  weights: ${WEIGHTS[*]} =="

mag() { # mag <dir> <script> [env k=v ...]
    local d=$1 s=$2; shift 2
    ( cd "$d/build" && env "$@" magic -dnull -noconsole -rcfile "$RC" < "../$s" ) \
        | grep -E "^(DRC=|BBOX=|WEIGHTS_FILE|PRECHARGE_ROW)" || true
}
expect_drc0() { # expect_drc0 <dir>/<script-tag> -- last DRC= in log slice
    :
}

echo "-- precharge cell + row --"
mag cell/sky130/precharge gen_precharge.tcl
mag cell/sky130/precharge gen_precharge_row.tcl ANKHDJET_PRECHARGE_N=32

echo "-- bitcell + tap + array + WL/BL routing --"
mag cell/sky130/bitcell_v4 gen_bitcell_v4.tcl
mag cell/sky130/bitcell_v4 gen_body_tap.tcl
mag cell/sky130/bitcell_v4 gen_array.tcl ANKHDJET_ARRAY_N=64 ANKHDJET_ARRAY_M=32
mag cell/sky130/bitcell_v4 gen_wl_routing_m1.tcl ANKHDJET_ARRAY_N=64 ANKHDJET_ARRAY_M=32
mag cell/sky130/bitcell_v4 gen_bl_routing.tcl ANKHDJET_ARRAY_N=64 ANKHDJET_ARRAY_M=32

for W in "${WEIGHTS[@]}"; do
    echo "-- weights: $W --"
    WF_ARGS=(ANKHDJET_ARRAY_N=64 ANKHDJET_ARRAY_M=32 ANKHDJET_WEIGHTS="$W")
    AB_ARGS=()
    if [ -f "$ROOT/weights/$W.wmat" ]; then
        WF_ARGS+=(ANKHDJET_WEIGHTS_FILE="$ROOT/weights/$W.wmat")
        AB_ARGS+=(--weights-file "$ROOT/weights/$W.wmat")
    fi
    mag cell/sky130/bitcell_v4 gen_mask_programming.tcl "${WF_ARGS[@]}"
    mag cell/sky130/macro gen_macro_array_pc.tcl "${WF_ARGS[@]}"
    uv run python3 macro/sky130/gen_abstracts.py 64 32 "$W" "${AB_ARGS[@]}" \
        | grep -E "wrote|bbox" | tail -2

    echo "-- standalone netgen: $W --"
    ( cd cell/sky130/macro/build && magic -dnull -noconsole -rcfile "$RC" <<EOT
load macro_array_pc_64x32_$W
flatten chk_$W
load chk_$W
extract do local
extract no capacitance
extract no coupling
extract no resistance
extract no adjust
extract unique
extract
ext2spice lvs
ext2spice cthresh infinite
ext2spice rthresh infinite
ext2spice subcircuit on
ext2spice -o chk_$W.spice
quit -noprompt
EOT
    ) > /dev/null 2>&1
    ( cd cell/sky130/macro/build && netgen -batch lvs \
        "chk_$W.spice chk_$W" \
        "$ROOT/macro/sky130/abstracts/macro_array_pc_64x32_$W.lvs.spice macro_array_pc_64x32_$W" \
        "$SETUP" "lvs_rebuild_$W.rpt" 2>&1 | grep -iE "match" | tail -1 )
done

echo "-- band views --"
uv run python3 cell/sky130/sense_se/build_band_klayout.py | tail -1
uv run python3 cell/sky130/sense_se/author_band_lef.py \
    cell/sky130/strongarm/build/sa_se_band16_kl.lef \
    cell/sky130/strongarm/build/sa_se_band16_kl_power.json \
    macro/sky130/abstracts/sa_se_band16.lef | tail -1
cp cell/sky130/strongarm/build/sa_se_band16_kl.gds macro/sky130/abstracts/sa_se_band16.gds
uv run python3 cell/sky130/sense_se/author_band_lib.py | tail -1

echo "-- band LVS (flat extract vs floating-substrate references) --"
for BN in 4 16; do
    [ "$BN" = 4 ] && ANKHDJET_BAND_N=4 uv run python3 cell/sky130/sense_se/build_band_klayout.py > /dev/null
    ( cd cell/sky130/strongarm/build && magic -dnull -noconsole -rcfile "$RC" <<EOT > /dev/null 2>&1
gds read sa_se_band${BN}_kl
load sa_se_band${BN}
extract do local
extract no capacitance
extract no coupling
extract no resistance
extract no adjust
extract
ext2spice lvs
ext2spice cthresh infinite
ext2spice rthresh infinite
ext2spice subcircuit on
ext2spice -o band${BN}_chk.spice
quit -noprompt
EOT
      netgen -batch lvs "band${BN}_chk.spice sa_se_band${BN}" \
        "$ROOT/cell/sky130/sense_se/band${BN}_reference.spice sa_se_band${BN}" \
        "$SETUP" "lvs_band${BN}_rebuild.rpt" 2>&1 | grep -iE "match" | tail -1 | sed "s/^/[band$BN] /" )
done

echo "-- functional regressions --"
for W in "${WEIGHTS[@]}"; do
    if [ -f "$ROOT/macro/sky130/abstracts/macro_array_pc_64x32_$W.wpos.memh" ]; then
        ARRAY=$W bash rtl/chip/sim/run_sim.sh 2>&1 | grep -E "^(PASS|FAIL)" | sed "s/^/[$W] /"
    fi
done

echo "== rebuild complete; log: $LOG =="
