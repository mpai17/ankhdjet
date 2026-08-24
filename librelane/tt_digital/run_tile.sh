#!/usr/bin/env bash
# Driver for the LibreLane Classic flow on tt_um_darga_cirom (the TinyTapeout
# digital-tier tile: the mask-programmed array macro read by clocked bitline
# sampling, with the ternary MAC in standard cells; no analog content, no ua
# pins). The tile sources are compiler-emitted here first: weights=test0, the
# same mask program as the analog tile, so the two vehicles differ only in
# readout style. Same tool sourcing as librelane/cirom_chip_analog/run_librelane.sh
# (pip librelane + nix openroad/opensta + system yosys/magic/klayout/netgen).
# Run from repo root:
#   bash librelane/tt_digital/run_tile.sh [run-tag]
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"
RUN_TAG=${1:-dig1}
export PATH="$REPO/build/openroad-wrap:$REPO/build/opensta/bin:$PATH"
unset PYTHONPATH
export _LLN_OVERRIDE_YOSYS="$REPO/build/yosys-wrap/yosys"
PDK_ROOT=${PDK_ROOT:-$HOME/.ciel}
export PDK_ROOT

rm -rf librelane/tt_digital/build/src   # stale emitted tops must not linger

uv run python - <<'EOF'
from ankhdjet.backend.tt_digital import emit_tt_digital
r = emit_tt_digital("librelane/tt_digital/build/src", weights="test0", n_cols=32, n_acc=4, store_acts=0)
print(f"emitted {r['top']} + {r['afe']} (macro {r['macro_module']})")
EOF

exec uv run python -m librelane \
    --pdk-root "$PDK_ROOT" \
    --pdk sky130A \
    --run-tag "$RUN_TAG" \
    librelane/tt_digital/config_tile.json
