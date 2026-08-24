#!/usr/bin/env bash
# Apply the repo's environment patches (librelane/cirom_chip_analog/ENV_PATCHES.md)
# to a Python environment's librelane site-packages. Idempotent: safe to run
# after every install/sync; a marker comment guards double-insertion.
#
#   bash tools/apply_env_patches.sh [envdir]     # default: .venv, else venv
set -euo pipefail
cd "$(dirname "$0")/.."
ENVDIR="${1:-}"
if [ -z "$ENVDIR" ]; then
    for c in .venv venv; do [ -d "$c" ] && ENVDIR=$c && break; done
fi
[ -n "$ENVDIR" ] || { echo "no .venv or venv found"; exit 1; }

# yosys shim: librelane's pyosys steps run `yosys -y <script>`, and yosys's
# embedded python resolves its prefix from the first python3 on PATH. Under
# `uv run` that is the repo venv, which exposes no site-packages to the
# embedded interpreter (different Python version), so `import click` fails
# inside every pyosys script. The shim extends PYTHONPATH with a copy of the
# venv's own locked click (pure python, interpreter-version agnostic), so the
# fix carries no dependency on system python packages. The flow drivers point
# librelane at the shim via _LLN_OVERRIDE_YOSYS.
mkdir -p build/yosys-wrap/pyosys-deps
rm -rf build/yosys-wrap/pyosys-deps/click
CLICK_SRC=$(find "$ENVDIR" -maxdepth 4 -type d -path "*/site-packages/click" | head -1)
[ -n "$CLICK_SRC" ] || { echo "click not found under $ENVDIR (run uv sync first)"; exit 1; }
cp -r "$CLICK_SRC" build/yosys-wrap/pyosys-deps/
cat > build/yosys-wrap/yosys <<'YEOF'
#!/usr/bin/env bash
# yosys shim for librelane pyosys steps (invoked via _LLN_OVERRIDE_YOSYS):
# extends PYTHONPATH with the pyosys scripts' third-party deps (click) so
# the embedded python -- whose prefix resolution under `uv run` lands in
# the repo venv and exposes no site-packages -- can import them regardless
# of what the system python has installed. The real yosys comes from PATH
# (this directory is not on PATH, so there is no self-recursion).
HERE=$(cd "$(dirname "$0")" && pwd)
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$HERE/pyosys-deps"
exec yosys "$@"
YEOF
chmod +x build/yosys-wrap/yosys
echo "yosys shim: build/yosys-wrap/yosys (deps: pyosys-deps/click)"

TCL=$(find "$ENVDIR" -path "*librelane/scripts/magic/def/mag_gds.tcl" | head -1)
[ -n "$TCL" ] || { echo "mag_gds.tcl not found under $ENVDIR (librelane installed?)"; exit 1; }

MARK="Project sign-off ECO hook"
if grep -q "$MARK" "$TCL"; then
    echo "ECO hook already present: $TCL"
    exit 0
fi

# system python3 on purpose: this bootstraps the env and must not depend on it
python3 - "$TCL" <<'EOF'
import sys
from pathlib import Path
p = Path(sys.argv[1])
s = p.read_text()
needle = "gds write $::env(SAVE_MAG_GDS)"
assert needle in s, f"anchor line not found in {p}"
hook = """# Project sign-off ECO hook: source <DESIGN_DIR>/eco_patches.tcl if present,
# so net-safe paint DRC patches stream out natively (ENV_PATCHES.md).
if { [info exists ::env(DESIGN_DIR)] } {
    set _eco [file join $::env(DESIGN_DIR) eco_patches.tcl]
    if { [file exists $_eco] } {
        puts "Sourcing sign-off ECO hook: $_eco"
        select top cell
        source $_eco
    }
}
"""
i = s.index(needle)
line_start = s.rfind("\n", 0, i) + 1
s = s[:line_start] + hook + s[line_start:]
p.write_text(s)
print(f"ECO hook inserted: {p}")
EOF
