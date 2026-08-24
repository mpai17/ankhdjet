"""Persist regression results to a timestamped on-disk log.

`write_summary(build_dir, config, args, results_text, passed, runtime_s)`
creates `build_dir/summary_<config>_<UTCstamp>.log` with a header
recording timestamp, git rev, command, verdict, and runtime, followed
by the `results_text` body. Every regression entry-point in the
project should call this so direct CLI runs (outside
`tools/run_tests.sh`) leave a debuggable trail.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        return "unknown"


def write_summary(build_dir: Path, config: str, args: list[str],
                  results_text: str, passed: bool,
                  runtime_s: float | None = None) -> Path:
    """Write a regression summary log and return its path."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    path = build_dir / f"summary_{config}_{ts}.log"
    header_lines = [
        "# regression result log",
        f"# timestamp_utc: {ts}",
        f"# git_rev:       {_git_rev()}",
        f"# config:        {config}",
        f"# command:       {' '.join(args)}",
        f"# verdict:       {'PASS' if passed else 'FAIL'}",
    ]
    if runtime_s is not None:
        header_lines.append(f"# runtime_s:     {runtime_s:.1f}")
    header = "\n".join(header_lines) + "\n\n"
    path.write_text(header + results_text)
    print(f"[log] wrote {path}", flush=True)
    return path
