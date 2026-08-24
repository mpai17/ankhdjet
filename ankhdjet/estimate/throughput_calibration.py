"""Throughput knob calibration from multiple evidence sources.

The area_model.PDK exposes three throughput-derating knobs that default to
zero (RTL-ideal upper bound):
    clock_skew_alpha          - effective_fmax = clock_mhz / (1 + alpha*sqrt(area_mm^2))
    wire_hop_cycles           - register stages per inter-layer activation hop
    kv_access_cycles_per_layer - cycles per layer per token for KV reads

This module collects evidence from independent anchors and back-fits each
knob with low/mid/high bounds per process node:

    silicon_anchor   measured (process, area, fmax) tuples from public open
                     tapeouts (TinyTapeout, Caravel, Efabless ChipIgnite)
    irds_anchor      per-mm global wire delay from IRDS Interconnect roadmap
    sram_anchor      KV-cache SRAM access latency from foundry datasheets +
                     OpenRAM measured points
    openroad_anchor  achieved fmax + bus delay from a local OpenROAD CTS+STA
                     run (optional; not required for the data-only tier)

The fit produces pdk/calibrated.yaml with bracketed knobs the area model
and rendering tools consume.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml


def pdk_data_root() -> Path:
    """The pdk/ data directory: the repo checkout's copy when running
    in-tree, else the copy bundled into the installed wheel."""
    repo = Path(__file__).resolve().parent.parent.parent / "pdk"
    if repo.is_dir():
        return repo
    from importlib.resources import files
    return Path(str(files("ankhdjet"))) / "_pdk"


DATA = pdk_data_root() / "calibration_data"


@dataclass
class SiliconPoint:
    """One measured (process_nm, area_mm^2, achieved_fmax_mhz) point from a
    real open-PDK tapeout. Source is a citation string."""
    process_nm: float
    area_mm2: float
    achieved_fmax_mhz: float
    name: str
    source: str


@dataclass
class IRDSWirePoint:
    """Per-mm global wire delay (picoseconds) at a process node, from a
    cited IRDS / interconnect roadmap entry."""
    process_nm: float
    delay_ps_per_mm: float
    source: str


@dataclass
class OpenROADResult:
    """One OpenROAD CTS+STA measurement on a generated Ankhdjet block.

    Captures what OpenROAD's report_* commands return after a flat
    floorplan + place + CTS + STA pass against a real PDK lib/lef pair.
    Used to validate (or correct) the silicon-back-fit alpha for the
    specific RTL we emit, since the open-tapeout silicon points come
    from arbitrary designs, not from ankhdjet_layer / ankhdjet_pipeline.
    """
    process_nm: float
    block_name: str
    area_mm2: float
    target_clock_mhz: float
    achieved_fmax_mhz: float
    clock_skew_ps: float
    worst_slack_ps: float
    inter_layer_path_ps: float | None = None  # max register-to-register on inter-layer bus
    source: str = "OpenROAD CTS+STA"


@dataclass
class SRAMBound:
    """Bracketed SRAM access latency (nanoseconds) at a (process, bank_size)
    point. low/high bracket the foundry-datasheet vs OpenRAM-measured gap."""
    process_nm: float
    bank_kb: float
    low_ns: float
    high_ns: float
    source: str


@dataclass
class CalibratedKnob:
    low: float
    mid: float
    high: float
    sources: list[str] = field(default_factory=list)


@dataclass
class CalibratedNode:
    process_nm: float
    clock_skew_alpha: CalibratedKnob
    wire_hop_cycles: CalibratedKnob
    kv_access_cycles_per_layer: CalibratedKnob


def load_silicon_points(path: Path | None = None) -> list[SiliconPoint]:
    """Load measured silicon (process, area, fmax) tuples from YAML."""
    p = path or (DATA / "silicon_tapeouts.yaml")
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text()) or []
    return [SiliconPoint(**d) for d in raw]


def load_irds_wire_points(path: Path | None = None) -> list[IRDSWirePoint]:
    """Load per-mm wire delay table from YAML."""
    p = path or (DATA / "irds_wire_delay.yaml")
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text()) or []
    return [IRDSWirePoint(**d) for d in raw]


def load_sram_bounds(path: Path | None = None) -> list[SRAMBound]:
    """Load bracketed SRAM access latency bounds from YAML."""
    p = path or (DATA / "sram_bounds.yaml")
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text()) or []
    return [SRAMBound(**d) for d in raw]


def _min_area_for_point(pt: SiliconPoint, default_min: float) -> float:
    """The 1 mm^2 default applies to mature-node tapeouts where the fmax
    ceiling is dominated by routing congestion or design-target choices,
    not H-tree skew. Two carve-outs admit smaller designs:
      1. Advanced nodes (<= 14 nm) where the skew IS what limits fmax
         (typical ASAP7 anchor designs are <0.01 mm^2 by feature size).
      2. Any source tagged as OpenROAD CTS+STA: those numbers come from
         a real STA pass with repair_timing, so they reflect skew-limited
         fmax regardless of area.
    """
    if pt.process_nm <= 14.0:
        return 1e-5
    if "CTS+STA" in pt.source or "openroad-flow-scripts" in pt.source:
        return 1e-5
    return default_min


def fit_alpha_from_silicon(
    points: list[SiliconPoint],
    target_clock_mhz: dict[float, float],
    min_area_mm2: float = 1.0,
) -> dict[float, CalibratedKnob]:
    """Back-fit clock_skew_alpha per node from measured (area, fmax) points.

    Model: achieved_fmax = ideal_clock / (1 + alpha * sqrt(area))
    Rearranged: alpha = (ideal_clock / achieved_fmax - 1) / sqrt(area)

    `target_clock_mhz[node]` is the per-node small-design ideal fmax (the
    fmax achievable on a sub-mm^2 timing-closed block at that node). Each
    measurement contributes one alpha estimate; we report low/mid/high as
    the per-node 25th/50th/75th percentile across all points.

    `min_area_mm2` filters out small designs (< 1 mm^2 by default) where
    the fmax ceiling is dominated by routing congestion or design-target
    choices rather than H-tree skew. Skew-limited regime starts when the
    clock tree spans enough metal that insertion delay dominates the
    period budget, which empirically kicks in above ~1 mm^2.

    Nodes with fewer than 2 qualifying measurements get widened bounds and
    a `_low_confidence` source tag.
    """
    by_node: dict[float, list[float]] = {}
    sources_by_node: dict[float, list[str]] = {}
    for pt in points:
        node = float(pt.process_nm)
        if pt.area_mm2 < _min_area_for_point(pt, min_area_mm2):
            continue
        ideal = target_clock_mhz.get(node)
        if ideal is None or pt.achieved_fmax_mhz <= 0:
            continue
        if pt.achieved_fmax_mhz >= ideal:
            alpha = 0.0
        else:
            alpha = (ideal / pt.achieved_fmax_mhz - 1.0) / math.sqrt(pt.area_mm2)
        by_node.setdefault(node, []).append(alpha)
        sources_by_node.setdefault(node, []).append(
            f"{pt.name} ({pt.area_mm2:.4f} mm^2, {pt.achieved_fmax_mhz:.0f} MHz) [{pt.source}]"
        )

    out: dict[float, CalibratedKnob] = {}
    for node, alphas in by_node.items():
        alphas_sorted = sorted(alphas)
        n = len(alphas_sorted)
        if n == 1:
            a = alphas_sorted[0]
            out[node] = CalibratedKnob(low=a * 0.5, mid=a, high=a * 2.0,
                                       sources=sources_by_node[node] + ["_low_confidence (single point)"])
        else:
            lo = alphas_sorted[max(0, n // 4)]
            mid = alphas_sorted[n // 2]
            hi = alphas_sorted[min(n - 1, (3 * n) // 4)]
            out[node] = CalibratedKnob(low=lo, mid=mid, high=hi,
                                       sources=sources_by_node[node])
    return out


def fit_wire_hop_cycles(
    irds: list[IRDSWirePoint],
    bus_length_mm: float,
    target_clock_mhz: dict[float, float],
) -> dict[float, CalibratedKnob]:
    """Convert per-mm wire delay to register-hop cycles at each node.

    cycles = ceil(bus_length_mm * delay_ps_per_mm * clock_ghz / 1000)

    bus_length_mm is the typical inter-layer activation bus distance; for
    a reticle-class ~815 mm^2 die we assume ~10 mm (reasonable layer-to-layer
    spacing on a square die). Bracketing widens by +/-50% to cover layout
    spread.
    """
    out: dict[float, CalibratedKnob] = {}
    for pt in irds:
        ideal = target_clock_mhz.get(pt.process_nm, 0.0)
        if ideal <= 0:
            continue
        clock_ghz = ideal / 1000.0
        delay_cycles = pt.delay_ps_per_mm * bus_length_mm * clock_ghz / 1000.0
        out[pt.process_nm] = CalibratedKnob(
            low=max(1, math.ceil(delay_cycles * 0.5)),
            mid=max(1, math.ceil(delay_cycles)),
            high=max(1, math.ceil(delay_cycles * 1.5)),
            sources=[f"IRDS {pt.delay_ps_per_mm:.0f} ps/mm * {bus_length_mm} mm @ {ideal} MHz [{pt.source}]"],
        )
    return out


def fit_kv_cycles(
    bounds: list[SRAMBound],
    bank_kb: float,
    accesses_per_layer: int,
    target_clock_mhz: dict[float, float],
) -> dict[float, CalibratedKnob]:
    """Convert SRAM access latency bounds into per-layer KV cycle counts.

    kv_cycles = ceil(access_ns * clock_ghz) * accesses_per_layer

    Picks the bracket nearest the requested bank_kb at each node. accesses
    per layer = 2 (read prior K + V) for a single-token decode; multiplied
    by heads upstream by the area model's KV cost calculation.
    """
    by_node: dict[float, list[SRAMBound]] = {}
    for b in bounds:
        by_node.setdefault(b.process_nm, []).append(b)

    out: dict[float, CalibratedKnob] = {}
    for node, lst in by_node.items():
        ideal = target_clock_mhz.get(node, 0.0)
        if ideal <= 0:
            continue
        # Closest bank size to requested
        nearest = min(lst, key=lambda b: abs(math.log2(b.bank_kb / bank_kb)) if bank_kb > 0 and b.bank_kb > 0 else 0.0)
        clock_ghz = ideal / 1000.0
        lo_cycles = max(1, math.ceil(nearest.low_ns * clock_ghz)) * accesses_per_layer
        hi_cycles = max(1, math.ceil(nearest.high_ns * clock_ghz)) * accesses_per_layer
        mid_cycles = (lo_cycles + hi_cycles) // 2
        out[node] = CalibratedKnob(
            low=lo_cycles, mid=mid_cycles, high=hi_cycles,
            sources=[f"SRAM {nearest.bank_kb:.0f} KB: {nearest.low_ns:.1f}-{nearest.high_ns:.1f} ns @ {ideal} MHz [{nearest.source}]"],
        )
    return out


def extrapolate_alpha(
    anchored: dict[float, CalibratedKnob],
    target_nodes: list[float],
    anchor_node: float = 130.0,
) -> dict[float, CalibratedKnob]:
    """Project clock_skew_alpha to nodes that have no direct silicon anchor.

        alpha(target) = alpha(ref) * (node_ref / target_node) ** beta

    `beta` is fit from the anchored nodes' alpha values via linear regression
    in log-log space when at least two anchors exist. A single anchor falls
    back to beta=0.5 (PVT-variance ~ 1/sqrt(node), per Hashimoto/Yamamoto/Onodera
    ISQED 2005 follow-up work). Bracketing widens for far-extrapolated nodes.
    """
    if not anchored:
        return {n: CalibratedKnob(0.0, 0.0, 0.0, ["_no_anchor"]) for n in target_nodes}

    # Fit beta in log-log space if we have >=2 anchors
    anchor_pts = [(n, anchored[n].mid) for n in sorted(anchored) if anchored[n].mid > 0]
    if len(anchor_pts) >= 2:
        # log(alpha) = log(alpha_ref) + beta * log(node_ref / node)
        # Pick the smallest-node anchor as ref so all target_nodes <= ref scale up
        n_ref, a_ref = anchor_pts[0]
        xs = [math.log(n_ref / n) for n, _ in anchor_pts]
        ys = [math.log(a / a_ref) for _, a in anchor_pts]
        sx, sy, sxx, sxy = sum(xs), sum(ys), sum(x*x for x in xs), sum(x*y for x, y in zip(xs, ys))
        n = len(xs)
        denom = n*sxx - sx*sx
        beta_fit = (n*sxy - sx*sy) / denom if denom != 0 else 0.5
        beta_fit = max(0.0, min(2.0, beta_fit))  # sanity clamp
        beta_low, beta_mid, beta_high = beta_fit * 0.7, beta_fit, beta_fit * 1.3
        ref_source = f"fit beta={beta_fit:.2f} from {len(anchor_pts)} anchors {[f'{n:g}nm' for n,_ in anchor_pts]}"
    else:
        n_ref, a_ref = anchor_pts[0]
        beta_low, beta_mid, beta_high = 0.25, 0.50, 0.75
        ref_source = f"single anchor at {n_ref:g}nm; default beta=0.5 +/- (PVT 1/sqrt(node))"

    out: dict[float, CalibratedKnob] = {}
    for node in target_nodes:
        node = float(node)
        if node in anchored:
            out[node] = anchored[node]
            continue
        ratio = n_ref / node
        # For ratio<1 (target_node larger than ref), bracket order flips,
        # so sort the three candidates ascending into low/mid/high.
        cands = sorted([
            a_ref * ratio ** beta_low,
            a_ref * ratio ** beta_mid,
            a_ref * ratio ** beta_high,
        ])
        out[node] = CalibratedKnob(
            low=cands[0], mid=cands[1], high=cands[2],
            sources=[f"_extrapolated from {n_ref:g}nm (alpha={a_ref:.3f}); {ref_source}"],
        )
    return out


def emit_calibrated_yaml(
    nodes: dict[float, CalibratedNode],
    path: Path,
) -> None:
    """Write the per-node bracketed knobs to a YAML file."""
    out = {"nodes": {}}
    for node, cal in sorted(nodes.items()):
        out["nodes"][f"{node:g}nm"] = {
            "process_nm": cal.process_nm,
            "clock_skew_alpha":          asdict(cal.clock_skew_alpha),
            "wire_hop_cycles":           asdict(cal.wire_hop_cycles),
            "kv_access_cycles_per_layer": asdict(cal.kv_access_cycles_per_layer),
        }
    path.write_text(
        "# Generated by tools/calibrate_throughput.py\n"
        "# Each knob is bracketed (low, mid, high) with provenance per evidence anchor.\n"
        "# Consumed by ankhdjet.estimate.area_model + ankhdjet fit when --bracketed is set.\n\n"
        + yaml.safe_dump(out, sort_keys=False)
    )


def load_calibrated(path: Path | None = None) -> dict[float, CalibratedNode]:
    """Load pdk/calibrated.yaml back into CalibratedNode objects keyed by process_nm."""
    p = path or (pdk_data_root() / "calibrated.yaml")
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text())
    out: dict[float, CalibratedNode] = {}
    for _, entry in (raw.get("nodes") or {}).items():
        n = float(entry["process_nm"])
        out[n] = CalibratedNode(
            process_nm=n,
            clock_skew_alpha=CalibratedKnob(**entry["clock_skew_alpha"]),
            wire_hop_cycles=CalibratedKnob(**entry["wire_hop_cycles"]),
            kv_access_cycles_per_layer=CalibratedKnob(**entry["kv_access_cycles_per_layer"]),
        )
    return out


def apply_bracket(pdk, calibrated: dict[float, CalibratedNode], bracket: str = "mid"):
    """Return a copy of `pdk` with throughput knobs overridden by the
    calibrated.yaml values at the requested bracket (low|mid|high)."""
    from dataclasses import replace
    cal = calibrated.get(float(pdk.process_nm))
    if cal is None:
        return pdk
    pick = lambda k: getattr(k, bracket)
    # Multi-domain knobs are NOT bracketed (they're architectural choices,
    # not measurement uncertainties); preserve whatever the PDK YAML set.
    return replace(
        pdk,
        clock_skew_alpha          = float(pick(cal.clock_skew_alpha)),
        wire_hop_cycles           = int(pick(cal.wire_hop_cycles)),
        kv_access_cycles_per_layer = int(pick(cal.kv_access_cycles_per_layer)),
    )
