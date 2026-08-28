#!/usr/bin/env bash
# Build the size- and weight-independent CiROM leaf cells (bitcell, body tap,
# precharge cell). Run once; shared by every macro (tools/gen_macro.sh).
# Skips if already built this checkout (FORCE=1 to rebuild).
#
# Usage: tools/gen_cells.sh          # skip if cached
#        FORCE=1 tools/gen_cells.sh  # rebuild
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
source "$ROOT/tools/lib_silicon.sh"

if cached gen_cells; then echo "== gen_cells: cached (FORCE=1 to rebuild) =="; exit 0; fi

echo "== gen_cells =="
mag cell/sky130/precharge  gen_precharge.tcl
mag cell/sky130/bitcell_v4 gen_bitcell_v4.tcl
mag cell/sky130/bitcell_v4 gen_body_tap.tcl
mark_done gen_cells
echo "== gen_cells: leaf cells built =="
