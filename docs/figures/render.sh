#!/usr/bin/env bash
# Render every .drawio in this directory to PNG with a consistent border.
set -u
cd "$(dirname "$0")"

for src in *.drawio; do
    out="${src%.drawio}.png"
    drawio --no-sandbox -x -f png -s 2 -b 80 -o "$out" "$src" 2>&1 \
        | grep -v "wayland_wp_color_manager\|vaInitialize" | tail -1
done
