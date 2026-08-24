#!/usr/bin/env bash
# Chip-level functional regression for the SKY130 chip tops, both
# readouts: iverilog + behavioral macro models, full row sweep checked
# against the selected weight matrix's memh views. TOP picks the
# readout (digital samplers or banded analog comparators), ARRAY the
# weight variant; writes a timestamped pass/fail log under build/.
set -uo pipefail

# ARRAY selects the weight variant (module + memh views); default checker.
# TOP selects the readout: bands (analog comparators) or digital (samplers).
ARRAY="${ARRAY:-checker}"
TOP="${TOP:-bands}"
DEFS="-DANKHDJET_ARRAY_MODULE=macro_array_pc_64x32_${ARRAY}"
DEFS="$DEFS -DANKHDJET_WEIGHTS_MEMH_BASE=\"macro/sky130/abstracts/macro_array_pc_64x32_${ARRAY}\""
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
BUILD="$HERE/build"
mkdir -p "$BUILD"
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="$BUILD/tb_cirom_chip_${TOP}_${ARRAY}_${STAMP}.log"

if [ "$TOP" = "digital" ]; then
    DEFS="$DEFS -DCIROM_DIGITAL"
    SRCS="$REPO/rtl/chip/cirom_chip_digital.sv $HERE/macro_array_beh.sv"
else
    SRCS="$REPO/rtl/chip/cirom_chip_analog.sv $HERE/macro_array_beh.sv $HERE/sa_se_band16_beh.sv"
fi
iverilog -g2012 $DEFS -DUSE_POWER_PINS -o "$BUILD/tb_cirom_chip.vvp" \
    -DRESULT_LOG="\"$LOG\"" \
    "$HERE/tb_cirom_chip.sv" \
    $SRCS || { echo "COMPILE FAIL" | tee "$LOG"; exit 1; }

vvp "$BUILD/tb_cirom_chip.vvp" | tee "$BUILD/tb_cirom_chip_${TOP}_${ARRAY}_${STAMP}.stdout"
grep -E "^(PASS|FAIL)" "$LOG" || { echo "no verdict in $LOG"; exit 1; }
echo "result log: $LOG"
