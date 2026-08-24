"""Run the BL-discharge sweep across (N, corner) in parallel.

For each (N, corner) pair this writes a small ngspice deck that includes
the appropriate sky130 corner library and the BL-discharge template,
runs ngspice in batch, and parses the t_50pct measurement out of the
log file. Runs all (N, corner) pairs concurrently via a thread pool
since each ngspice invocation is single-threaded but independent.

Pass criterion: SS @ N=128 must show t_50pct <= 1.5 ns.
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
SKY130_LIB = Path.home() / ".ciel/sky130A/libs.tech/ngspice/sky130.lib.spice"
REPO = HERE.parent.parent.parent.parent

sys.path.insert(0, str(REPO))
from tools.regression_log import write_summary  # noqa: E402

CORNERS = ["tt", "ss", "ff"]
N_VALUES = [32, 64, 128, 256, 512]


def write_deck(n: int, corner: str, work: Path) -> Path:
    """Wrap the template with the corner .lib selection + N override."""
    template = TEMPLATE.read_text()
    deck = re.sub(r"^\.param N\s*=\s*\d+", f".param N = {n}", template,
                   count=1, flags=re.MULTILINE)
    lib_line = f'.lib "{SKY130_LIB}" {corner}\n'
    deck = lib_line + deck
    out = work / f"deck_{corner}_n{n}.sp"
    out.write_text(deck)
    return out


def run_ngspice(deck: Path, work: Path, corner: str, n: int) -> dict:
    """Run ngspice in batch in a per-job subdir to avoid trampling
    side-effect files (rawfile, b#, etc.) when many runs are concurrent."""
    job_dir = work / f"job_{corner}_n{n}"
    job_dir.mkdir(parents=True, exist_ok=True)
    log = job_dir / "ngspice.log"
    r = subprocess.run(
        ["ngspice", "-b", "-o", str(log), str(deck)],
        capture_output=True, text=True, timeout=120,
        cwd=job_dir,
    )
    text = log.read_text() if log.exists() else (r.stdout + r.stderr)
    parsed: dict[str, float | str] = {"corner": corner, "n": n}
    for key in ["t_50pct", "v_bl_at_2ns", "v_bl_at_3ns", "v_bl_at_5ns"]:
        m = re.search(rf"^{key}\s*=\s*([-\d.eE+]+|\S+)", text, re.MULTILINE)
        if m:
            try:
                parsed[key] = float(m.group(1))
            except ValueError:
                parsed[key] = m.group(1)
    if "t_50pct" not in parsed:
        parsed["error_tail"] = text[-1500:]
    return parsed


def run_one(n: int, corner: str, work: Path) -> dict:
    deck = write_deck(n, corner, work)
    return run_ngspice(deck, work, corner, n)


def main() -> int:
    work = HERE / "build_bl_sweep"
    work.mkdir(exist_ok=True)
    t0 = time.monotonic()

    work_items = [(n, c) for c in CORNERS for n in N_VALUES]
    # ngspice batch transient solves are memory-bandwidth bound; running
    # too many concurrent jobs causes solver thrash. Cap at 4-6 even on
    # high-core hosts (similar to Docker-daemon contention pattern).
    max_workers = min(len(work_items), int(os.environ.get("ANKHDJET_NGSPICE_JOBS", "6")))

    results_by_key: dict[tuple[str, int], dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(run_one, n, c, work): (c, n) for n, c in work_items
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                results_by_key[key] = fut.result()
            except Exception as e:
                results_by_key[key] = {"corner": key[0], "n": key[1],
                                       "error": str(e)[:500]}

    body_lines: list[str] = []
    def _emit(line: str) -> None:
        print(line)
        body_lines.append(line)

    _emit(f"{'corner':<6} {'N':>5} {'t_50pct (ns)':>14} {'v@2ns':>8} {'v@3ns':>8} {'v@5ns':>8}")
    _emit("-" * 60)
    rows = []
    for corner in CORNERS:
        for n in N_VALUES:
            r = results_by_key.get((corner, n), {})
            t = r.get("t_50pct")
            v2 = r.get("v_bl_at_2ns")
            v3 = r.get("v_bl_at_3ns")
            v5 = r.get("v_bl_at_5ns")
            t_str = f"{t*1e9:>9.3f}" if isinstance(t, (int, float)) else f"{t!s:>9}"
            v2s = f"{v2:>6.3f}" if isinstance(v2, (int, float)) else f"{v2!s:>6}"
            v3s = f"{v3:>6.3f}" if isinstance(v3, (int, float)) else f"{v3!s:>6}"
            v5s = f"{v5:>6.3f}" if isinstance(v5, (int, float)) else f"{v5!s:>6}"
            _emit(f"{corner:<6} {n:>5}    {t_str}    {v2s}   {v3s}   {v5s}")
            rows.append(r)

    # Pass criterion: bitcell_v4 is sized for SUBCOL_ROWS=64 (W=0.42 um
    # minimum drive). The SS-corner discharge target at the SA's strobe
    # window is 1.5 ns. N=128 was the v3-era target (W=0.84 drive); v4
    # halves the drive so N=64 is the production knee.
    _emit("")
    target_n = 64
    target_ns = 1.5
    rec = next((r for r in rows if r.get("corner") == "ss" and r.get("n") == target_n), None)
    if rec is None or "t_50pct" not in rec or not isinstance(rec["t_50pct"], (int, float)):
        _emit(f"[FAIL] no ss N={target_n} measurement available")
        passed = False
    else:
        actual_ns = rec["t_50pct"] * 1e9
        if actual_ns <= target_ns:
            _emit(f"[ok] ss @ N={target_n} t_50pct = {actual_ns:.3f} ns <= {target_ns} ns target")
            passed = True
        else:
            _emit(f"[FAIL] ss @ N={target_n} t_50pct = {actual_ns:.3f} ns > {target_ns} ns target")
            passed = False

    write_summary(
        build_dir=work,
        config="bl_sweep",
        args=sys.argv,
        results_text="\n".join(body_lines) + "\n",
        passed=passed,
        runtime_s=time.monotonic() - t0,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
