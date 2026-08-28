#!/usr/bin/env bash
# LEGACY: build the analog StrongARM sense band views (GDS/LEF/Liberty) and
# verify them by flat-extraction netgen against the floating-substrate
# references. The analog readout is retired for future tapeouts; this exists
# only to reproduce the submitted Azara vehicle. Skips if already built this
# checkout (FORCE=1 to rebuild).
#
# Usage: tools/gen_band.sh          # skip if cached
#        FORCE=1 tools/gen_band.sh  # rebuild
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
source "$ROOT/tools/lib_silicon.sh"

if cached gen_band; then echo "== gen_band: cached (FORCE=1 to rebuild) =="; exit 0; fi

echo "== gen_band (LEGACY analog) =="
echo "-- band views --"
uv run python3 cell/sky130/sense_se/build_band_klayout.py | tail -1
uv run python3 cell/sky130/sense_se/author_band_lef.py \
    cell/sky130/strongarm/build/sa_se_band16_kl.lef \
    cell/sky130/strongarm/build/sa_se_band16_kl_power.json \
    macro/sky130/abstracts/sa_se_band16.lef | tail -1
cp cell/sky130/strongarm/build/sa_se_band16_kl.gds macro/sky130/abstracts/sa_se_band16.gds
uv run python3 cell/sky130/sense_se/author_band_lib.py | tail -1

echo "-- band LVS (flat extract vs floating-substrate references) --"
for BN in 4 16; do
    [ "$BN" = 4 ] && ANKHDJET_BAND_N=4 uv run python3 cell/sky130/sense_se/build_band_klayout.py > /dev/null
    ( cd cell/sky130/strongarm/build && magic -dnull -noconsole -rcfile "$RC" <<EOT > /dev/null 2>&1
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
      netgen -batch lvs "band${BN}_chk.spice sa_se_band${BN}" \
        "$ROOT/cell/sky130/sense_se/band${BN}_reference.spice sa_se_band${BN}" \
        "$SETUP" "lvs_band${BN}_rebuild.rpt" 2>&1 | grep -iE "match" | tail -1 | sed "s/^/[band$BN] /" )
done
mark_done gen_band
echo "== gen_band: built =="
