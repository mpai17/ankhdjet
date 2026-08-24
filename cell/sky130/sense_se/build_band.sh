#!/usr/bin/env bash
# Build the sa_se_band16 abstract (GDS + LEF) from the single sa_se cell.
#   1. build_band_klayout.py -> sa_se_band16_kl.gds (16x tiled, met3 signal risers
#      to the macro edges, met4 power ring; port labels on the PIN datatype 16) +
#      power manifest JSON
#   2. KLayout DRC the GDS (must be 0)
#   3. band_lef_ports.tcl (Magic) -> kl.lef (full-riser met3 signal pins + OBS comb,
#      read straight from the GDS 16-datatype port labels)
#   4. author_band_lef.py        -> authored.lef (VDD/VGND from manifest)
#   5. publish the KLayout GDS + authored LEF to macro/sky130/abstracts/. The GDS
#      carries its ports as 16-datatype labels, which Magic's chip extraction reads
#      as ports, so it is published directly (no Magic round-trip). lib + bb.v are
#      pin-name level and unchanged, so they are not regenerated.
set -euo pipefail
REPO=/home/mohnishp/workspace/Azara
SA_BUILD="$REPO/cell/sky130/strongarm/build"
SENSE="$REPO/cell/sky130/sense_se"
ABS="$REPO/macro/sky130/abstracts"
PY="uv run python"

cd "$REPO"
$PY "$SENSE/build_band_klayout.py"

echo "== KLayout DRC (published GDS, full signoff options) =="
DECK=$(find "${PDK_ROOT:-$HOME/.ciel}" -name "sky130A_mr.drc" | head -1)
klayout -b -r "$DECK" -rd input="$SA_BUILD/sa_se_band16_kl.gds" \
    -rd topcell=sa_se_band16 -rd report=/tmp/band_drc.lyrdb \
    -rd feol=true -rd beol=true -rd floating_metal=false \
    -rd offgrid=true -rd seal=true -rd threads=16 > /tmp/band_drc.log 2>&1
V=$($PY -c "import re;print(len(re.findall(r'<item>',open('/tmp/band_drc.lyrdb').read())))")
echo "violations: $V"
[ "$V" = 0 ] || { echo "FAIL: KLayout DRC $V != 0; NOT publishing"; exit 1; }

cd "$SA_BUILD"
# Magic: read the GDS (16-datatype labels -> ports) and write the LEF (full-riser
# signal pins + OBS comb). Power pins are clipped by lef write, so author them next.
magic -dnull -noconsole -T sky130A < "$SENSE/band_lef_ports.tcl" 2>&1 | grep -E "BAND_LEF_DONE" || true
$PY "$SENSE/author_band_lef.py" sa_se_band16_kl.lef sa_se_band16_kl_power.json sa_se_band16_authored.lef

# Netgen LVS gate BEFORE publish: a band-internal short (e.g. band-level paint
# landing on SA-internal li) is legal geometry to DRC and invisible to the LEF,
# so extraction + netlist compare is the only check that catches it. Both band
# sizes must "match uniquely" with the full port list or nothing is published.
echo "== netgen LVS gate (band4 + band16 vs reference) =="
STAMP=$(date +%Y%m%d_%H%M%S)
LVSLOG="$SA_BUILD/lvs_band_gate_${STAMP}.log"
RC=$(find "${PDK_ROOT:-$HOME/.ciel}" -path '*magic*' -name "sky130A.magicrc" | head -1)
SETUP=$(find "${PDK_ROOT:-$HOME/.ciel}" -iname "sky130A_setup.tcl" -path "*netgen*" | head -1)
( cd "$REPO" && ANKHDJET_BAND_N=4 $PY "$SENSE/build_band_klayout.py" > /dev/null )
for BN in 4 16; do
    magic -dnull -noconsole -rcfile "$RC" <<EOT > /dev/null 2>&1
gds read sa_se_band${BN}_kl
load sa_se_band${BN}
extract do local
extract no capacitance
extract no coupling
extract no resistance
extract no adjust
extract
ext2spice lvs
ext2spice cthresh infinite
ext2spice rthresh infinite
ext2spice subcircuit on
ext2spice -o band${BN}_chk.spice
quit -noprompt
EOT
    VERDICT=$(netgen -batch lvs "band${BN}_chk.spice sa_se_band${BN}" \
        "$SENSE/band${BN}_reference.spice sa_se_band${BN}" \
        "$SETUP" "lvs_band${BN}_gate.rpt" 2>&1 | grep -i "match" | tail -1)
    echo "band${BN}: $VERDICT" | tee -a "$LVSLOG"
    if ! echo "$VERDICT" | grep -q "uniquely"; then
        echo "FAIL: band${BN} LVS did not match uniquely; NOT publishing" | tee -a "$LVSLOG"
        exit 1
    fi
done

cp -f "$SA_BUILD/sa_se_band16_kl.gds"        "$ABS/sa_se_band16.gds"
cp -f "$SA_BUILD/sa_se_band16_authored.lef"  "$ABS/sa_se_band16.lef"
echo "published $ABS/sa_se_band16.{gds,lef}"
echo "  signal pins: $(grep -cE '^  PIN (BL|VREF|HIT|STROBE)_' "$ABS/sa_se_band16.lef")  power pins: $(grep -cE '^  PIN (VDD|VGND)$' "$ABS/sa_se_band16.lef")"
