"""Ordered fan-out over a process pool for the per-layer emitters.

Chunk emission is CPU-bound pure Python, so the layer fan-out uses
processes. Results return in submission order regardless of completion
order, keeping manifests and filelists byte-deterministic; progress
fires per completion (so labels arrive in completion order under a
pool). jobs=1, or a single call, runs serially in-process.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed


def run_ordered(calls, jobs=None, progress=None, stage=""):
    """Run [(label, fn, args, kwargs), ...] and return the results in
    input order. fn/args/kwargs must be picklable; a worker exception
    propagates to the caller. progress(stage, done, total, label) is
    called after each completion."""
    total = len(calls)
    results = [None] * total
    if total == 0:
        return results
    if jobs == 1 or total == 1:
        for i, (label, fn, args, kwargs) in enumerate(calls):
            results[i] = fn(*args, **kwargs)
            if progress is not None:
                progress(stage, i + 1, total, label)
        return results
    done = 0
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(fn, *args, **kwargs): (i, label)
                for i, (label, fn, args, kwargs) in enumerate(calls)}
        for fut in as_completed(futs):
            i, label = futs[fut]
            results[i] = fut.result()
            done += 1
            if progress is not None:
                progress(stage, done, total, label)
    return results
