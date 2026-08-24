"""Small helper to build and run a Verilator binary for a given testbench.

Common pattern in our tests:
    1. Write generated RTL files and stim data into a temporary work dir
    2. Call verilator to build a self-contained binary
    3. Run the binary, capture stdout
    4. Parse output strings printed by $display

Build is configured for maximum runtime throughput so larger pipeline
tests (full BitNet layers, tile-grain validations of compiled real
weights) stay tractable. The optimization stack:

  Verilator side:
    -O3                    aggressive Verilator IR optimization
    --x-assign fast        skip 4-state X tracking
    --x-initial fast       skip 4-state X init
    --noassert             drop $assert / $cover at sim time
    --unroll-count 1024    inline larger generate / for-loops
    --unroll-stmts 100000  raise the per-loop body cost cap
    --inline-mult 10000    aggressively inline submodule instances
                           (cirom_tile generates many per layer)

  C++ compile side (-CFLAGS / -LDFLAGS):
    -O3                    full GCC optimization
    -march=native          Zen 3 vectorization (AVX2/BMI2/SHA-NI)
    -fno-stack-protector   skip canary checks; we trust our own RTL
    -DNDEBUG               drop assert.h asserts
    -flto                  link-time inlining across translation units

  Build parallelism:
    --build-jobs N         parallel C++ compile (defaults to host cores)

Compile time grows by ~30-60% vs -O0 default, simulation runtime drops
by 3-8x on tile-heavy designs - the right tradeoff for any test where
sim wall-clock dominates compile.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _build_jobs() -> int:
    return max(1, (os.cpu_count() or 4) - 1)


DEFAULT_VERILATOR_FLAGS = (
    "--binary",           # produce a standalone executable
    "--timing",           # support `#delay` / `always #5 clk`
    "-sv",                # SystemVerilog
    "-O3",
    "-CFLAGS", "-O3 -march=native -fno-stack-protector -DNDEBUG",
    "-LDFLAGS", "-flto",
    "--x-assign", "fast",
    "--x-initial", "fast",
    "--noassert",
    "--unroll-count", "1024",
    "--unroll-stmts", "100000",
    "--inline-mult", "10000",
    "-Wno-fatal",
    "-Wno-WIDTHEXPAND",
    "-Wno-WIDTHTRUNC",
    "-Wno-TIMESCALEMOD",
    "-Wno-UNUSEDSIGNAL",
    "-Wno-UNUSEDPARAM",
)


def build_and_run(
    workdir: Path,
    sources: list[Path | str],
    top: str,
    include_dirs: list[Path | str] | None = None,
    build_timeout: float = 600.0,
    run_timeout: float = 600.0,
    sim_threads: int = 1,
) -> str:
    """Build `sources` with Verilator and run the resulting binary.

    Returns the captured stdout string. Raises RuntimeError on either the
    verilator invocation or the simulation returning nonzero.

    `sim_threads` controls Verilator's runtime model partitioning:
      1     single-threaded (best for small testbenches; threading
            overhead dominates below ~50K gates)
      >1    enable --threads N for large flat designs (e.g. compiling
            a full BitNet layer); only beneficial when the model has
            enough parallelism to outweigh sync overhead

    `build_timeout` defaults to 10 min to accommodate -flto + -O3 on
    larger pipelines; small testbenches still build in seconds.
    """
    obj_dir = workdir / "obj_dir"
    if obj_dir.exists():
        shutil.rmtree(obj_dir)

    flags = list(DEFAULT_VERILATOR_FLAGS)
    flags += ["--build-jobs", str(_build_jobs())]
    if sim_threads > 1:
        flags += ["--threads", str(sim_threads)]

    cmd = ["verilator", *flags, "--top-module", top]
    for inc in include_dirs or []:
        cmd.append(f"-I{inc}")
    cmd.extend(str(s) for s in sources)

    r = subprocess.run(
        cmd, cwd=workdir,
        capture_output=True, text=True, timeout=build_timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"verilator failed:\n--- cmd ---\n{' '.join(cmd)}\n"
            f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
        )

    exe = obj_dir / f"V{top}"
    r = subprocess.run(
        [str(exe)], cwd=workdir,
        capture_output=True, text=True, timeout=run_timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"sim failed (rc={r.returncode}):\n"
            f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
        )
    return r.stdout
