#!/usr/bin/env bash
# Digital power report for the analog tile's controller (tt_um_azara_cirom minus the
# analog macros): OpenSTA report_power on the final routed netlist + nom SPEF
# at the nominal corner, VECTORLESS (default input activity 0.1, resets held
# quiet) -- label any quoted number as such. The AFE macros contribute only
# their Liberty pin loads here; analog read energy comes from the ngspice
# energy sweep (cell/sky130/macro/sim_a2/run_energy.py), not this report.
# Persists a timestamped result log. Run from the repo root.
set -u
cd "$(dirname "$0")/../../.." || exit 1
OUT=rtl/tt_analog/sim/build; mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ); LOG="$OUT/power_${STAMP}.log"
RUN=librelane/tt_analog/runs/tile62
LIB=$(find ~/.ciel -name "sky130_fd_sc_hd__tt_025C_1v80.lib" 2>/dev/null | head -1)
SPEF=$(find "$RUN/final/spef/nom" -name "*.spef" | head -1)
[ -z "$LIB" ] || [ -z "$SPEF" ] && { echo "missing lib or spef" | tee "$LOG"; exit 1; }
A=macro/sky130/abstracts
cat > "$OUT/power.tcl" <<TCL
read_liberty $LIB
read_liberty $A/sa_se_band16.lib
read_liberty $A/macro_array_pc_64x32_test0.lib
read_verilog $RUN/final/nl/tt_um_azara_cirom.nl.v
link_design tt_um_azara_cirom
read_spef $SPEF
create_clock -period 25 [get_ports clk]
set_power_activity -input -activity 0.1
set_power_activity -input_port rst_n -activity 0
report_power
exit
TCL
build/opensta/bin/sta -no_splash -exit "$OUT/power.tcl" > "$OUT/power_raw.txt" 2>&1
RC=$?
{
  echo "Digital power report: tt_um_azara_cirom (tile62 final nl + nom spef, tt/25C/1.80V)"
  echo "Method: OpenSTA report_power, VECTORLESS (input activity 0.1, rst quiet),"
  echo "clock 25ns. Analog macro internals are NOT modeled here (Liberty loads only)."
  echo ""
  grep -A20 "Group.*Internal\|^Total\|Sequential\|Combinational\|Clock\|Macro\|Pad" "$OUT/power_raw.txt" | head -30
  echo ""
  if [ $RC -eq 0 ] && grep -q "^Total" "$OUT/power_raw.txt"; then
    echo "RESULT: PASS (report generated)"
  else
    echo "RESULT: FAIL (rc=$RC; see $OUT/power_raw.txt)"
  fi
} | tee "$LOG"
echo "logged -> $LOG"
exit $RC
