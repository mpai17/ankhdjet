"""Run the precharge recharge-time sweep across (C_BL, corner).

Measures the time for the W=0.42 L=0.15 PMOS to recharge a BL load
from VDD-DELTA_V back to VDD-50 mV, across PVT corners and BL load
capacitances. Pass criterion: SS @ C_BL=32 fF (= SUBCOL=64 loaded BL)
must show t_recharge <= 1 ns.
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
SKY130_LIB = (Path(os.environ.get("PDK_ROOT", Path.home() / ".ciel"))
              / "sky130A/libs.tech/ngspice/sky130.lib.spice")
REPO = HERE.parent.parent.parent.parent

sys.path.insert(0, str(REPO))
from tools.regression_log import write_summary  # noqa: E402

CORNERS = ["tt", "ss", "ff"]
C_BL_F_VALUES = [16e-15, 32e-15, 64e-15]


def write_deck(c_bl: float, corner: str, work: Path) -> Path:
    template = TEMPLATE.read_text()
    deck = re.sub(r"^\.param C_BL_F\s*=\s*\S+", f".param C_BL_F = {c_bl:.3e}",
                  template, count=1, flags=re.MULTILINE)
    lib_line = f'.lib "{SKY130_LIB}" {corner}\n'
    deck = lib_line + deck
    fname = f"deck_{corner}_c{int(c_bl*1e15)}fF.sp"
    out = work / fname
    out.write_text(deck)
    return out


def run_ngspice(deck: Path, work: Path, corner: str, c_bl: float) -> dict:
    tag = f"{corner}_c{int(c_bl*1e15)}fF"
    job_dir = work / f"job_{tag}"
    job_dir.mkdir(parents=True, exist_ok=True)
    log = job_dir / "ngspice.log"
    r = subprocess.run(
        ["ngspice", "-b", "-o", str(log), str(deck)],
        capture_output=True, text=True, timeout=60, cwd=job_dir,
    )
    text = log.read_text() if log.exists() else (r.stdout + r.stderr)
    parsed: dict[str, float | str] = {"corner": corner, "c_bl_fF": c_bl * 1e15}
    for key in ["v_bl_at_pre_start", "t_recharge", "v_bl_final"]:
        m = re.search(rf"^{key}\s*=\s*([-\d.eE+]+|\S+)", text, re.MULTILINE)
        if m:
            try:
                parsed[key] = float(m.group(1))
            except ValueError:
                parsed[key] = m.group(1)
    if "t_recharge" not in parsed:
        parsed["error_tail"] = text[-1500:]
    return parsed


def main() -> int:
    work = HERE / "build_recharge"
    work.mkdir(exist_ok=True)
    t0 = time.monotonic()

    items = [(c, corner) for corner in CORNERS for c in C_BL_F_VALUES]
    max_workers = min(len(items), int(os.environ.get("ANKHDJET_NGSPICE_JOBS", "6")))

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut = {pool.submit(run_ngspice, write_deck(c, k, work), work, k, c): (c, k)
               for (c, k) in items}
        for f in as_completed(fut):
            results.append(f.result())

    body_lines: list[str] = []
    def _emit(line: str) -> None:
        print(line)
        body_lines.append(line)

    _emit(f"\n{'corner':>6} {'C_BL(fF)':>10} {'t_recharge(ps)':>16} {'v_final':>10}")
    _emit("-" * 50)
    for r in sorted(results, key=lambda r: (r["corner"], r["c_bl_fF"])):
        if "t_recharge" in r and isinstance(r["t_recharge"], float):
            t_ps = r["t_recharge"] * 1e12
            _emit(f"{r['corner']:>6} {r['c_bl_fF']:>10.1f} {t_ps:>16.1f} "
                  f"{r.get('v_bl_final', '?'):>10}")
        else:
            _emit(f"{r['corner']:>6} {r['c_bl_fF']:>10.1f} {'N/A':>16} ERROR")
            _emit(r.get("error_tail", "")[-500:])

    # Pass criterion: SS @ C_BL=32 fF must recharge in <= 1 ns from PRE_n
    # falling edge (which is at t=1ns). Reported t_recharge is absolute,
    # so subtract the trigger delay.
    PRE_FALL_S = 1e-9
    ss32 = next((r for r in results
                 if r["corner"] == "ss" and abs(r["c_bl_fF"] - 32.0) < 0.1), None)
    if ss32 is None or "t_recharge" not in ss32 or not isinstance(ss32["t_recharge"], float):
        _emit("\n[FAIL] SS @ 32 fF result missing")
        passed = False
    else:
        dt = ss32["t_recharge"] - PRE_FALL_S
        if dt > 1e-9:
            _emit(f"\n[FAIL] SS @ 32 fF: recharge dt {dt*1e12:.0f} ps > 1000 ps")
            passed = False
        else:
            _emit(f"\n[ok] SS @ 32 fF: recharge dt {dt*1e12:.0f} ps <= 1000 ps")
            passed = True

    write_summary(
        build_dir=work,
        config="recharge",
        args=sys.argv,
        results_text="\n".join(body_lines) + "\n",
        passed=passed,
        runtime_s=time.monotonic() - t0,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
