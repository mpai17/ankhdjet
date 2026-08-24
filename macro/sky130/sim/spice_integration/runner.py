"""Orchestrate the SPICE integration test.

`run_pattern(name, W, act_seq, ...)` writes a deck, runs ngspice in
batch mode, parses the .measure outputs, and diffs vs the reference.
`main()` builds the pattern list from CLI flags and dispatches them
to a ThreadPoolExecutor.

CLI:
  uv run runner.py -N 64 -M 32 --coverage tier1 --corner tt --timeout 7200
  ANKHDJET_NGSPICE_JOBS=4 uv run runner.py ...   # override parallelism
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from check import (
    FAIL_PWL_MALFORMED, FAIL_TIMEOUT, check, parse_results,
)
from deck import emit_array_deck
from patterns import pattern_random, select_patterns
from paths import HERE, REPO

sys.path.insert(0, str(REPO))
from tools.regression_log import write_summary  # noqa: E402


def run_pattern(name: str, W: np.ndarray, act_seq: np.ndarray, corner: str,
                work: Path, timeout_s: int) -> tuple[bool, str, list[dict]]:
    """Generate the deck, run ngspice on it, parse + check the output."""
    N, M = W.shape
    deck = emit_array_deck(W, act_seq, corner=corner)
    work.mkdir(parents=True, exist_ok=True)
    deck_path = work / f"deck_{name}_{corner}.sp"
    deck_path.write_text(deck)
    log_path = work / f"log_{name}_{corner}.log"
    n_active = int(((W != 0) & act_seq[:, None].astype(bool)).sum())
    print(f"[run] {name} N={N} M={M} corner={corner} active={n_active} "
          f"deck={len(deck)//1024} KB", flush=True)
    try:
        r = subprocess.run(
            ["ngspice", "-b", "-o", str(log_path), str(deck_path)],
            capture_output=True, text=True, timeout=timeout_s, cwd=work,
        )
    except subprocess.TimeoutExpired:
        return False, f"ngspice timed out after {timeout_s}s", [
            dict(r=-1, c=-1, kind=FAIL_TIMEOUT,
                 msg=f"ngspice exceeded {timeout_s}s wall-clock budget for {name}")
        ]
    log = log_path.read_text() if log_path.exists() else (r.stdout + r.stderr)

    # Surface ngspice errors (PWL non-increasing, model not found,
    # convergence failure) BEFORE trying to parse measurements.
    pwl_warns = sum(1 for ln in log.splitlines() if "non-increasing PWL" in ln)
    if pwl_warns > 0:
        return False, f"ngspice rejected {pwl_warns} PWL waveforms (non-increasing)", [
            dict(r=-1, c=-1, kind=FAIL_PWL_MALFORMED,
                 msg=f"{pwl_warns} PWL voltage sources had non-increasing time points "
                     f"-- floating-point representation bug in deck emitter")
        ]

    results = parse_results(log, N, M)
    fails = check(W, act_seq, results)
    if fails:
        kinds: dict[str, int] = {}
        for f in fails:
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
        kinds_str = ", ".join(f"{k}={v}" for k, v in sorted(kinds.items()))
        msg = f"{len(fails)} cell failures ({kinds_str}); first 5:\n" + \
              "\n".join("  " + f["msg"] for f in fails[:5])
        return False, msg, fails
    return True, f"all {N*M} cells PASS (active={n_active})", []


def run(N: int, M: int, seed: int, corner: str, work: Path,
        timeout_s: int) -> tuple[bool, str]:
    """Single-pattern compatibility entry-point (used by quick smoke runs)."""
    W, act = pattern_random(N, M, seed)
    ok, msg, _ = run_pattern(f"random_seed{seed}", W, act, corner, work, timeout_s)
    return ok, msg


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("-N", type=int, default=8)
    p.add_argument("-M", type=int, default=4)
    p.add_argument("--corner", default="tt", choices=["tt", "ss", "ff"])
    p.add_argument("--timeout", type=int, default=3600,
                   help="per-pattern ngspice subprocess timeout (seconds)")
    p.add_argument("--coverage", default="tier1+random",
                   choices=["tier1", "random", "tier1+random",
                            "tier1+random+exhaustive", "smoke"],
                   help="which patterns to run")
    p.add_argument("--n-random", type=int, default=3,
                   help="number of random-seed patterns under tier 2")
    args = p.parse_args()

    work = HERE / f"build_array_{args.N}x{args.M}"
    work.mkdir(parents=True, exist_ok=True)

    patterns = select_patterns(args.N, args.M, args.coverage, n_random=args.n_random)

    n_jobs = int(os.environ.get(
        "ANKHDJET_NGSPICE_JOBS",
        str(min(len(patterns), max(1, (os.cpu_count() or 4) - 2))),
    ))
    header = (f"running {len(patterns)} patterns at {args.corner} corner "
              f"on {args.N}x{args.M} array, jobs={n_jobs}")
    print(header)
    body_lines = [header]
    t0 = time.monotonic()

    n_pass = 0
    n_fail = 0
    fail_cells: list[dict] = []

    def _record(name: str, ok: bool, msg: str) -> None:
        line = ("  [ok] " if ok else "  [FAIL] ") + name + ": " + msg
        print(line, flush=True)
        body_lines.append(line)

    if n_jobs == 1:
        for name, W, act in patterns:
            ok, msg, fs = run_pattern(name, W, act, args.corner, work, args.timeout)
            _record(name, ok, msg)
            if ok:
                n_pass += 1
            else:
                n_fail += 1
                fail_cells.extend(fs)
    else:
        # ngspice itself is single-threaded but per-pattern decks are
        # independent; ThreadPoolExecutor fans them out to (CPU - 2)
        # concurrent ngspice processes.
        with ThreadPoolExecutor(max_workers=n_jobs) as pool:
            futs = {pool.submit(run_pattern, name, W, act, args.corner, work,
                                args.timeout): name
                    for (name, W, act) in patterns}
            for f in as_completed(futs):
                name = futs[f]
                ok, msg, fs = f.result()
                _record(name, ok, msg)
                if ok:
                    n_pass += 1
                else:
                    n_fail += 1
                    fail_cells.extend(fs)

    summary_line = f"\nsummary: {n_pass}/{len(patterns)} patterns pass"
    print(summary_line)
    body_lines.append(summary_line)
    if fail_cells:
        kinds: dict[str, int] = {}
        for f in fail_cells:
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
        print("failure-mode taxonomy:")
        body_lines.append("failure-mode taxonomy:")
        for k, v in sorted(kinds.items()):
            tax_line = f"  {k:25s} {v}"
            print(tax_line)
            body_lines.append(tax_line)

    config = f"{args.N}x{args.M}_{args.corner}_{args.coverage.replace('+', '-')}"
    write_summary(
        build_dir=work,
        config=config,
        args=sys.argv,
        results_text="\n".join(body_lines) + "\n",
        passed=(n_fail == 0),
        runtime_s=time.monotonic() - t0,
    )
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
