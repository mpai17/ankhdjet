"""PDK pack discovery, conformance, and provenance: the resolver finds
packs across its precedence chain, the sky130 pack validates against
its signed-off anchor, out-of-tree packs plug in through
ANKHDJET_PDK_PATH with shadowing precedence, and a restricted pack's
flag lands in the bundle manifest."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.pdks import discover_packs, discover_pdks, validate_pack

pytestmark = pytest.mark.package


def test_sky130_pack_discovered():
    packs = discover_packs()
    assert "sky130" in packs
    p = packs["sky130"]
    assert set(p.tiers) == {"estimate", "abstracts", "physical"}
    assert not p.restricted


def test_descriptor_names_stable():
    names = set(discover_pdks())
    assert {"sky130_v4", "sky130_biroma_bound", "gf180", "asap7"} <= names


def test_sky130_pack_conforms():
    assert validate_pack("sky130") == []


@pytest.mark.parametrize("name", ["gf180", "asap7"])
def test_estimate_only_packs_discovered_and_conform(name):
    packs = discover_packs()
    assert name in packs
    assert list(packs[name].tiers) == ["estimate"]
    assert validate_pack(name) == []


def test_estimate_only_pack_refuses_abstracts():
    from ankhdjet.pdks import abstract_pack
    with pytest.raises(ValueError, match="no abstracts tier.*sky130"):
        abstract_pack("gf180")


def test_pack_descriptors_keep_anchored_values():
    pdks = discover_pdks()
    assert pdks["gf180"].process_nm == 180
    assert pdks["gf180"].bitcell_um2 == 4.24
    assert pdks["asap7"].process_nm == 7
    assert pdks["asap7"].bitcell_um2 == 0.07
    assert pdks["asap7"].synth_calibration == 0.42


def test_unknown_pack_reported():
    issues = validate_pack("no_such_pdk")
    assert issues and "not found" in issues[0]


def test_anchor_lef_lockstep_with_signed_off():
    pack_copy = REPO_ROOT / "pdk" / "sky130" / "anchors" / \
        "macro_array_pc_64x32_checker.lef"
    signed_off = REPO_ROOT / "macro" / "sky130" / "abstracts" / \
        "macro_array_pc_64x32_checker.lef"
    assert pack_copy.read_bytes() == signed_off.read_bytes()


def _make_pack(root: Path, name: str, restricted: bool = False) -> Path:
    """A minimal abstracts-tier pack cloned from the sky130 data."""
    d = root / name
    (d / "anchors").mkdir(parents=True)
    src = REPO_ROOT / "pdk" / "sky130"
    (d / "abstracts.yaml").write_text((src / "abstracts.yaml").read_text())
    shutil.copy(src / "anchors" / "macro_array_pc_64x32_checker.lef",
                d / "anchors")
    (d / "pack.yaml").write_text(
        f"name: {name}\nversion: '9'\ntiers: [abstracts]\n"
        f"restricted: {str(restricted).lower()}\n")
    return d


def test_env_path_pack_discovered_and_validates(tmp_path, monkeypatch):
    _make_pack(tmp_path, "ndanode")
    monkeypatch.setenv("ANKHDJET_PDK_PATH", str(tmp_path))
    packs = discover_packs()
    assert "ndanode" in packs and packs["ndanode"].version == "9"
    assert validate_pack("ndanode") == []


def test_env_path_pack_shadows_bundled(tmp_path, monkeypatch):
    d = _make_pack(tmp_path, "sky130")
    monkeypatch.setenv("ANKHDJET_PDK_PATH", str(tmp_path))
    assert discover_packs()["sky130"].root == d


def test_validate_catches_geometry_drift(tmp_path, monkeypatch):
    d = _make_pack(tmp_path, "driftnode")
    text = (d / "abstracts.yaml").read_text()
    (d / "abstracts.yaml").write_text(
        text.replace("col_pitch: 1.700", "col_pitch: 1.800"))
    monkeypatch.setenv("ANKHDJET_PDK_PATH", str(tmp_path))
    issues = validate_pack("driftnode")
    assert issues and any("SIZE" in i or "rect" in i for i in issues)


def test_restricted_flag_lands_in_bundle_manifest(tmp_path, monkeypatch):
    from ankhdjet.backend.bundle import emit_design_bundle
    from ankhdjet.frontend.ir import (
        Layer, LayerType, ModelIR, QuantScheme, WeightTensor,
    )
    _make_pack(tmp_path / "packs", "secret7", restricted=True)
    monkeypatch.setenv("ANKHDJET_PDK_PATH", str(tmp_path / "packs"))
    rng = np.random.default_rng(3)
    W = rng.integers(-1, 2, size=(8, 4)).astype(np.int8)
    model = ModelIR(name="tiny", layers=[
        Layer(name="blk_1", layer_type=LayerType.LINEAR,
              weights={"weight": WeightTensor(name="weight", data=W,
                                              scheme=QuantScheme.TERNARY)},
              input_dim=8, output_dim=4)])
    res = emit_design_bundle(model, tmp_path / "out", macro_rows=8,
                             macro_cols=4, pdk="secret7")
    ma = res["bundle"]["macro_abstracts"]
    assert ma["pdk"] == "secret7"
    assert ma["restricted"] is True
    assert ma["pack_version"] == "9"
