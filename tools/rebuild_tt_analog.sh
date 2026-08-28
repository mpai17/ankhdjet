#!/usr/bin/env bash
# LEGACY: rebuild the submitted Azara (tt_um_azara_cirom) ANALOG vehicle from
# sources by orchestrating the reusable generators. The analog StrongARM readout
# is retired for FUTURE tapeouts; this script is kept only to reproduce the
# already-submitted analog tile: leaf cells + the submitted 64x32 test0 macro +
# the analog sense band + the functional regression. New work uses
# tools/rebuild_tt_digital.sh / tools/gen_macro.sh directly. The tile itself is
# hardened separately by librelane/cirom_chip_analog/run_librelane.sh.
# Sub-steps skip if already built this checkout (FORCE=1 to rebuild everything).
#
# Usage: tools/rebuild_tt_analog.sh                # submitted config (test0)
#        tools/rebuild_tt_analog.sh <name> [wmat]  # override for dev
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
NAME=${1:-test0}
WMAT=${2:-weights/$NAME.wmat}
mkdir -p build
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="build/rebuild_tt_analog_${STAMP}.log"
exec > >(tee "$LOG") 2>&1
echo "== rebuild_tt_analog (LEGACY) $STAMP  name=$NAME =="

bash tools/gen_cells.sh
if [ -f "$WMAT" ]; then
    bash tools/gen_macro.sh 64 32 "$NAME" "$WMAT"
else
    bash tools/gen_macro.sh 64 32 "$NAME"
fi
bash tools/gen_band.sh

echo "-- functional regression --"
if [ -f "macro/sky130/abstracts/macro_array_pc_64x32_$NAME.wpos.memh" ]; then
    ARRAY=$NAME bash rtl/chip/sim/run_sim.sh 2>&1 | grep -E "^(PASS|FAIL)" | sed "s/^/[$NAME] /"
fi
echo "== rebuild_tt_analog complete; log: $LOG =="
