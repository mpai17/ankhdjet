"""A2 energy sweep: per-read supply energy and idle leakage on the
C-extracted macro with the sa_se pair, at FSM timing, across corners.

Charge-based energy is the well-conditioned quantity for a C-only
extraction (dynamic energy is sum C*V^2), unlike delay. Each corner row
is gated on the deck's functional sanity measures (both reads must
decide correctly) before its energy is reported. Writes a timestamped
result log under build/ with the per-phase table and the tile/chip
scaling arithmetic stated explicitly.
"""
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
BUILD.mkdir(exist_ok=True)
REPO = HERE.parent.parent.parent.parent
NETLIST = REPO / "cell/sky130/macro/build/macro_cap.spice"
LIB = next(Path.home().glob(".ciel/**/sky130A/libs.tech/ngspice/sky130.lib.spice"))

# macro port list (from the .subckt header, continuation-aware)
hdr, collect = [], False
for ln in NETLIST.read_text().splitlines():
    if ln.lower().startswith(".subckt"):
        collect = True; hdr.append(ln); continue
    if collect:
        if ln.startswith("+"): hdr.append(ln)
        else: break
ports = " ".join(h.lstrip("+") for h in hdr).split()[2:]

conn = []
for p in ports:
    if p == "VPWR": conn.append("vpwr")
    elif p == "VGND": conn.append("vgnd_m")
    elif p == "PRE_N": conn.append("pre_n")
    elif p == "BLP_0": conn.append("blp_0")
    elif p == "BLN_0": conn.append("bln_0")
    elif p == "WL_0": conn.append("wl0")
    elif p == "WL_1": conn.append("wl1")
    elif p.startswith("WL_"): conn.append("0")          # unselected rows held low
    else: conn.append(f"fl_{p.lower()}")                 # other bitlines float

tmpl = (HERE / "a2_energy.sp.tmpl").read_text()
chunks = [conn[i:i+16] for i in range(0, len(conn), 16)]
inst = "Xmacro " + " ".join(chunks[0]) + "\n" + \
       "\n".join("+ " + " ".join(ch) for ch in chunks[1:]) + \
       f"\n+ {hdr[0].split()[1]}"
tmpl = tmpl.replace("Xmacro vpwr vgnd_m PRE_N_NETLIST", inst)
tmpl = tmpl.replace("LIBPATH", str(LIB))

# (corner, tempC, vdd, rgnd): tt nominal, ss slow-low-V, ff hot-fast-high-V
# (the leakage-worst corner from the deferred-gaps list). RGND fixed at the
# bounded 500 ohm ground return; one near-zero control on tt.
CASES = [("tt", 27, 1.8, 500), ("ss", 100, 1.62, 500),
         ("ff", 125, 1.98, 500), ("tt", 27, 1.8, 0.001)]


def run(case):
    corner, temp, vdd, rgnd = case
    tag = f"{corner}_{temp}C_{vdd}V_r{int(rgnd)}"
    deck = tmpl.replace("CORNER", corner).replace("TEMPC", str(temp)) \
               .replace("VDDV", str(vdd)).replace("RGNDV", str(rgnd))
    p = BUILD / f"energy_{tag}.sp"
    p.write_text(deck)
    t0 = time.time()
    r = subprocess.run(["ngspice", "-b", str(p)], capture_output=True,
                       text=True, timeout=3600)
    meas = {k.lower(): float(v) for k, v in
            re.findall(r"^(\w+)\s*=\s*([-\d.eE+]+)", r.stdout, re.M)}
    return case, tag, meas, time.time() - t0, r.returncode


def sane(m, vdd):
    hi, lo = 0.9 * vdd, 0.1 * vdd
    try:
        return (m["hitp_read1"] > hi and m["hitn_read1"] < lo and
                m["hitn_read2"] > hi and m["hitp_read2"] < lo)
    except KeyError:
        return False


def main():
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    log = BUILD / f"energy_{stamp}.log"
    lines = [
        "A2 per-read energy sweep (C-extracted macro + sa_se pair, FSM timing)",
        f"netlist: {NETLIST}",
        "E = vdd * |q|. Deck: full 64x32 macro (all 32 columns precharge and",
        "discharge per mask) + ONE sa_se pair on column 0.",
        "Scaling: E_tile_read = E_macro + 16 * E_sa_pair (TT: 16 sensed cols);",
        "         E_chip_read = E_macro + 32 * E_sa_pair (chip: full sense).",
        "Per-sensed-weight = E_tile_read / 16.  Cycle = 125 ns (5 FSM states).",
        "", ]
    hdr_row = (f"{'corner':>16} {'ok':>3} {'E_macro/read pJ':>16} "
               f"{'E_sa_pair pJ':>13} {'E_tile pJ':>10} {'pJ/weight':>10} "
               f"{'Q_vref pC':>10} {'P_leak uW':>10}")
    lines.append(hdr_row)
    rows = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for case, tag, m, dt, rc in ex.map(run, CASES):
            corner, temp, vdd, rgnd = case
            ok = sane(m, vdd)
            try:
                e_m = vdd * abs((m["q_m_c1"] + m["q_m_c2"]) / 2) * 1e12
                e_sa = vdd * abs((m["q_sa_c1"] + m["q_sa_c2"]) / 2) * 1e12
                e_tile = e_m + 16 * e_sa
                q_vr = abs((m["qvr_125"] + (m["qvr_250"] - m["qvr_125"])) / 2) * 1e12
                p_lk = vdd * (abs(m["i_lk_m"]) + abs(m["i_lk_sa"])) * 1e6
                row = (f"{tag:>16} {('Y' if ok else 'N'):>3} {e_m:16.2f} "
                       f"{e_sa:13.2f} {e_tile:10.2f} {e_tile/16:10.2f} "
                       f"{q_vr:10.3f} {p_lk:10.3f}")
            except KeyError as e:
                ok = False
                row = f"{tag:>16}   N   missing measure {e} (rc={rc})"
            rows.append((tag, ok))
            lines.append(row)
            phases = " ".join(f"{k}={vdd*abs(m[k])*1e12:.2f}pJ"
                              for k in ("q_m_t0", "q_m_t1", "q_m_t2", "q_m_t3")
                              if k in m)
            lines.append(f"{'':>20} phases: {phases}  ({dt:.0f}s)")
    verdict = "PASS" if all(ok for _, ok in rows) else "FAIL"
    lines.append("")
    lines.append(f"RESULT: {verdict} ({sum(ok for _, ok in rows)}/{len(rows)} "
                 f"rows valid; ok=Y requires correct read decisions and all measures)")
    log.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"logged -> {log}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
