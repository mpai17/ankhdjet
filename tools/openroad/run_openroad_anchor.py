"""Multi-platform OpenROAD CTS+STA anchor for the throughput calibration.

Sweeps benchmark designs at each open PDK platform that ships in the
ORFS Docker image (sky130hd 130 nm, gf180 180 nm, asap7 7 nm). Each
(area, achieved_fmax) tuple is appended to silicon_tapeouts.yaml as an
OpenROAD-grade anchor at the corresponding process_nm.

Skips ORFS's post-CTS detailed_placement (SIGILL on AMD Zen 3) by
running ORFS make through 3_5_place_dp.odb only, then driving our own
minimal CTS+STA Tcl on the placed .odb.

Usage:
    uv run tools/openroad/run_openroad_anchor.py
    uv run tools/openroad/run_openroad_anchor.py --platforms sky130hd
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOCKER_IMG = "openroad/orfs:latest"
TCL_HOST = REPO / "tools" / "openroad" / "run_cts_sta.tcl"
PLATFORM_DIR = "/OpenROAD-flow-scripts/flow/platforms"

# Persistent host-side cache for the ORFS results tree. Mounting this into
# the container at /OpenROAD-flow-scripts/flow/results lets `make` skip
# already-built stages across container invocations - re-running the sweep
# after a small Tcl edit only redoes CTS+STA, not synth+floorplan+place.
ORFS_CACHE = REPO / "build" / "orfs_cache"

# Per-platform liberty + designs + time-unit conversion. For each platform
# the libs are listed in the order ORFS reads them (so multi-liberty
# platforms get all groups loaded).
PLATFORMS = {
    "sky130hd": {
        "process_nm": 130,
        "libs_glob": [f"{PLATFORM_DIR}/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"],
        "designs": ["gcd", "aes", "ibex", "jpeg", "microwatt"],
        "ps_to_ns": 1.0,  # SKY130 lib declares time_unit "1ns"
        "cts_buf_list": "",  # let OpenROAD auto-pick
    },
    "gf180": {
        "process_nm": 180,
        "libs_glob": [f"{PLATFORM_DIR}/gf180/lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_5v00.lib.gz"],
        "designs": ["aes", "ibex", "jpeg", "riscv32i"],
        "ps_to_ns": 1.0,
        "cts_buf_list": "",
    },
    "asap7": {
        "process_nm": 7,
        "libs_glob": [
            f"{PLATFORM_DIR}/asap7/lib/NLDM/asap7sc7p5t_AO_RVT_TT_nldm_211120.lib.gz",
            f"{PLATFORM_DIR}/asap7/lib/NLDM/asap7sc7p5t_INVBUF_RVT_TT_nldm_220122.lib.gz",
            f"{PLATFORM_DIR}/asap7/lib/NLDM/asap7sc7p5t_OA_RVT_TT_nldm_211120.lib.gz",
            f"{PLATFORM_DIR}/asap7/lib/NLDM/asap7sc7p5t_SEQ_RVT_TT_nldm_220123.lib",
            f"{PLATFORM_DIR}/asap7/lib/NLDM/asap7sc7p5t_SIMPLE_RVT_TT_nldm_211120.lib.gz",
        ],
        "designs": ["gcd", "aes", "ibex", "ethmac"],
        "ps_to_ns": 0.001,  # ASAP7 lib declares time_unit "1ps"
        "cts_buf_list": "BUFx2_ASAP7_75t_R BUFx4_ASAP7_75t_R BUFx12_ASAP7_75t_R",
    },
}


def run_design(platform: str, design: str) -> dict:
    cfg = PLATFORMS[platform]
    workdir_in = "/work"
    out_in = f"{workdir_in}/out_{platform}_{design}"
    placed_odb = f"results/{platform}/{design}/base/3_5_place_dp.odb"
    floorplan_sdc = f"results/{platform}/{design}/base/2_floorplan.sdc"
    libs_str = " ".join(cfg["libs_glob"])

    inner = f"""
set -e
cd /OpenROAD-flow-scripts/flow
make -j1 DESIGN_CONFIG=./designs/{platform}/{design}/config.mk \\
        results/{platform}/{design}/base/3_5_place_dp.odb >/work/make_{platform}_{design}.log 2>&1
mkdir -p {out_in}
cp {workdir_in}/run_cts_sta.tcl /tmp/run_cts_sta.tcl
ANKHDJET_PLACED_ODB={placed_odb} \\
ANKHDJET_SDC={floorplan_sdc} \\
ANKHDJET_LIBS="{libs_str}" \\
ANKHDJET_OUT_DIR={out_in} \\
ANKHDJET_PS_TO_NS={cfg["ps_to_ns"]} \\
ANKHDJET_CTS_BUF_LIST="{cfg["cts_buf_list"]}" \\
/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad -no_init -exit \\
    /tmp/run_cts_sta.tcl > {out_in}/openroad.log 2>&1
"""
    work_host = REPO / "build" / "openroad_anchor"
    work_host.mkdir(parents=True, exist_ok=True)
    (work_host / "run_cts_sta.tcl").write_text(TCL_HOST.read_text())
    ORFS_CACHE.mkdir(parents=True, exist_ok=True)

    # Each design runs in its own container but shares the host-side
    # results/ + logs/ directories so make can incremental-rebuild across
    # invocations. Different (platform, design) pairs write to disjoint
    # subdirectories so concurrent containers don't collide.
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{work_host}:{workdir_in}",
        "-v", f"{ORFS_CACHE}/results:/OpenROAD-flow-scripts/flow/results",
        "-v", f"{ORFS_CACHE}/logs:/OpenROAD-flow-scripts/flow/logs",
        "-v", f"{ORFS_CACHE}/reports:/OpenROAD-flow-scripts/flow/reports",
        DOCKER_IMG,
        "bash", "-c", inner,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    out_dir = work_host / f"out_{platform}_{design}"

    parsed: dict[str, float | str] = {"platform": platform, "design": design}
    if r.returncode != 0:
        log = out_dir / "openroad.log"
        tail = log.read_text()[-1500:] if log.exists() else (r.stdout + r.stderr)[-1500:]
        parsed["error"] = tail
        return parsed

    timing = (out_dir / "timing.txt").read_text() if (out_dir / "timing.txt").exists() else ""
    area_txt = (out_dir / "area.txt").read_text() if (out_dir / "area.txt").exists() else ""
    for txt in (timing, area_txt):
        for line in txt.strip().splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                try:
                    parsed[parts[0]] = float(parts[1])
                except ValueError:
                    parsed[parts[0]] = parts[1]
    return parsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platforms", default="sky130hd,gf180,asap7",
                    help="comma-separated subset of " + ",".join(PLATFORMS))
    ap.add_argument("--jobs", type=int, default=8,
                    help="max concurrent design containers (Docker will "
                         "schedule them; tune to host core count)")
    args = ap.parse_args()
    selected = [p.strip() for p in args.platforms.split(",") if p.strip()]
    for p in selected:
        if p not in PLATFORMS:
            print(f"unknown platform: {p}", file=sys.stderr)
            return 2

    # Build the full (platform, design) work list across all selected
    # platforms and run them concurrently - they share zero state so
    # parallelism is bounded only by host CPU and Docker resource limits.
    work_items: list[tuple[str, str]] = [
        (p, d) for p in selected for d in PLATFORMS[p]["designs"]
    ]
    print(f"Running {len(work_items)} design flows across "
          f"{len(selected)} platforms with up to {args.jobs} concurrent "
          f"containers (cache: {ORFS_CACHE.relative_to(REPO)})")

    all_results: dict[str, list[dict]] = {p: [] for p in selected}
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        future_to_key = {
            pool.submit(run_design, p, d): (p, d) for p, d in work_items
        }
        for fut in as_completed(future_to_key):
            p, d = future_to_key[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"platform": p, "design": d, "error": str(e)[:1500]}
            if "error" in r:
                print(f"[FAIL] {p}/{d}: {str(r['error'])[-200:]}")
            else:
                print(f"[ok]   {p}/{d}: area={r.get('die_area_mm2', '?')} "
                      f"mm^2  achieved={r.get('achieved_fmax_mhz', '?')} MHz")
            all_results[p].append(r)

    for p in selected:
        out_path = REPO / "pdk" / "calibration_data" / f"openroad_{p}.json"
        out_path.write_text(json.dumps(all_results[p], indent=2))
        print(f"Wrote {out_path.relative_to(REPO)}")

    # Append the successful runs to silicon_tapeouts.yaml as anchors.
    silicon = REPO / "pdk" / "calibration_data" / "silicon_tapeouts.yaml"
    # First strip any prior auto-appended block so we don't duplicate.
    text = silicon.read_text()
    marker = "\n# === Appended by tools/openroad/run_openroad_anchor.py ==="
    if marker in text:
        text = text[: text.index(marker)]
        silicon.write_text(text)

    appended_lines: list[str] = []
    appended_count = 0
    for p, results in all_results.items():
        process_nm = PLATFORMS[p]["process_nm"]
        for r in results:
            if "achieved_fmax_mhz" not in r or "die_area_mm2" not in r:
                continue
            fmax = float(r["achieved_fmax_mhz"])
            area = float(r["die_area_mm2"])
            if fmax <= 0 or area <= 0:
                continue
            appended_lines += [
                f"\n- name: \"ORFS {p} {r['design']} (CTS+STA via run_cts_sta.tcl)\"",
                f"  process_nm: {process_nm}",
                f"  area_mm2: {area:.4f}",
                f"  achieved_fmax_mhz: {fmax:.0f}",
                f"  source: \"openroad-flow-scripts {p}/{r['design']} placed via make + custom CTS+STA Tcl; signoff_not_silicon\"",
            ]
            appended_count += 1
    if appended_lines:
        with silicon.open("a") as f:
            f.write("\n# === Appended by tools/openroad/run_openroad_anchor.py ===")
            f.write("\n".join(appended_lines) + "\n")
        print(f"\nAppended {appended_count} OpenROAD anchors to {silicon.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
