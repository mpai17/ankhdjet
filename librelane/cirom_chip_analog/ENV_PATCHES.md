# Environment patches (not in the repo)

Re-apply after any `uv sync` / reinstall:
`bash tools/apply_env_patches.sh` applies everything below idempotently.

## Sign-off ECO hook (mag_gds.tcl)

File: `<env>/lib/python3.11/site-packages/librelane/scripts/magic/def/mag_gds.tcl`
Immediately before `gds write $::env(SAVE_MAG_GDS)`, add:

```tcl
if { [info exists ::env(DESIGN_DIR)] } {
    set _eco [file join $::env(DESIGN_DIR) eco_patches.tcl]
    if { [file exists $_eco] } {
        puts "Sourcing sign-off ECO hook: $_eco"
        select top cell
        source $_eco
    }
}
```

This streams `<design_dir>/eco_patches.tcl` (net-safe paint DRC patches)
out natively in Magic, keeping extraction and LVS truthful. Remove or
rename eco_patches.tcl to run without the ECO. The fills are tied to the
flow's deterministic routing: regenerate them (tools/gen_drc_eco.py)
after any geometry or config change.

## yosys shim (build/yosys-wrap/)

LibreLane's pyosys steps run `yosys -y <script>`; yosys's embedded Python
resolves its prefix from the first `python3` on PATH. Under `uv run` that
is the repo venv, which exposes no site-packages to the embedded
interpreter (different Python version), so `import click` fails inside
every pyosys script. `tools/apply_env_patches.sh` builds
`build/yosys-wrap/yosys`, a shim that extends PYTHONPATH with a copy of
the venv's own locked click (pure Python, interpreter-version agnostic)
and then execs the PATH yosys. The flow drivers point librelane at the
shim via `_LLN_OVERRIDE_YOSYS`; nothing depends on system Python
packages, so the fix travels with `uv sync` to any machine.
