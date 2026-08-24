"""A2 extracted-macro read validation: drives the C-extracted macro
(real bitline + coupling caps) with the validated sa_se schematic pair
at FSM timing, across corners and a swept lumped ground-return
resistance. Writes a timestamped result log under build/."""
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

tmpl = (HERE / "a2_read.sp.tmpl").read_text()
chunks = [conn[i:i+16] for i in range(0, len(conn), 16)]
inst = "Xmacro " + " ".join(chunks[0]) + "\n" + \
       "\n".join("+ " + " ".join(ch) for ch in chunks[1:]) + \
       f"\n+ {hdr[0].split()[1]}"
tmpl = tmpl.replace("Xmacro vpwr vgnd_m PRE_N_NETLIST", inst)
tmpl = tmpl.replace("LIBPATH", str(LIB))

CASES = [("tt", 27, 1.8, r) for r in (0.001, 500, 2000, 10000)] + \
        [("ss", 100, 1.62, r) for r in (0.001, 500, 2000, 10000)]

def run(case):
    corner, temp, vdd, rgnd = case
    tag = f"{corner}_{int(rgnd)}"
    deck = tmpl.replace("CORNER", corner).replace("TEMPC", str(temp)) \
               .replace("VDDV", str(vdd)).replace("RGNDV", str(rgnd))
    p = BUILD / f"a2_{tag}.sp"
    p.write_text(deck)
    r = subprocess.run(["ngspice", "-b", str(p)], capture_output=True, text=True, timeout=1800)
    meas = dict(re.findall(r"^(\w+)\s*=\s*([-\d.eE+]+)", r.stdout, re.M))
    return tag, meas, r.returncode

stamp = time.strftime("%Y%m%d_%H%M%S")
log = BUILD / f"a2_results_{stamp}.log"
rows = []
with ThreadPoolExecutor(max_workers=8) as ex:
    for tag, meas, rc in ex.map(run, CASES):
        rows.append((tag, meas, rc))

ok = True
with open(log, "w") as f:
    f.write("# A2 extracted-macro read validation\n")
    f.write(f"# netlist: {NETLIST}\n")
    hdrline = f"{'case':>10} {'blp@strobe':>11} {'bln_preStr':>11} {'bln_kick':>9} {'hitP':>6} {'hitN':>6} {'blp@80n':>9} {'r2 bln':>8} {'r2 hitN':>8} {'r2 hitP':>8}"
    print(hdrline); f.write(hdrline + "\n")
    for tag, m, rc in rows:
        g = lambda k: float(m.get(k, float("nan")))
        rec80 = g("blp80"); rec85 = g("blp85")
        line = (f"{tag:>10} {g('blp_at_strobe'):11.3f} {g('bln_min'):11.3f} "
                f"{g('bln_post_kick'):9.3f} {g('hitp_read1'):6.2f} {g('hitn_read1'):6.2f} "
                f"{rec80:9.3f} {g('bln_at_strobe2'):8.3f} {g('hitn_read2'):8.2f} {g('hitp_read2'):8.2f}")
        print(line); f.write(line + "\n")
        vdd = 1.62 if tag.startswith("ss") else 1.8
        # bln_min = the floating victim's pre-strobe level (coupling dip
        # included); the post-strobe level reflects SA kickback, which
        # lands after the decision and is reported, not checked.
        checks = [g("blp_at_strobe") < 0.25,
                  g("bln_min") > vdd/2 + 0.25,
                  g("hitp_read1") > 0.8*vdd, g("hitn_read1") < 0.2*vdd,
                  rec85 > 0.95*vdd,
                  g("bln_at_strobe2") < 0.25,
                  g("hitn_read2") > 0.8*vdd, g("hitp_read2") < 0.2*vdd]
        if not all(checks):
            ok = False
            msg = f"FAIL {tag}: checks={checks}"
            print(msg); f.write(msg + "\n")
    verdict = "PASS: all cases" if ok else "FAIL: see above"
    print(verdict); f.write(verdict + "\n")
print(f"result log: {log}")
sys.exit(0 if ok else 1)
