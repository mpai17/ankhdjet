#!/usr/bin/env bash
# Block-scale ASAP7 anchor: floorplan + place + CTS + STA of a CiROM
# block slice (hard-macro abstract + the generated wrapper) through the
# ORFS container's native asap7 platform. Extends the anchor methodology
# from controller-scale synthesis to placed-and-clocked block scale.
#
#   tools/openroad/run_asap7_block.sh [rows] [cols] [stage]
#   default: 2560 256 cts
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
ROWS="${1:-2560}"
COLS="${2:-256}"
STAGE="${3:-cts}"
STEM="cirom_array_${ROWS}x${COLS}_asap7"
NAME="cirom_array_${ROWS}x${COLS}"

cd "$REPO"
uv run python macro/sky130/gen_anchor_abstracts.py "$ROWS" "$COLS" --pdk asap7

WORK="$REPO/build/asap7_block/${ROWS}x${COLS}"
DSN="$WORK/design"
mkdir -p "$DSN" "$WORK/out"
cp "macro/sky130/build/${STEM}.lef" "$DSN/"
cp "macro/sky130/build/${STEM}.lib" "$DSN/"
cp "macro/sky130/build/${STEM}_wrapper.sv" "$DSN/wrapper.sv"

# Die box: macro footprint plus wrapper margin (asap7 rows are 0.27 um;
# the wrapper is a few hundred cells).
read -r MW MH < <(awk '/^  SIZE / {print $2, $4}' "$DSN/${STEM}.lef")
DIE_W=$(python3 -c "print(f'{$MW + 20:.2f}')")
DIE_H=$(python3 -c "print(f'{$MH + 20:.2f}')")
CORE_W=$(python3 -c "print(f'{$MW + 18:.2f}')")
CORE_H=$(python3 -c "print(f'{$MH + 18:.2f}')")

cat > "$DSN/constraint.sdc" <<SDC
create_clock -name clk -period 700 [get_ports clk]
set_input_delay 50 -clock clk [all_inputs]
set_output_delay 50 -clock clk [all_outputs]
SDC

cat > "$DSN/config.mk" <<MK
export DESIGN_NICKNAME = cirom_block
export DESIGN_NAME     = ${NAME}_test_harness
export PLATFORM        = asap7
export VERILOG_FILES   = \$(DESIGN_HOME)/asap7/cirom_block/wrapper.sv
export SDC_FILE        = \$(DESIGN_HOME)/asap7/cirom_block/constraint.sdc
export ADDITIONAL_LEFS = \$(DESIGN_HOME)/asap7/cirom_block/${STEM}.lef
export ADDITIONAL_LIBS = \$(DESIGN_HOME)/asap7/cirom_block/${STEM}.lib
export DIE_AREA        = 0 0 ${DIE_W} ${DIE_H}
export CORE_AREA       = 1 1 ${CORE_W} ${CORE_H}
export PLACE_DENSITY   = 0.40
export MACRO_PLACE_HALO = 2 2
export TNS_END_PERCENT = 100
MK

# ORFS through detailed placement only (the container's post-CTS
# detailed_placement SIGILLs on Zen 3, per the anchor harness), then the
# harness's own CTS+STA script on the placed database.
cp "$REPO/tools/openroad/run_cts_sta.tcl" "$WORK/run_cts_sta.tcl"
LIBS="/OpenROAD-flow-scripts/flow/platforms/asap7/lib/NLDM/asap7sc7p5t_AO_RVT_TT_nldm_211120.lib.gz /OpenROAD-flow-scripts/flow/platforms/asap7/lib/NLDM/asap7sc7p5t_INVBUF_RVT_TT_nldm_220122.lib.gz /OpenROAD-flow-scripts/flow/platforms/asap7/lib/NLDM/asap7sc7p5t_OA_RVT_TT_nldm_211120.lib.gz /OpenROAD-flow-scripts/flow/platforms/asap7/lib/NLDM/asap7sc7p5t_SEQ_RVT_TT_nldm_220123.lib /OpenROAD-flow-scripts/flow/platforms/asap7/lib/NLDM/asap7sc7p5t_SIMPLE_RVT_TT_nldm_211120.lib.gz /OpenROAD-flow-scripts/flow/designs/asap7/cirom_block/${STEM}.lib"

echo "== ORFS asap7 ${NAME} -> place + local CTS/STA (die ${DIE_W}x${DIE_H} um)"
docker run --rm \
    -v "$DSN":/OpenROAD-flow-scripts/flow/designs/asap7/cirom_block:ro \
    -v "$WORK":/work \
    -v "$WORK/out":/out \
    -e WORK_HOME=/out \
    openroad/orfs:latest \
    bash -c "set -e
make -C /OpenROAD-flow-scripts/flow DESIGN_CONFIG=designs/asap7/cirom_block/config.mk /out/results/asap7/cirom_block/base/3_5_place_dp.odb
ANKHDJET_PLACED_ODB=/out/results/asap7/cirom_block/base/3_5_place_dp.odb \
ANKHDJET_SDC=/out/results/asap7/cirom_block/base/2_1_floorplan.sdc \
ANKHDJET_LIBS=\"$LIBS\" \
ANKHDJET_OUT_DIR=/out \
ANKHDJET_PS_TO_NS=0.001 \
ANKHDJET_CTS_BUF_LIST=\"BUFx2_ASAP7_75t_R BUFx4_ASAP7_75t_R BUFx12_ASAP7_75t_R\" \
/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad -no_init -exit /work/run_cts_sta.tcl" \
    2>&1 | tee "$WORK/orfs_${STAGE}.log" | tail -20

echo "== reports:"
grep -E "achieved|fmax|slack|skew|area" "$WORK/out/openroad.log" 2>/dev/null | tail -8
