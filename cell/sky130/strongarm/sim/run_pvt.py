"""StrongARM PVT sweep (schematic OR post-layout).

The SA test deck (test_harness.sp) instantiates one
`Xsa ... strongarm` line. This runner prepends the .include line for
the strongarm subckt:

  ANKHDJET_SA_SOURCE=schematic   (default)  cell/sky130/strongarm/strongarm_schematic.spice
  ANKHDJET_SA_SOURCE=extracted              cell/sky130/strongarm/build/strongarm_extracted.spice
                                          (regenerate via extract_parasitics.tcl first)

Sweep is fan-out parallel via ThreadPoolExecutor; each ngspice job
runs in its own subdir.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATE = HERE / "test_harness.sp"
REPO = HERE.parent.parent.parent.parent

sys.path.insert(0, str(REPO))
from tools.regression_log import write_summary  # noqa: E402
SCHEMATIC = HERE.parent / "strongarm_schematic.spice"
EXTRACTED = HERE.parent / "build" / "strongarm_extracted.spice"
SKY130_LIB = Path.home() / ".volare/sky130A/libs.tech/ngspice/sky130.lib.spice"

CORNERS = ["tt", "ss", "ff"]
VIN_DIFF_MV = [25, 50, 75, 100, 150, 200]

# Schematic port order — what the deck's Xsa line uses.
PORT_ORDER = "BLP BLN OUTP OUTM STROBE VDD VGND"


def _resolve_source(work: Path) -> Path:
    """Return path to a strongarm-subckt .spice that uses PORT_ORDER.

    For schematic: just the checked-in schematic file (already in
    PORT_ORDER). For extracted: load the netlist, rewrite the
    `.subckt strongarm <pins>` line to PORT_ORDER (only the external
    declaration; body references by name are unaffected), and write
    a normalized copy under `work/`.
    """
    mode = os.environ.get("ANKHDJET_SA_SOURCE", "schematic").lower()
    if mode == "schematic":
        if not SCHEMATIC.exists():
            raise FileNotFoundError(f"schematic not found: {SCHEMATIC}")
        return SCHEMATIC
    if mode == "extracted":
        if not EXTRACTED.exists():
            raise FileNotFoundError(
                f"extracted netlist not found: {EXTRACTED}\n"
                "Run: cd cell/sky130/strongarm/build && magic -dnull "
                "-noconsole < ../extract_parasitics.tcl"
            )
        text = EXTRACTED.read_text()
        text = re.sub(
            r"^\.subckt\s+strongarm\b.*$",
            f".subckt strongarm {PORT_ORDER}",
            text, count=1, flags=re.MULTILINE,
        )
        out = work / "strongarm_normalized.spice"
        out.write_text(text)
        return out
    raise ValueError(f"ANKHDJET_SA_SOURCE must be schematic|extracted, got {mode!r}")


def write_deck(vin_diff_mv: int, corner: str, source: Path, job: Path) -> Path:
    template = TEMPLATE.read_text()
    deck = re.sub(r"^\.param VIN_DIFF_V\s*=\s*[\d.]+",
                  f".param VIN_DIFF_V    = {vin_diff_mv/1000.0:.4f}",
                  template, count=1, flags=re.MULTILINE)
    header = f'.lib "{SKY130_LIB}" {corner}\n.include "{source}"\n'
    deck = header + deck
    out = job / f"deck_{corner}_v{vin_diff_mv}.sp"
    out.write_text(deck)
    return out


def parse_log(text: str) -> dict:
    out: dict[str, float | str] = {}
    for key in ["t_outp_high", "t_outm_high", "t_outp_low", "t_outm_low",
                "v_outp_final", "v_outm_final"]:
        m = re.search(rf"^{key}\s*=\s*([-\d.eE+]+|\S+)", text, re.MULTILINE)
        if m:
            try:
                out[key] = float(m.group(1))
            except ValueError:
                out[key] = m.group(1)
    return out


def run_one(vin_diff_mv: int, corner: str, source: Path, work: Path) -> dict:
    job = work / f"job_{corner}_v{vin_diff_mv}"
    job.mkdir(parents=True, exist_ok=True)
    deck = write_deck(vin_diff_mv, corner, source, job)
    log = job / "ngspice.log"
    r = subprocess.run(
        ["ngspice", "-b", "-o", str(log), str(deck)],
        capture_output=True, text=True, timeout=180, cwd=job,
    )
    text = log.read_text() if log.exists() else (r.stdout + r.stderr)
    parsed = parse_log(text)
    parsed["corner"] = corner
    parsed["vin_diff_mv"] = vin_diff_mv

    t_outm_h = parsed.get("t_outm_high")
    t_outp_l = parsed.get("t_outp_low")
    v_outp_f = parsed.get("v_outp_final")
    v_outm_f = parsed.get("v_outm_final")

    if (isinstance(v_outp_f, (int, float)) and isinstance(v_outm_f, (int, float)) and
        v_outm_f > v_outp_f + 0.5):
        parsed["resolved"] = True
        cands = [t for t in (t_outm_h, t_outp_l) if isinstance(t, (int, float))]
        parsed["t_resolve_ns"] = (min(cands) - 1.0e-9) * 1e9 if cands else None
    else:
        parsed["resolved"] = False
        parsed["t_resolve_ns"] = None
    return parsed


def main() -> int:
    mode = os.environ.get("ANKHDJET_SA_SOURCE", "schematic").lower()
    work = HERE / f"build_pvt_{mode}"
    work.mkdir(exist_ok=True)
    t0 = time.monotonic()
    source = _resolve_source(work)
    body_lines: list[str] = []
    def _emit(line: str) -> None:
        print(line)
        body_lines.append(line)

    _emit(f"sweeping at corners={CORNERS}, Vdiff={VIN_DIFF_MV} mV, "
          f"source={mode} ({source.name})")

    items = [(v, c) for c in CORNERS for v in VIN_DIFF_MV]
    n_jobs = min(len(items), int(os.environ.get("ANKHDJET_NGSPICE_JOBS", "6")))

    results: dict[tuple[str, int], dict] = {}
    with ThreadPoolExecutor(max_workers=n_jobs) as pool:
        futs = {pool.submit(run_one, v, c, source, work): (c, v) for v, c in items}
        for f in as_completed(futs):
            key = futs[f]
            try:
                results[key] = f.result()
            except Exception as e:
                results[key] = {"corner": key[0], "vin_diff_mv": key[1],
                                "error": str(e)[:300]}

    _emit(f"\n{'corner':<6} {'Vdiff(mV)':>10} {'resolved':>9} {'t_resolve(ps)':>14} "
          f"{'v_outp':>8} {'v_outm':>8}")
    _emit("-" * 70)
    for c in CORNERS:
        for v in VIN_DIFF_MV:
            r = results.get((c, v), {})
            t = r.get("t_resolve_ns")
            t_s = f"{t*1000:>10.1f}" if isinstance(t, (int, float)) else f"{'--':>10}"
            v_p = r.get("v_outp_final")
            v_m = r.get("v_outm_final")
            v_p_s = f"{v_p:>6.3f}" if isinstance(v_p, (int, float)) else f"{'--':>6}"
            v_m_s = f"{v_m:>6.3f}" if isinstance(v_m, (int, float)) else f"{'--':>6}"
            _emit(f"{c:<6} {v:>10}    {str(r.get('resolved', False)):>7}    "
                  f"{t_s}    {v_p_s}   {v_m_s}")

    ss100 = results.get(("ss", 100), {})
    target_ns = 3.0
    t = ss100.get("t_resolve_ns")
    if not ss100.get("resolved"):
        _emit(f"\n[FAIL] SS @ 100 mV did not resolve ({mode})")
        passed = False
    elif not isinstance(t, (int, float)) or t > target_ns:
        _emit(f"\n[FAIL] SS @ 100 mV t_resolve = {t:.3f} ns > {target_ns} ns")
        passed = False
    else:
        _emit(f"\n[ok] {mode} SS @ 100 mV t_resolve = {t:.3f} ns <= {target_ns:.1f} ns")
        passed = True

    write_summary(
        build_dir=work,
        config=f"pvt_{mode}",
        args=sys.argv,
        results_text="\n".join(body_lines) + "\n",
        passed=passed,
        runtime_s=time.monotonic() - t0,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
