#!/usr/bin/env bash
# Build + verify the sa_se atomic cell.
#
# sa_se is the single-ended sense comparator. It is electrically IDENTICAL
# to the validated strongarm cell (proven by topology isomorphism), so the
# layout is the DRC/LVS-clean strongarm.mag with 4 ports relabeled:
#     BLP->BL  BLN->VREF  OUTP->HIT  OUTM->HITB
# (STROBE/VDD/VGND unchanged). The cell is hierarchical -- it instantiates
# the 9 strongarm device subcells -- so sa_se.mag must live alongside those
# subcells for extraction to resolve the subtree. We therefore build it in
# the strongarm build dir.
#
# Verifies: Magic DRC == 0, and netgen LVS "Circuits match uniquely" vs the
# sa_se schematic in sense_col_schematic.spice.
set -euo pipefail
REPO=/home/mohnishp/workspace/Azara
SA_BUILD="$REPO/cell/sky130/strongarm/build"
SENSE="$REPO/cell/sky130/sense_se"
SETUP=$(ls "$HOME"/.ciel/sky130A/libs.tech/netgen/sky130A_setup.tcl | head -1)

# 1. Ensure the strongarm hierarchy exists (subcells + top + routing).
cd "$SA_BUILD"
if [ ! -f sa_xc_p.mag ] || [ ! -f strongarm.mag ]; then
  magic -dnull -noconsole -T sky130A "$REPO/cell/sky130/strongarm/gen_strongarm_subcells.tcl" >/dev/null 2>&1
  magic -dnull -noconsole -T sky130A "$REPO/cell/sky130/strongarm/gen_strongarm_top.tcl"       >/dev/null 2>&1
  magic -dnull -noconsole -T sky130A "$REPO/cell/sky130/strongarm/gen_strongarm_routing.tcl"   >/dev/null 2>&1
fi

# 2. Relabel strongarm.mag -> sa_se.mag (in place, beside the subcells).
uv run python - "$SA_BUILD/strongarm.mag" "$SA_BUILD/sa_se.mag" <<'PYEOF'
import sys
src, dst = sys.argv[1], sys.argv[2]
RENAME = {"BLP": "BL", "BLN": "VREF", "OUTP": "HIT", "OUTM": "HITB"}
out = []
for ln in open(src).read().splitlines():
    t = ln.split()
    if t and t[0] in ("rlabel", "flabel", "label") and t[-1] in RENAME:
        t[-1] = RENAME[t[-1]]
        ln = " ".join(t)
    out.append(ln)
open(dst, "w").write("\n".join(out) + "\n")
PYEOF

# 3. DRC + extract.
magic -dnull -noconsole -T sky130A <<'TCL' 2>&1 | grep -E "DRC=|EXT_DONE" || true
drc off
load sa_se
select top cell
drc on
drc check
drc catchup
puts "DRC=[drc list count total]"
extract no all
extract do local
extract no capacitance
extract no resistance
extract all
ext2spice lvs
ext2spice cthresh infinite
ext2spice rthresh infinite
ext2spice subcircuit on
ext2spice -o sa_se_extracted.spice
puts "EXT_DONE"
quit -noprompt
TCL

# magic writes to <cellname>.mag.spice when -o basename collides; normalize.
[ -f sa_se.mag.spice ] && mv -f sa_se.mag.spice sa_se_extracted.spice

# 4. LVS vs schematic (alias VSUBS->VGND as the strongarm test does).
sed 's/VSUBS/VGND/g' sa_se_extracted.spice > sa_se_vgnd.spice
netgen -batch lvs "sa_se_vgnd.spice sa_se" \
  "$SENSE/sense_col_schematic.spice sa_se" "$SETUP" sa_se_lvs.rpt >/dev/null 2>&1 || true
echo "LVS:"; grep -E "match uniquely|are equivalent|Final result|MISMATCH" sa_se_lvs.rpt | tail -4
