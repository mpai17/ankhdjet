"""Complete design-bundle emission: masks + RTL + sim views + filelist.

The compile command's output contract: one directory carrying the mask
programs (the fab handoff) alongside a self-contained RTL view of the
same design, so the bundle elaborates on a machine that has never seen
the repository:

    <out>/<layer>/*.wmat + manifests   mask programs (fab handoff)
    <out>/rtl/lib/*.sv                 copied library modules
    <out>/rtl/*.sv                     per-layer grid top + front-end binding
    <out>/sim/<layer>/*.memh           behavioral views of the same mask programs
    <out>/sim/tb_grid.sv               the parameterized smoke bench
    <out>/macros/*.{lef,lib,bb.v}      per-shape macro abstracts (template-grade)
    <out>/rtl/hard/*.sv + *.bb.v       hardened chunk-macro bindings (harden=True)
    <out>/filelist_hard.f              selects the hardened view (harden=True)
    <out>/filelist.f                   sources, relative to <out>
    <out>/bundle_manifest.json         RTL file list + digests

`iverilog -f filelist.f` (run from <out>) elaborates the bundle; the
filelist header documents the per-layer bench invocation. GDS hardening
is the repository-side backend toolchain (custom cells + LibreLane).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ankhdjet.backend._pool import run_ordered
from ankhdjet.backend.abstracts import emit_macro_abstracts
from ankhdjet.backend.grid_rtl import emit_grid
from ankhdjet.backend.idents import check_unique, path_token, sv_ident
from ankhdjet.backend.macro_grid import emit_model
from ankhdjet.frontend.ir import LayerType, ModelIR

# The emission library shipped in the wheel (ankhdjet/_rtl) and copied
# into every bundle. Kept in lockstep with the wheel force-include map
# in pyproject.toml; the package test suite asserts the two agree.
LIB_FILES = (
    "grid/cirom_grid_ctrl.sv",
    "grid/cirom_array_beh.sv",
    "between_layer/between_layer.sv",
    "between_layer/requantize.sv",
    "column/cirom_nor_tile.sv",
)
TB_FILE = "grid/sim/tb_grid.sv"

# Bundle subdirectories that a layer name must not shadow.
RESERVED_DIRS = frozenset({"rtl", "sim", "macros"})


def rtl_data_root() -> Path:
    """The rtl/ library directory: the repo checkout's copy when running
    in-tree, else the copy bundled into the installed wheel."""
    repo = Path(__file__).resolve().parent.parent.parent / "rtl"
    if repo.is_dir():
        return repo
    from importlib.resources import files
    return Path(str(files("ankhdjet"))) / "_rtl"


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def emit_design_bundle(model: ModelIR, out_dir: Path | str,
                       macro_rows: int = 64, macro_cols: int = 256,
                       act_w: int = 4, acc_w: int = 16,
                       emit_rtl: bool = True,
                       skip_layers: tuple[str, ...] = (),
                       progress=None, jobs: int | None = None,
                       pdk: str = "sky130", harden: bool = False) -> dict:
    """Emit the mask set and, unless emit_rtl is False, the
    self-contained RTL bundle beside it. The RTL grid chunks use the
    same macro geometry as the mask programs, so the memh views are
    views of the same chunks the .wmat files program. Returns
    {"masks": <model manifest>, "bundle": <bundle manifest or None>}.
    `progress`, when given, is called as progress(stage, done, total,
    label) with stage "masks" then "rtl". Both stages fan their layers
    out across a process pool (`jobs` workers, default all cores; 1 =
    serial) with byte-deterministic output either way. With `harden`,
    the bundle additionally carries the hardened view under rtl/hard/
    (per-chunk hard-macro AFE implementations + blackbox declarations),
    filelist_hard.f selecting it, and macros/hardening_manifest.json
    mapping every chunk module to its layer, grid position, and mask
    program for the hardening flow.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    masks = emit_model(model, out, macro_rows, macro_cols,
                       skip_layers=skip_layers, progress=progress,
                       jobs=jobs)
    if not emit_rtl:
        return {"masks": masks, "bundle": None}

    linear = [L for L in model.layers
              if L.name not in skip_layers
              and L.layer_type == LayerType.LINEAR]
    check_unique([L.name for L in linear])
    for L in linear:
        if path_token(L.name) in RESERVED_DIRS:
            raise ValueError(
                f"layer name {L.name!r} shadows a bundle directory "
                f"(reserved: {sorted(RESERVED_DIRS)})")

    rtl_dir = out / "rtl"
    lib_dir = rtl_dir / "lib"
    sim_dir = out / "sim"
    lib_dir.mkdir(parents=True, exist_ok=True)
    sim_dir.mkdir(parents=True, exist_ok=True)

    root = rtl_data_root()
    lib_paths = []
    for rel in LIB_FILES:
        dst = lib_dir / Path(rel).name
        dst.write_text((root / rel).read_text())
        lib_paths.append(dst)
    tb_dst = sim_dir / Path(TB_FILE).name
    tb_dst.write_text((root / TB_FILE).read_text())
    if progress is not None:
        progress("rtl", 0, len(linear), "library")

    hard_dir = rtl_dir / "hard" if harden else None
    calls = [(L.name, emit_grid, (L.weights["weight"].data, out), dict(
        layer_name=L.name,
        top_name=f"ankhdjet_grid_{sv_ident(L.name)}",
        macro_rows=macro_rows, macro_cols=macro_cols,
        act_w=act_w, acc_w=acc_w,
        rtl_dir=rtl_dir, memh_dir=sim_dir,
        memh_prefix=f"sim/{L.name}",
        afe_name=f"cirom_grid_afe_{sv_ident(L.name)}",
        hardened_dir=hard_dir,
        chunk_base=f"macro_array_pc_{macro_rows}x{macro_cols}_"
                   f"{sv_ident(L.name)}",
    )) for L in linear]
    grids = run_ordered(calls, jobs=jobs, progress=progress, stage="rtl")

    layer_paths = []
    layer_entries = []
    for L, g in zip(linear, grids):
        layer_paths += [g["afe"], g["top"]]
        layer_entries.append({
            "layer": L.name,
            "top": f"ankhdjet_grid_{sv_ident(L.name)}",
            "afe": g["afe"].relative_to(out).as_posix(),
            "top_file": g["top"].relative_to(out).as_posix(),
            "n": g["N"], "m": g["M"],
            "grid_r": g["grid_r"], "grid_c": g["grid_c"],
        })

    ab = emit_macro_abstracts(macro_rows, macro_cols, out / "macros",
                              pdk=pdk)

    hardening = None
    hard_paths: list[Path] = []
    if harden:
        from ankhdjet.backend.abstracts import blackbox_lines
        chunk_entries = []
        for L, g in zip(linear, grids):
            base = (f"macro_array_pc_{macro_rows}x{macro_cols}_"
                    f"{sv_ident(L.name)}")
            bbp = hard_dir / f"{base}.bb.v"
            bb = [f"// Per-chunk hard-macro blackboxes for layer {L.name}:",
                  f"// {len(g['chunk_modules'])} chunks of "
                  f"{macro_rows}x{macro_cols} (one mask program each).", ""]
            for mod in g["chunk_modules"]:
                bb += blackbox_lines(mod, macro_rows, macro_cols) + [""]
            bbp.write_text("\n".join(bb))
            hard_paths += [g["hard_afe"], bbp]
            for i, mod in enumerate(g["chunk_modules"]):
                r, c = divmod(i, g["grid_c"])
                chunk_entries.append({
                    "module": mod, "layer": L.name, "r": r, "c": c,
                    "wmat": f"{L.name}/r{r}_c{c}.wmat",
                })
        hardening = {
            "filelist": "filelist_hard.f",
            "shape": {"rows": macro_rows, "cols": macro_cols},
            "abstracts": {k: ab[k].relative_to(out).as_posix()
                          for k in ("lef", "lib", "bb")},
            "chunks": chunk_entries,
        }
        (out / "macros" / "hardening_manifest.json").write_text(
            json.dumps(hardening, indent=1))
        hard_rels = ([p.relative_to(out).as_posix() for p in lib_paths
                      if p.name != "cirom_array_beh.sv"]
                     + [g["top"].relative_to(out).as_posix() for g in grids]
                     + [p.relative_to(out).as_posix() for p in hard_paths])
        (out / "filelist_hard.f").write_text("\n".join([
            "# Hardened-view sources: grid tops bound to per-chunk hard",
            "# macros (blackboxes here; GDS/views from the hardening flow",
            "# per macros/hardening_manifest.json). Compile this OR",
            "# filelist.f, never both.",
            *hard_rels,
        ]) + "\n")

    rels = [p.relative_to(out).as_posix() for p in lib_paths + layer_paths]
    filelist = out / "filelist.f"
    filelist.write_text("\n".join([
        "# Ankhdjet design bundle sources; paths relative to this directory.",
        "# Elaborate:  iverilog -g2012 -f filelist.f",
        "# Hard-macro floorplanning collateral: macros/ (not simulation sources).",
        "# Per-layer smoke bench (act.memh/golden.memh in this directory;",
        "# N/M/top per bundle_manifest.json):",
        "#   iverilog -g2012 -DANKHDJET_N=<n> -DANKHDJET_M=<m> \\",
        "#     -DANKHDJET_GRID_TOP=<top> -f filelist.f sim/tb_grid.sv",
        "#   vvp a.out",
        *rels,
    ]) + "\n")

    bundle_man = {
        "filelist": "filelist.f",
        "tb": tb_dst.relative_to(out).as_posix(),
        "act_w": act_w, "acc_w": acc_w,
        "library": {p.relative_to(out).as_posix(): _sha16(p)
                    for p in lib_paths},
        "layers": layer_entries,
        "rtl_sha256_16": {p.relative_to(out).as_posix(): _sha16(p)
                          for p in layer_paths},
        "macro_abstracts": {
            "name": ab["name"], "pdk": ab["pdk"],
            "pack_version": ab["pack_version"],
            "restricted": ab["restricted"],
            "width_um": ab["width_um"], "height_um": ab["height_um"],
            "files": {ab[k].relative_to(out).as_posix(): _sha16(ab[k])
                      for k in ("lef", "lib", "bb")},
        },
        "masks_manifest": "model_manifest.json",
    }
    if hardening is not None:
        bundle_man["hardening"] = {
            "filelist": "filelist_hard.f",
            "manifest": "macros/hardening_manifest.json",
            "chunk_count": len(hardening["chunks"]),
            "files": {p.relative_to(out).as_posix(): _sha16(p)
                      for p in hard_paths},
        }
    (out / "bundle_manifest.json").write_text(json.dumps(bundle_man, indent=1))
    return {"masks": masks, "bundle": bundle_man}
