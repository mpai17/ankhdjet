#!/usr/bin/env bash
# Generate a self-contained interactive GDS web viewer (single HTML file):
# per-layer KLayout renders -> tinted SKY130 colors -> pan/zoom layer viewer.
#
# Usage: tools/gen_gds_viewer.sh <design.gds> [out.html] [title] [subtitle]
#   out.html defaults to build/gds_viewer/<stem>/<stem>-viewer.html
# Needs: klayout, magick (ImageMagick 7), python3.
set -euo pipefail
cd "$(dirname "$0")/.."

GDS=${1:?usage: tools/gen_gds_viewer.sh <design.gds> [out.html] [title] [subtitle]}
STEM=$(basename "$GDS" .gds)
WORK="build/gds_viewer/$STEM"
OUT=${2:-$WORK/$STEM-viewer.html}
TITLE=${3:-$STEM}
SUB=${4:-"GDS viewer — $(basename "$GDS")"}

mkdir -p "$WORK"
klayout -b -rd gds="$GDS" -rd out="$WORK" -r tools/gds_viewer/render_layers.py
python3 tools/gds_viewer/build_viewer.py "$WORK" "$OUT" \
    --title "$TITLE" --subtitle "$SUB"
