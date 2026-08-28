#!/usr/bin/env bash
# Shared silicon-build environment and helpers. SOURCE this (do not execute):
# it sets PDK_ROOT, the Magic rcfile, and the netgen setup file, and defines the
# mag() helper used by tools/gen_cells.sh, tools/gen_macro.sh, tools/gen_band.sh,
# and the per-vehicle rebuild scripts.
export PDK_ROOT="${PDK_ROOT:-$HOME/.ciel}"
RC=$(find "$PDK_ROOT" -path '*magic*' -name "sky130A.magicrc" | head -1)
SETUP=$(find "$PDK_ROOT" -iname "sky130A_setup.tcl" -path "*netgen*" | head -1)

mag() { # mag <dir> <script> [env k=v ...]
    local d=$1 s=$2; shift 2
    mkdir -p "$d/build"   # generators write here; may not exist on a fresh clone
    ( cd "$d/build" && env "$@" magic -dnull -noconsole -rcfile "$RC" < "../$s" ) \
        | grep -E "^(DRC=|BBOX=|WEIGHTS_FILE|PRECHARGE_ROW)" || true
}

# cached <sentinel-basename> -- true (skip) if the sentinel exists and FORCE unset.
# Call `mark_done <sentinel-basename>` after a successful build.
cached() { [ -z "${FORCE:-}" ] && [ -f "build/.$1.done" ]; }
mark_done() { mkdir -p build && touch "build/.$1.done"; }
