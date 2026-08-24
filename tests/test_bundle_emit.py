"""Design-bundle closure: a compiled output directory must be
self-contained (every filelist entry exists, every memh a binding
references exists, digests match), the wheel's force-include map must
stay in lockstep with the bundle's library list, and the guardrails
(name collisions, reserved directories, masks-only mode) must hold."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.backend.bundle import (
    LIB_FILES, TB_FILE, emit_design_bundle, rtl_data_root,
)
from ankhdjet.frontend.ir import Layer, LayerType, ModelIR, QuantScheme, WeightTensor

pytestmark = pytest.mark.package


def _layer(name: str, n: int, m: int, seed: int = 0) -> Layer:
    rng = np.random.default_rng(seed)
    W = rng.integers(-1, 2, size=(n, m)).astype(np.int8)
    return Layer(name=name, layer_type=LayerType.LINEAR,
                 weights={"weight": WeightTensor(name="weight", data=W,
                                                 scheme=QuantScheme.TERNARY)},
                 input_dim=n, output_dim=m)


def _model() -> ModelIR:
    return ModelIR(name="tiny", layers=[
        _layer("blk.0", 10, 6, seed=0),      # ragged at 8x4 chunks
        _layer("blk_1", 8, 4, seed=1),       # exact fit
        _layer("lm_head", 4, 4, seed=2),     # skipped as off-fabric
    ])


def _filelist_entries(out: Path) -> list[str]:
    return [ln for ln in (out / "filelist.f").read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]


def test_bundle_is_closed(tmp_path):
    res = emit_design_bundle(_model(), tmp_path, macro_rows=8, macro_cols=4,
                             skip_layers=("lm_head",))
    out = tmp_path

    # masks unchanged beside the bundle
    assert (out / "blk.0" / "r0_c0.wmat").exists()
    assert (out / "model_manifest.json").exists()
    assert res["masks"]["totals"]["weights"] == 10 * 6 + 8 * 4

    # every filelist entry exists
    entries = _filelist_entries(out)
    assert entries, "filelist has no source entries"
    for rel in entries:
        assert (out / rel).exists(), f"filelist names missing file {rel}"

    # library complete, bench present
    lib_names = {Path(rel).name for rel in LIB_FILES}
    assert {p.name for p in (out / "rtl" / "lib").iterdir()} == lib_names
    assert (out / "sim" / "tb_grid.sv").exists()

    # every memh a front-end binding references exists, relative to out
    for afe in (out / "rtl").glob("cirom_grid_afe_*.sv"):
        text = afe.read_text()
        refs = [seg.split('"')[0] for seg in text.split('.WPOS("')[1:]]
        refs += [seg.split('"')[0] for seg in text.split('.WNEG("')[1:]]
        assert refs, f"{afe.name} references no memh"
        for rel in refs:
            assert (out / rel).exists(), f"{afe.name} references missing {rel}"

    # legalized names in the emitted structure
    top = (out / "rtl" / "ankhdjet_grid_blk_0.sv").read_text()
    assert "module ankhdjet_grid_blk_0 (" in top
    assert "cirom_grid_afe_blk_0 #(" in top

    # manifest digests match the files on disk (library, rtl, abstracts)
    man = res["bundle"]
    digests = {**man["library"], **man["rtl_sha256_16"],
               **man["macro_abstracts"]["files"]}
    for rel, digest in digests.items():
        actual = hashlib.sha256((out / rel).read_bytes()).hexdigest()[:16]
        assert actual == digest, f"digest mismatch for {rel}"
    assert man["macro_abstracts"]["name"] == "macro_array_pc_8x4"


def test_masks_only_mode(tmp_path):
    res = emit_design_bundle(_model(), tmp_path, macro_rows=8, macro_cols=4,
                             emit_rtl=False, skip_layers=("lm_head",))
    assert res["bundle"] is None
    assert not (tmp_path / "rtl").exists()
    assert not (tmp_path / "filelist.f").exists()
    assert (tmp_path / "model_manifest.json").exists()


def test_colliding_layer_names_refused(tmp_path):
    model = ModelIR(name="tiny", layers=[
        _layer("blk.0", 8, 4), _layer("blk_0", 4, 4, seed=1)])
    with pytest.raises(ValueError, match="collides"):
        emit_design_bundle(model, tmp_path, macro_rows=8, macro_cols=4)


def test_reserved_layer_name_refused(tmp_path):
    model = ModelIR(name="tiny", layers=[_layer("rtl", 8, 4)])
    with pytest.raises(ValueError, match="reserved"):
        emit_design_bundle(model, tmp_path, macro_rows=8, macro_cols=4)


def test_hardened_view(tmp_path):
    res = emit_design_bundle(_model(), tmp_path, macro_rows=8, macro_cols=4,
                             skip_layers=("lm_head",), harden=True)
    out = tmp_path
    # blk.0 is 10x6 at 8x4 chunks (2x2 grid) + blk_1 exact (1x1)
    assert res["bundle"]["hardening"]["chunk_count"] == 5

    entries = [ln for ln in
               (out / "filelist_hard.f").read_text().splitlines()
               if ln.strip() and not ln.startswith("#")]
    for rel in entries:
        assert (out / rel).exists(), f"filelist_hard names missing {rel}"
    assert not any("cirom_array_beh" in e for e in entries)
    assert any(e.startswith("rtl/hard/") for e in entries)

    # every instantiated chunk module is declared by the bb files
    declared, instantiated = set(), set()
    for rel in entries:
        text = (out / rel).read_text()
        if rel.endswith(".bb.v"):
            declared |= set(re.findall(r"^module\s+(\w+)", text, re.M))
        elif rel.startswith("rtl/hard/"):
            instantiated |= set(
                re.findall(r"^\s*(macro_array_pc_\w+)\s+u_", text, re.M))
    assert instantiated and instantiated <= declared

    # the manifest maps every chunk module to an existing mask program
    man = json.loads(
        (out / "macros" / "hardening_manifest.json").read_text())
    assert len(man["chunks"]) == 5
    for ch in man["chunks"]:
        assert (out / ch["wmat"]).exists()
        assert ch["module"].endswith(f"_r{ch['r']}_c{ch['c']}")

    for rel, digest in res["bundle"]["hardening"]["files"].items():
        actual = hashlib.sha256((out / rel).read_bytes()).hexdigest()[:16]
        assert actual == digest

    plain = emit_design_bundle(_model(), tmp_path / "plain", macro_rows=8,
                               macro_cols=4, skip_layers=("lm_head",))
    assert "hardening" not in plain["bundle"]


def test_progress_events_serial(tmp_path):
    events = []
    emit_design_bundle(_model(), tmp_path, macro_rows=8, macro_cols=4,
                       skip_layers=("lm_head",), jobs=1,
                       progress=lambda *a: events.append(a))
    masks = [e for e in events if e[0] == "masks"]
    rtl = [e for e in events if e[0] == "rtl"]
    assert masks == [("masks", 1, 2, "blk.0"), ("masks", 2, 2, "blk_1")]
    assert rtl[0] == ("rtl", 0, 2, "library")
    assert rtl[-1][1:3] == (2, 2)
    assert events.index(masks[-1]) < events.index(rtl[0])


def test_parallel_output_matches_serial(tmp_path):
    a, b = tmp_path / "serial", tmp_path / "parallel"
    ra = emit_design_bundle(_model(), a, macro_rows=8, macro_cols=4,
                            skip_layers=("lm_head",), jobs=1)
    rb = emit_design_bundle(_model(), b, macro_rows=8, macro_cols=4,
                            skip_layers=("lm_head",), jobs=2)
    assert ra["bundle"]["library"] == rb["bundle"]["library"]
    assert ra["bundle"]["rtl_sha256_16"] == rb["bundle"]["rtl_sha256_16"]
    assert ra["bundle"]["layers"] == rb["bundle"]["layers"]
    assert ra["masks"]["layers"] == rb["masks"]["layers"]
    assert (a / "filelist.f").read_text() == (b / "filelist.f").read_text()


def test_abstracts_match_signed_off_anchor(tmp_path):
    from ankhdjet.backend.abstracts import emit_macro_abstracts
    from ankhdjet.pdks import lef_size_and_pins
    ab = emit_macro_abstracts(64, 32, tmp_path)
    got_size, got = lef_size_and_pins(ab["lef"].read_text())
    ref_size, ref = lef_size_and_pins(
        (REPO_ROOT / "macro" / "sky130" / "abstracts" /
         "macro_array_pc_64x32_checker.lef").read_text())
    assert got_size == pytest.approx(ref_size, abs=1e-3)
    for pin in ("WL_0", "WL_8", "WL_63", "BLP_0", "BLP_31",
                "BLN_0", "BLN_31", "PRE_N"):
        assert got[pin] == ref[pin], f"{pin}: {got[pin]} != {ref[pin]}"
    # rails: every template rect must appear in the signed-off pin
    # (which additionally carries nwell/tap ports the template omits)
    for pin in ("VPWR", "VGND"):
        for rect in got[pin]:
            assert rect in ref[pin], f"{pin} rect {rect} not in signed-off"


def test_abstract_caps_scale_with_shape(tmp_path):
    from ankhdjet.backend.abstracts import emit_macro_abstracts
    ab = emit_macro_abstracts(128, 16, tmp_path)
    lib = ab["lib"].read_text()
    assert "capacitance : 120.0" in lib     # BL: 0.9375 fF/row x 128
    assert "capacitance : 15.0" in lib      # WL: 0.9375 fF/col x 16
    assert "capacitance : 52.5" in lib      # PRE_N: 3.28 fF/col x 16
    assert "anchored to the as-built" in lib


def test_library_sources_exist():
    root = rtl_data_root()
    for rel in (*LIB_FILES, TB_FILE):
        assert (root / rel).exists(), f"emission library file missing: {rel}"


def test_wheel_forceinclude_matches_library():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    fi = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    rtl_map = {k: v for k, v in fi.items() if k.startswith("rtl/")}
    expected = {f"rtl/{rel}": f"ankhdjet/_rtl/{rel}"
                for rel in (*LIB_FILES, TB_FILE)}
    assert rtl_map == expected
