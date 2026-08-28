#!/usr/bin/env bash
# Rebuild the submitted Darga (tt_um_darga_cirom) DIGITAL vehicle from sources:
# leaf cells + the programmed macro at the submitted 64x32 test0 shape + the
# digital functional regression. The default reproduces the submission exactly.
# The tile itself is emitted and hardened separately by
# librelane/tt_digital/run_tile.sh (weights=test0, n_cols=32, n_acc=4,
# store_acts=0). Digital readout only; no analog band.
#
# Usage: tools/rebuild_tt_digital.sh                # submitted config (test0)
#        tools/rebuild_tt_digital.sh <name> [wmat]  # override for dev
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
NAME=${1:-test0}
WMAT=${2:-weights/$NAME.wmat}
source "$ROOT/tools/lib_silicon.sh"
STAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p build
LOG="build/rebuild_tt_digital_${STAMP}.log"
exec > >(tee "$LOG") 2>&1
echo "== rebuild_tt_digital $STAMP  name=$NAME =="

bash tools/gen_cells.sh
if [ -f "$WMAT" ]; then
    bash tools/gen_macro.sh 64 32 "$NAME" "$WMAT"
else
    bash tools/gen_macro.sh 64 32 "$NAME"
fi

echo "-- functional regression --"
if [ -f "macro/sky130/abstracts/macro_array_pc_64x32_$NAME.wpos.memh" ]; then
    ARRAY=$NAME bash rtl/chip/sim/run_sim.sh 2>&1 | grep -E "^(PASS|FAIL)" | sed "s/^/[$NAME] /"
fi
echo "== rebuild_tt_digital complete; log: $LOG =="
