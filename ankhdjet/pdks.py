"""PDK pack discovery and validation.

A PDK plugs into the compiler as a pack: a directory whose pack.yaml
declares identity and capability tiers, with everything the core
consumes expressed as data (core code never names a specific PDK).
Tiers are optional and degrade gracefully:

    estimate    estimators/*.yaml area/throughput descriptors
    abstracts   abstracts.yaml macro-contract constants plus the
                anchor's extracted LEF as the conformance reference
    physical    cells and flow collateral (repository-side machinery)

Discovery precedence, first match winning on name collisions:
directories on ANKHDJET_PDK_PATH (each entry a pack or a directory of
packs), installed packages exposing the "ankhdjet.pdks" entry-point
group, then the data root (a repo checkout's pdk/ or the wheel's
bundled copy). Loose descriptor YAMLs at the data root stay
discoverable so shared multi-node descriptor files keep working. The
public repo and wheel carry only open packs; a restricted pack's flag
travels into every bundle manifest that consumes it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ankhdjet.estimate.throughput_calibration import pdk_data_root

PACK_MANIFEST = "pack.yaml"
ENTRY_POINT_GROUP = "ankhdjet.pdks"
TIERS = ("estimate", "abstracts", "physical")


@dataclass
class Pack:
    name: str
    root: Path
    version: str = "0"
    tiers: tuple[str, ...] = ()
    restricted: bool = False
    provenance: str = ""
    physical: str = ""   # "repository" = collateral ships with the repo

    @classmethod
    def load(cls, root: Path) -> "Pack":
        man = yaml.safe_load((root / PACK_MANIFEST).read_text()) or {}
        return cls(
            name=str(man.get("name", root.name)), root=root,
            version=str(man.get("version", "0")),
            tiers=tuple(man.get("tiers", [])),
            restricted=bool(man.get("restricted", False)),
            provenance=str(man.get("provenance", "")),
            physical=str(man.get("physical", "")),
        )

    def estimator_files(self) -> list[Path]:
        d = self.root / "estimators"
        return sorted(d.glob("*.yaml")) if d.is_dir() else []

    def abstracts_file(self) -> Path | None:
        p = self.root / "abstracts.yaml"
        return p if p.exists() else None


def _expand(root: Path) -> list[Path]:
    """A candidate root is a pack itself or a directory of packs."""
    if (root / PACK_MANIFEST).exists():
        return [root]
    if root.is_dir():
        return [d for d in sorted(root.iterdir())
                if (d / PACK_MANIFEST).exists()]
    return []


def _entry_point_roots() -> list[Path]:
    from importlib.metadata import entry_points
    roots: list[Path] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            obj = ep.load()
        except Exception:
            continue
        if callable(obj):
            obj = obj()
        obj = getattr(obj, "data_location", obj)
        roots.append(Path(str(obj)))
    return roots


def discover_packs() -> dict[str, Pack]:
    """All reachable packs by name, in discovery precedence."""
    packs: dict[str, Pack] = {}
    roots: list[Path] = []
    for part in os.environ.get("ANKHDJET_PDK_PATH", "").split(os.pathsep):
        if part:
            roots.append(Path(part))
    roots.extend(_entry_point_roots())
    roots.append(pdk_data_root())
    for root in roots:
        for d in _expand(root):
            pack = Pack.load(d)
            packs.setdefault(pack.name, pack)
    return packs


def descriptor_files() -> list[Path]:
    """Estimator descriptor YAMLs: every pack's estimators/ plus the
    loose (shared, multi-node) YAMLs at the data root."""
    seen: set[Path] = set()
    out: list[Path] = []
    for pack in discover_packs().values():
        for f in pack.estimator_files():
            r = f.resolve()
            if r not in seen:
                seen.add(r)
                out.append(f)
    for f in sorted(pdk_data_root().glob("*.yaml")):
        if f.name.startswith("calibrat"):
            continue
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            out.append(f)
    return out


def discover_pdks() -> dict:
    """All estimator descriptors by name (ankhdjet.estimate.area_model.PDK)."""
    from ankhdjet.estimate.area_model import PDK
    out: dict = {}
    for yml in descriptor_files():
        try:
            p = PDK.from_yaml(yml)
            out.setdefault(p.name, p)
        except Exception:
            try:
                for p in PDK.all_from_yaml(yml):
                    out.setdefault(p.name, p)
            except Exception:
                continue
    return out


def abstract_pack(pdk: str) -> tuple[dict, Pack]:
    """The abstract-constant set and its pack for a PDK name."""
    packs = discover_packs()
    pack = packs.get(pdk)
    if pack is None or pack.abstracts_file() is None:
        have = sorted(n for n, p in packs.items()
                      if p.abstracts_file() is not None)
        raise ValueError(
            f"no abstracts tier for pdk {pdk!r} (packs providing "
            f"abstracts: {have})")
    params = yaml.safe_load(pack.abstracts_file().read_text())
    return params, pack


def lef_size_and_pins(text: str):
    """Parse a LEF into (SIZE, {pin: [(layer, x1, y1, x2, y2), ...]})
    with coordinates rounded to 1 nm-scale precision."""
    size = None
    pins: dict[str, list[tuple]] = {}
    pin = layer = None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", s)
        if m:
            size = (float(m.group(1)), float(m.group(2)))
        m = re.match(r"PIN\s+(\S+)\s*$", s)
        if m:
            pin, layer = m.group(1), None
            continue
        if pin and s == f"END {pin}":
            pin = layer = None
            continue
        m = re.match(r"LAYER\s+(\S+)\s*;", s)
        if m and pin:
            layer = m.group(1)
            continue
        m = re.match(
            r"RECT\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*;", s)
        if m and pin and layer:
            pins.setdefault(pin, []).append(
                (layer, *(round(float(x), 3) for x in m.groups())))
    return size, pins


def validate_pack(name: str) -> list[str]:
    """Conformance-check one pack; returns a list of issues (empty =
    conforms). estimate: every descriptor YAML loads. abstracts: the
    constants regenerate the anchor's extracted LEF (SIZE equal, every
    generated rectangle present in the anchor pin's rectangles, signal
    pins exactly). physical: declared collateral directories exist."""
    packs = discover_packs()
    if name not in packs:
        return [f"pack {name!r} not found (have: {sorted(packs)})"]
    pack = packs[name]
    issues: list[str] = []
    for t in pack.tiers:
        if t not in TIERS:
            issues.append(f"unknown tier {t!r} (known: {list(TIERS)})")

    if "estimate" in pack.tiers:
        from ankhdjet.estimate.area_model import PDK
        files = pack.estimator_files()
        if not files:
            issues.append("estimate tier declared but estimators/ is empty")
        for yml in files:
            try:
                PDK.from_yaml(yml)
            except Exception:
                try:
                    if not PDK.all_from_yaml(yml):
                        issues.append(f"{yml.name}: no descriptors")
                except Exception as e:
                    issues.append(f"{yml.name}: does not load ({e})")

    if "abstracts" in pack.tiers:
        issues += _validate_abstracts(pack)

    if "physical" in pack.tiers:
        in_pack = any((pack.root / d).is_dir() for d in ("cells", "flow"))
        if not in_pack and pack.physical != "repository":
            issues.append("physical tier declared but no cells/ or flow/ "
                          "in the pack (or physical: repository)")
    return issues


def _validate_abstracts(pack: Pack) -> list[str]:
    import tempfile

    from ankhdjet.backend.abstracts import emit_macro_abstracts

    f = pack.abstracts_file()
    if f is None:
        return ["abstracts tier declared but abstracts.yaml is missing"]
    params = yaml.safe_load(f.read_text())
    anchor = params.get("anchor")
    if not anchor or not {"rows", "cols", "lef"} <= set(anchor):
        return ["abstracts.yaml needs anchor: {rows, cols, lef}"]
    ref_lef = pack.root / anchor["lef"]
    if not ref_lef.exists():
        return [f"anchor LEF missing: {anchor['lef']}"]
    with tempfile.TemporaryDirectory() as td:
        ab = emit_macro_abstracts(anchor["rows"], anchor["cols"], td,
                                  pdk=pack.name)
        got_size, got = lef_size_and_pins(ab["lef"].read_text())
    ref_size, ref = lef_size_and_pins(ref_lef.read_text())
    issues: list[str] = []
    if got_size != ref_size:
        issues.append(f"SIZE {got_size} != anchor {ref_size}")
    for pin, rects in got.items():
        if pin not in ref:
            issues.append(f"pin {pin} absent from anchor LEF")
            continue
        for rect in rects:
            if rect not in ref[pin]:
                issues.append(f"pin {pin}: rect {rect} not in anchor")
        signal = not pin.startswith(("VPWR", "VGND"))
        if signal and len(rects) != len(ref[pin]):
            issues.append(f"pin {pin}: {len(rects)} rects vs "
                          f"anchor {len(ref[pin])}")
    return issues
