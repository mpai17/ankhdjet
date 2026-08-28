#!/usr/bin/env bash
# Generate one programmed CiROM macro from a weight set: array + WL/BL routing +
# precharge row + mask programming + macro assembly + abstracts
# (LEF/lib/bb.v/LVS spice/memh) + standalone netgen LVS. Vehicle-agnostic and
# size-parametric -- this is the reusable unit every tapeout calls. Run the leaf
# cells first (tools/gen_cells.sh). Skips if this macro is already built this
# checkout (FORCE=1 to rebuild).
#
# Usage: tools/gen_macro.sh <rows N> <cols M> <name> [weights.wmat]
#   <name>          mask-program name (e.g. test0, checker).
#   [weights.wmat]  optional file of {+,-,0} chars, one per cell; omit for a
#                   built-in pattern (e.g. checker).
# Emits macro_array_pc_<N>x<M>_<name> (GDS + abstracts under macro/sky130/abstracts).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
[ $# -ge 3 ] || { echo "usage: tools/gen_macro.sh <N> <M> <name> [weights.wmat]"; exit 2; }
N=$1 M=$2 NAME=$3
WMAT="${4:-}"
if [ -n "$WMAT" ]; then
    [ -f "$WMAT" ] || { echo "ERROR: wmat not found: $WMAT"; exit 1; }
    WMAT=$(cd "$(dirname "$WMAT")" && pwd)/$(basename "$WMAT")
fi
source "$ROOT/tools/lib_silicon.sh"
MACRO="macro_array_pc_${N}x${M}_${NAME}"

if cached "$MACRO"; then echo "== gen_macro: $MACRO cached (FORCE=1 to rebuild) =="; exit 0; fi

echo "== gen_macro ${N}x${M} name=$NAME ${WMAT:+wmat=$WMAT} =="

echo "-- array + WL/BL routing + precharge row --"
mag cell/sky130/precharge  gen_precharge_row.tcl ANKHDJET_PRECHARGE_N="$M"
mag cell/sky130/bitcell_v4 gen_array.tcl         ANKHDJET_ARRAY_N="$N" ANKHDJET_ARRAY_M="$M"
mag cell/sky130/bitcell_v4 gen_wl_routing_m1.tcl ANKHDJET_ARRAY_N="$N" ANKHDJET_ARRAY_M="$M"
mag cell/sky130/bitcell_v4 gen_bl_routing.tcl    ANKHDJET_ARRAY_N="$N" ANKHDJET_ARRAY_M="$M"

echo "-- mask program + macro assembly + abstracts --"
WF=(ANKHDJET_ARRAY_N="$N" ANKHDJET_ARRAY_M="$M" ANKHDJET_WEIGHTS="$NAME")
[ -n "$WMAT" ] && WF+=(ANKHDJET_WEIGHTS_FILE="$WMAT")
mag cell/sky130/bitcell_v4 gen_mask_programming.tcl "${WF[@]}"
mag cell/sky130/macro      gen_macro_array_pc.tcl   "${WF[@]}"
if [ -n "$WMAT" ]; then
    uv run python3 macro/sky130/gen_abstracts.py "$N" "$M" "$NAME" --weights-file "$WMAT" | grep -E "wrote|bbox" | tail -2
else
    uv run python3 macro/sky130/gen_abstracts.py "$N" "$M" "$NAME" | grep -E "wrote|bbox" | tail -2
fi

echo "-- standalone netgen LVS --"
( cd cell/sky130/macro/build && magic -dnull -noconsole -rcfile "$RC" <<EOT
load $MACRO
flatten chk_$NAME
load chk_$NAME
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
ext2spice -o chk_$NAME.spice
quit -noprompt
EOT
) > /dev/null 2>&1
( cd cell/sky130/macro/build && netgen -batch lvs \
    "chk_$NAME.spice chk_$NAME" \
    "$ROOT/macro/sky130/abstracts/$MACRO.lvs.spice $MACRO" \
    "$SETUP" "lvs_$NAME.rpt" 2>&1 | grep -iE "match" | tail -1 )
mark_done "$MACRO"
echo "== gen_macro: $MACRO built =="
