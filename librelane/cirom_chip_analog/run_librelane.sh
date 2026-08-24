#!/usr/bin/env bash
# Driver script for running the LibreLane Classic flow on cirom_chip_analog.
#
# Tool sourcing (no LibreLane Nix shell -- its yosys-with-plugins
# depends on libgnat which currently fails to fetch from any mirror):
#   - librelane Python lib  : uv-managed project env (uv sync -> .venv,
#                             pinned in pyproject.toml/uv.lock)
#   - openroad              : nix-built into build/openroad/
#   - openroad-wrap         : sets PYTHONPATH only inside openroad
#                             (so embedded python3.13 finds yaml/click/rich;
#                              global PYTHONPATH would poison the
#                              python3.11 project env via yamlcore C-ext
#                              mismatch)
#   - opensta               : nix-built into build/opensta/
#   - yosys/magic/klayout/netgen/verilator : system pacman packages
#   - yaml/click/rich/markdown_it/pygments : nix-built python3.13 wheels
#
# First-time setup expects:
#   nix build github:librelane/librelane#openroad --out-link build/openroad
#   nix build github:librelane/librelane#opensta  --out-link build/opensta
#   nix build nixpkgs#python313Packages.{pyyaml,click,rich,markdown-it-py,pygments} \
#       --out-link build/<name>
#
# Run from repo root:
#   bash librelane/cirom_chip_analog/run_librelane.sh [run-tag]

set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"

RUN_TAG=${1:-default}

export PATH="$REPO/build/openroad-wrap:$REPO/build/opensta/bin:$PATH"
unset PYTHONPATH  # PYTHONPATH for openroad's embedded python is set inside the wrapper
export _LLN_OVERRIDE_YOSYS="$REPO/build/yosys-wrap/yosys"  # system-only PATH for yosys's embedded python (see tools/apply_env_patches.sh)

PDK_ROOT=${PDK_ROOT:-$HOME/.ciel}
export PDK_ROOT

bash "$REPO/tools/apply_env_patches.sh"   # idempotent: the flow needs the ECO hook
exec uv run python -m librelane \
    --pdk-root "$PDK_ROOT" \
    --pdk sky130A \
    --run-tag "$RUN_TAG" \
    librelane/cirom_chip_analog/config_bands.json
