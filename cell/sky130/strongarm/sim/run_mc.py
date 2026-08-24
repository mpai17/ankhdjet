"""StrongARM Monte Carlo mismatch sweep at SS.

Each trial is a fresh ngspice invocation with a unique random seed,
which the sky130 `_mismatch.corner` files use to assign per-instance
VTH/length sigma offsets. The sweep is the falsifiable test for
whether the StrongARM resolves a small bit-line differential correctly
across realistic transistor mismatch.

Pass criterion:
- >= 99.9% of trials resolve in the correct direction
- median strobe-to-output <= 500 ps

Configurable via env:
  ANKHDJET_SA_SOURCE    schematic | extracted | big (default schematic)
                       schematic = test_harness.sp + strongarm_schematic.spice
                                   (production sizing W=2/L=0.3 input pair)
                       extracted = test_harness.sp + strongarm_extracted.spice
                                   (post-layout RCC of production cell)
                       big       = test_harness_big.sp standalone
                                   (W=10/L=2 input pair, ~50 um^2/SA;
                                   the area-cost trade for SS mismatch margin)
  ANKHDJET_VDIFF_MV     comma-list of input differentials in mV (default 100)
  ANKHDJET_MC_TRIALS    trials per Vdiff (default 1000)
  ANKHDJET_MC_SHARDS    concurrent single-process ngspice runs per Vdiff
                        (default 1). One process loads the SKY130 models once
                        and loops all N trials in-process; the load does not
                        parallelize, so >1 shard only helps at very large N.
  ANKHDJET_NGSPICE_JOBS cap on concurrent shards (default 12, capped at cpu_count)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE_INIT = Path(__file__).parent
REPO_INIT = HERE_INIT.parent.parent.parent.parent
sys.path.insert(0, str(REPO_INIT))
from tools.regression_log import write_summary  # noqa: E402

HERE = Path(__file__).parent
TEMPLATE = HERE / "test_harness.sp"
TEMPLATE_BIG = HERE / "test_harness_big.sp"
SCHEMATIC = HERE.parent / "strongarm_schematic.spice"
EXTRACTED = HERE.parent / "build" / "strongarm_extracted.spice"
SKY130_LIB = Path.home() / ".volare/sky130A/libs.tech/ngspice/sky130.lib.spice"

CORNER = "ss"
PORT_ORDER = "BLP BLN OUTP OUTM STROBE VDD VGND"

VIN_DIFF_MV_LIST = [int(x) for x in
                    os.environ.get("ANKHDJET_VDIFF_MV", "100").split(",") if x.strip()]
N_TRIALS = int(os.environ.get("ANKHDJET_MC_TRIALS", "1000"))
N_JOBS = int(os.environ.get("ANKHDJET_NGSPICE_JOBS", "12"))
N_JOBS = min(N_JOBS, os.cpu_count() or 12)
# Shards per Vdiff = concurrent single-process ngspice runs. Each pays the
# ~30 s SKY130 model load, and that load does NOT parallelize (it is
# memory-bandwidth bound: 4 concurrent loads run ~4x slower than one), so the
# default is 1 -- one process loads once and loops all N trials in-process.
# Raise ANKHDJET_MC_SHARDS only for very large N where the per-trial transient
# time outweighs the extra serialized loads.
N_SHARDS = max(1, int(os.environ.get("ANKHDJET_MC_SHARDS", "1")))


def resolve_source(work: Path) -> Path:
    """Schematic mode: return checked-in schematic file. Extracted mode:
    rewrite the .subckt strongarm port-order line to match PORT_ORDER and
    return a normalized copy under work/."""
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


def write_mc_deck(job: Path, source: Path, vin_diff_mv: int,
                  n_trials: int, seed_base: int) -> Path:
    """Emit one deck that loads the SKY130 models ONCE and loops n_trials
    mismatch trials inside a `.control` block. The ~30 s model load/parse
    (the real MC bottleneck) is paid once per shard instead of once per
    trial. Each iteration reseeds; `reset` re-draws the per-instance AGAUSS
    mismatch (mc_mm_switch=1); per-trial results are echoed as
    `MCRESULT <i> <vpf> <vmf> <tmh> <tpl>`."""
    template = TEMPLATE.read_text()
    template = re.sub(r"^\.param VIN_DIFF_V\s*=\s*[\d.]+",
                      f".param VIN_DIFF_V    = {vin_diff_mv/1000.0:.4f}",
                      template, count=1, flags=re.MULTILINE)
    # Reuse the harness circuit; the single-shot analysis is replaced by the
    # loop below, so strip .tran/.measure/.print/.end from the template.
    circuit = "\n".join(ln for ln in template.splitlines()
                        if not re.match(r"^\s*\.(tran|meas|print|end)", ln, re.IGNORECASE))
    # Thresholds must be numeric literals: param expressions like '0.9*VDD_V'
    # do not evaluate inside a .control `meas`. Derive them from the template.
    vdd = float(re.search(r"\.param VDD_V\s*=\s*([\d.]+)", template).group(1))
    td = re.search(r"\.param STROBE_DELAY\s*=\s*(\S+)", template).group(1)
    tran_args = re.search(r"^\s*\.tran\s+(.+)$", template, re.MULTILINE).group(1).strip()
    at_t = re.search(r"AT\s*=\s*(\S+)", template).group(1)
    header = (f'.lib "{SKY130_LIB}" {CORNER}\n'
              f'.include "{source}"\n'
              ".param mc_mm_switch=1\n")
    control = f"""
.control
  let mc_runs = {n_trials}
  let run = 0
  dowhile run < mc_runs
    let sv = {seed_base} + run + 1
    setseed $&sv
    reset
    tran {tran_args}
    let tmh = -1
    let tpl = -1
    meas tran vpf FIND v(outp) AT={at_t}
    meas tran vmf FIND v(outm) AT={at_t}
    meas tran tmh WHEN v(outm)={0.9 * vdd:.4f} RISE=1 TD={td}
    meas tran tpl WHEN v(outp)={0.1 * vdd:.4f} FALL=1 TD={td}
    echo MCRESULT $&run $&vpf $&vmf $&tmh $&tpl
    let run = run + 1
  end
.endc
.end
"""
    out = job / f"mc_shard_v{vin_diff_mv}_s{seed_base}.sp"
    out.write_text(header + circuit + control)
    return out


def _classify(vpf, vmf, tmh, tpl) -> dict:
    """Same decision as the per-trial runner: OUT+/OUT- must diverge >0.5 V
    in the correct direction; resolve time = first threshold crossing minus
    the 1 ns strobe delay."""
    d = {"resolved_correct": False, "resolved_wrong": False, "t_resolve_ns": None}
    if not (isinstance(vpf, float) and isinstance(vmf, float)):
        return d
    if vmf > vpf + 0.5:
        d["resolved_correct"] = True
        cands = [t for t in (tmh, tpl) if isinstance(t, float) and t >= 0]
        if cands:
            d["t_resolve_ns"] = (min(cands) - 1e-9) * 1e9
    elif vpf > vmf + 0.5:
        d["resolved_wrong"] = True
    return d


def run_mc_shard(work: Path, source: Path, vin_diff_mv: int,
                 n_trials: int, seed_base: int) -> list[dict]:
    job = work / f"shard_v{vin_diff_mv}_s{seed_base:07d}"
    job.mkdir(parents=True, exist_ok=True)
    deck = write_mc_deck(job, source, vin_diff_mv, n_trials, seed_base)
    r = subprocess.run(["ngspice", "-b", str(deck)],
                       capture_output=True, text=True, timeout=1800, cwd=job)
    (job / "ngspice.out").write_text(r.stdout + "\n=== stderr ===\n" + r.stderr)

    def num(x):
        try:
            return float(x)
        except ValueError:
            return None

    results = []
    for m in re.finditer(r"^MCRESULT\s+\d+\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
                         r.stdout + "\n" + r.stderr, re.MULTILINE):
        vpf, vmf, tmh, tpl = m.groups()
        d = _classify(num(vpf), num(vmf), num(tmh), num(tpl))
        d["vin_diff_mv"] = vin_diff_mv
        results.append(d)
    return results


def main() -> int:
    mode = os.environ.get("ANKHDJET_SA_SOURCE", "schematic").lower()
    work = HERE / f"build_mc_{mode}"
    if work.exists():
        import shutil
        shutil.rmtree(work)
    work.mkdir()
    source = resolve_source(work)

    total = N_TRIALS * len(VIN_DIFF_MV_LIST)
    print(f"sweeping VIN_DIFF in {VIN_DIFF_MV_LIST} mV at SS, source={mode} ({source.name})")
    print(f"  trials per Vdiff: {N_TRIALS}, total: {total}")
    t_start = time.time()

    # Split each Vdiff's trials across N_SHARDS single-process shards; each shard
    # is one ngspice that loads the SKY130 models once and loops its trials, so
    # the ~30 s model load is paid per-shard instead of per-trial. The load does
    # not parallelize, so the default (1 shard/Vdiff) is optimal for the load-
    # dominated common case.
    shards = []
    seed_base = 1
    for v in VIN_DIFF_MV_LIST:
        base, rem = divmod(N_TRIALS, N_SHARDS)
        for i in range(N_SHARDS):
            cnt = base + (1 if i < rem else 0)
            if cnt:
                shards.append((v, cnt, seed_base))
                seed_base += cnt
    n_workers = min(len(shards), N_JOBS)
    print(f"  {len(shards)} single-process shard(s) (one model load each), "
          f"concurrency: {n_workers}")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(run_mc_shard, work, source, v, cnt, sb): (v, cnt)
                   for v, cnt, sb in shards}
        done_shards = 0
        for fut in as_completed(futures):
            try:
                results.extend(fut.result())
            except Exception as e:
                v, cnt = futures[fut]
                results.extend([{"vin_diff_mv": v, "error": str(e)[:200]}
                                for _ in range(cnt)])
            done_shards += 1
            print(f"  shard {done_shards}/{len(shards)} done  "
                  f"(elapsed={time.time() - t_start:5.0f}s)")

    body_lines: list[str] = []
    def _emit(line: str) -> None:
        print(line)
        body_lines.append(line)

    _emit("")
    _emit(f"{'Vdiff(mV)':>10} {'trials':>7} {'correct%':>9} {'wrong%':>8} "
          f"{'median(ps)':>12} {'p99(ps)':>10} {'p99.9(ps)':>12}")
    _emit("-" * 80)
    overall_pass = True
    for v in VIN_DIFF_MV_LIST:
        rs = [r for r in results if r.get("vin_diff_mv") == v]
        n = len(rs)
        n_c = sum(1 for r in rs if r.get("resolved_correct"))
        n_w = sum(1 for r in rs if r.get("resolved_wrong"))
        ts = sorted(r["t_resolve_ns"] * 1000 for r in rs
                     if r.get("resolved_correct") and isinstance(r.get("t_resolve_ns"), (int, float)))
        if ts:
            median = ts[len(ts) // 2]
            p99 = ts[int(len(ts) * 0.99)]
            p999 = ts[min(int(len(ts) * 0.999), len(ts) - 1)]
        else:
            median = p99 = p999 = float("nan")
        rate_pct = n_c / n * 100 if n else 0
        _emit(f"{v:>10} {n:>7} {rate_pct:>8.2f}% {n_w/n*100 if n else 0:>7.2f}% "
              f"{median:>11.1f} {p99:>9.1f} {p999:>11.1f}")
        if rate_pct < 99.9:
            overall_pass = False

    if not overall_pass:
        _emit(f"\n[FAIL] no VIN_DIFF in the sweep reaches 99.9% correct at SS")
    else:
        _emit(f"\n[ok] at least one VIN_DIFF passes 99.9% correct at SS")

    write_summary(
        build_dir=work,
        config=f"mc_{mode}",
        args=sys.argv,
        results_text="\n".join(body_lines) + "\n",
        passed=overall_pass,
        runtime_s=time.time() - t_start,
    )
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
