"""Macro-level structural LVS: verify the flattened extracted
netlist of macro_array_pc has the expected device count and that
each precharge D net is shared with one bitcell column's drain.

A full netgen flat-LVS against a hand-rolled reference is too
expensive at 64x32 (2080 devices, 30+ minute runtime). This test
checks the structural invariants that catch the class of bugs we've
hit:
  - Drain-source shorts (would show D net = S net)
  - Precharge-not-wired (would show precharge D nets disjoint from
    bitcell D nets)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from conftest import BUILD_DIR


MACRO_RE = re.compile(r"^macro_array_pc_(\d+)x(\d+)_(all_pos|all_neg|checker)$")


def _flat_extract(macro: str, tmp_path: Path) -> Path:
    """Flatten the macro and run extraction; return path to the SPICE."""
    out = BUILD_DIR / f"{macro}_flat.spice"
    if out.exists():
        return out
    tcl = (
        f"drc off\n"
        f"load {macro}\n"
        f"flatten {macro}_flat\n"
        f"load {macro}_flat\n"
        f"select top cell\n"
        f"extract no all\n"
        f"extract do local\n"
        f"extract no capacitance\n"
        f"extract no resistance\n"
        f"extract all\n"
        f"ext2spice lvs\n"
        f"ext2spice cthresh infinite\n"
        f"ext2spice rthresh infinite\n"
        f"ext2spice subcircuit on\n"
        f"ext2spice -o {macro}_flat.spice\n"
        f"quit -noprompt\n"
    )
    subprocess.run(
        ["magic", "-dnull", "-noconsole"],
        cwd=BUILD_DIR, input=tcl, text=True,
        capture_output=True, timeout=600,
    )
    assert out.exists(), f"flat extraction did not produce {out}"
    return out


def _discover_macros() -> list[tuple[str, int, int, str]]:
    out: list[tuple[str, int, int, str]] = []
    if not BUILD_DIR.exists():
        return out
    for mag in sorted(BUILD_DIR.glob("macro_array_pc_*.mag")):
        if mag.stem.endswith("_flat"):
            continue
        m = MACRO_RE.match(mag.stem)
        if m:
            out.append((mag.stem, int(m.group(1)), int(m.group(2)), m.group(3)))
    return out


@pytest.mark.parametrize("cell,n_rows,n_cols,pattern", _discover_macros())
def test_macro_structural_lvs(cell: str, n_rows: int, n_cols: int,
                               pattern: str, tmp_path: Path) -> None:
    spice = _flat_extract(cell, tmp_path)
    text = spice.read_text()

    # Filter to bitcell + precharge instances only; the macro also
    # contains a strongarm SA (5 NMOS + 4 PMOS) whose pin nets aren't
    # part of the bitcell-array architecture being checked here.
    # Magic's flatten anonymizes instance names, so match by the
    # cell-internal net paths that survive the flatten:
    #   bitcell pins reference v4_array_*/bitcell_v4_*.{S,G,D}
    #   precharge S = VPWR; SA pins reference strongarm_0.*
    bitcell_lines = [
        ln for ln in text.splitlines()
        if "sky130_fd_pr__nfet_01v8" in ln and ln.startswith("X")
           and "/bitcell_v4_" in ln
    ]
    precharge_lines = [
        ln for ln in text.splitlines()
        if "sky130_fd_pr__pfet_01v8" in ln and ln.startswith("X")
           and "strongarm_0" not in ln
    ]
    sa_n_lines = [
        ln for ln in text.splitlines()
        if "sky130_fd_pr__nfet_01v8" in ln and ln.startswith("X")
           and ("strongarm_0" in ln or "SA_" in ln)
    ]
    sa_p_lines = [
        ln for ln in text.splitlines()
        if "sky130_fd_pr__pfet_01v8" in ln and ln.startswith("X")
           and ("strongarm_0" in ln or "SA_" in ln)
    ]

    assert len(bitcell_lines) == n_rows * n_cols, (
        f"{cell}: expected {n_rows * n_cols} bitcell nfet instances, "
        f"got {len(bitcell_lines)}"
    )
    assert len(precharge_lines) == n_cols, (
        f"{cell}: expected {n_cols} precharge pfet instances, "
        f"got {len(precharge_lines)}"
    )
    assert len(sa_n_lines) == 0, (
        f"{cell}: expected 0 strongarm NMOS in macro_array_pc (SA is "
        f"a separate hard macro placed at chip level by LibreLane), "
        f"got {len(sa_n_lines)}"
    )
    assert len(sa_p_lines) == 0, (
        f"{cell}: expected 0 strongarm PMOS in macro_array_pc, "
        f"got {len(sa_p_lines)}"
    )

    # Re-bind for downstream net checks (bitcell-only).
    nfet_lines = bitcell_lines
    pfet_lines = precharge_lines

    # Each device line: X<name> p1 p2 p3 p4 model ...
    # NMOS PCell pin order: S G D B
    bitcell_d_nets = {ln.split()[3] for ln in nfet_lines}
    precharge_d_nets = {ln.split()[3] for ln in pfet_lines}

    # Drain-source short check: no bitcell should have D == S
    for ln in nfet_lines:
        toks = ln.split()
        s_net, d_net = toks[1], toks[3]
        assert s_net != d_net, (
            f"{cell}: bitcell instance {toks[0]} has D == S = {d_net} "
            f"(drain-source short)"
        )

    # Pattern-aware net-count expectations:
    #   all_pos -> all bitcell drains on BL+ per col -> n_cols distinct
    #   all_neg -> all bitcell drains on BL- per col -> n_cols distinct
    #   checker -> half cells on BL+, half on BL- per col -> 2*n_cols
    expected_bd = n_cols if pattern in ("all_pos", "all_neg") else 2 * n_cols
    assert len(bitcell_d_nets) == expected_bd, (
        f"{cell}: expected {expected_bd} distinct bitcell D nets "
        f"({pattern}), got {len(bitcell_d_nets)}"
    )
    assert len(precharge_d_nets) == n_cols, (
        f"{cell}: expected {n_cols} distinct precharge D nets, "
        f"got {len(precharge_d_nets)}"
    )

    # Precharge wiring depends on pattern:
    #   all_pos / checker -> BL+ has bitcell drains; precharge merges
    #     with BL+ -> all 32 precharge D nets must be a SUBSET of
    #     bitcell D nets.
    #   all_neg -> no bitcell uses BL+; precharge D nets are distinct
    #     from any bitcell D net (all bitcell drains on BL-).
    if pattern in ("all_pos", "checker"):
        assert precharge_d_nets <= bitcell_d_nets, (
            f"{cell}: precharge D nets not all merged with bitcell D "
            f"nets ({pattern} should have precharge -> BL+ wired):\n"
            f"  unmerged precharge nets: "
            f"{sorted(precharge_d_nets - bitcell_d_nets)[:5]}"
        )
    else:  # all_neg
        assert precharge_d_nets.isdisjoint(bitcell_d_nets), (
            f"{cell}: precharge D nets should NOT overlap bitcell D "
            f"nets in all_neg (precharge on BL+, bitcells on BL-):\n"
            f"  unexpected overlap: "
            f"{sorted(precharge_d_nets & bitcell_d_nets)[:5]}"
        )
