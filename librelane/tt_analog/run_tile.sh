#!/usr/bin/env bash
# Driver for the LibreLane Classic flow on tt_um_azara_cirom (the TinyTapeout
# tile: array macro + 2 sa_se_band16 bands + digital controller in the 1x2
# analog template; VREF is external on ua[0]). Same tool sourcing as
# librelane/cirom_chip_analog/run_librelane.sh (pip librelane + nix openroad/opensta +
# system yosys/magic/klayout/netgen). Run from repo root:
#   bash librelane/tt_analog/run_tile.sh [run-tag]
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"
RUN_TAG=${1:-tile1}
export PATH="$REPO/build/openroad-wrap:$REPO/build/opensta/bin:$PATH"
unset PYTHONPATH
export _LLN_OVERRIDE_YOSYS="$REPO/build/yosys-wrap/yosys"
PDK_ROOT=${PDK_ROOT:-$HOME/.ciel}
export PDK_ROOT
exec uv run python -m librelane \
    --pdk-root "$PDK_ROOT" \
    --pdk sky130A \
    --run-tag "$RUN_TAG" \
    librelane/tt_analog/config_tile.json
