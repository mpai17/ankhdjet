"""VREF validation per docs/vref_design.md: the C-extracted macro with
ALL 64 sa_se comparators strobing synchronously against the on-chip
divider (2x180k res_xhigh_po as ideal R with +/-30% sheet corners) +
150 pF split decap. Measures the kickback dip on vref, the startup
ramp, and every read verdict. Writes a timestamped result log."""
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
BUILD.mkdir(exist_ok=True)
REPO = HERE.parents[3]
NETLIST = REPO / "cell/sky130/macro/build/macro_cap.spice"
SENSE = REPO / "cell/sky130/sense_se/sense_col_schematic.spice"
LIB = next(Path.home().glob(".ciel/**/sky130A/libs.tech/ngspice/sky130.lib.spice"))

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
    elif p == "WL_0": conn.append("wl0")
    elif p.startswith("WL_"): conn.append("0")
    else: conn.append(p.lower())          # all 64 bitlines sensed
chunks = [conn[i:i+16] for i in range(0, len(conn), 16)]
inst = "Xmacro " + " ".join(chunks[0]) + "\n" + \
       "\n".join("+ " + " ".join(c) for c in chunks[1:]) + f"\n+ {hdr[0].split()[1]}"

sas = []
for c in range(32):
    sas.append(f"Xsap{c} blp_{c} vref hp_{c} hbp_{c} strobe vpwr 0 sa_se")
    sas.append(f"Xsan{c} bln_{c} vref hn_{c} hbn_{c} strobe vpwr 0 sa_se")
SAS = "\n".join(sas)

DECK = """* VREF divider + decap vs 64-comparator synchronous strobe (fine window;
* vref pre-set to its settled value -- the slow ramp is the second deck)
.lib {lib} {corner}
.temp {temp}
.param vdd={vdd}
.include {netlist}
.include {sense}
.ic v(vref)={{vdd/2}}

Vdd vpwr 0 dc {{vdd}}
Rgnd vgnd_m 0 0.001

R1 vpwr vref {r1}
R2 vref 0 {r2}
C1 vpwr vref 75p
C2 vref 0 75p

Vpre pre_n 0 pwl(0 0 25n 0 25.2n {{vdd}} 200n {{vdd}})
Vwl0 wl0 0 pwl(0 0 26n 0 26.2n {{vdd}} 200n {{vdd}})
Vstr strobe 0 pwl(0 0 50n 0 50.2n {{vdd}} 75n {{vdd}} 75.2n 0 200n 0)

{inst}
{sas}

.tran 0.05n 120n
.control
run
meas tran vref_pre  find v(vref) at=49.9n
meas tran vref_min  min v(vref) from=50n to=75n
meas tran vref_post find v(vref) at=110n
meas tran hp0 find v(hp_0) at=74n
meas tran hn0 find v(hn_0) at=74n
meas tran hp1 find v(hp_1) at=74n
meas tran hn1 find v(hn_1) at=74n
quit
.endc
.end
"""

RAMP = """* VREF startup ramp: divider + decap + 8.6 pF gate load, coarse step
.lib {lib} {corner}
.temp {temp}
.param vdd={vdd}
Vdd vpwr 0 dc {{vdd}}
R1 vpwr vref {r1}
R2 vref 0 {r2}
C1 vpwr vref 75p
C2 vref 0 75p
Cload vref 0 8.6p
.tran 50n 120u uic
.control
run
meas tran v75 find v(vref) at=75u
meas tran v120 find v(vref) at=120u
quit
.endc
.end
"""

CASES = [("tt", 27, 1.8, 1.0), ("ss", 100, 1.62, 1.3), ("ff", -40, 1.95, 0.7)]

def run(case):
    corner, temp, vdd, rk = case
    tag = f"{corner}_r{rk}"
    deck = DECK.format(lib=LIB, corner=corner, temp=temp, vdd=vdd,
                       r1=int(180e3*rk), r2=int(180e3*rk),
                       netlist=NETLIST, sense=SENSE, inst=inst, sas=SAS)
    p = BUILD / f"vref_{tag}.sp"
    p.write_text(deck)
    r = subprocess.run(["ngspice", "-b", str(p)], capture_output=True, text=True, timeout=3600)
    meas = dict(re.findall(r"^(\w+)\s*=\s*([-\d.eE+]+)", r.stdout, re.M))
    ramp = RAMP.format(lib=LIB, corner=corner, temp=temp, vdd=vdd,
                       r1=int(180e3*rk), r2=int(180e3*rk))
    p2 = BUILD / f"ramp_{tag}.sp"
    p2.write_text(ramp)
    r2 = subprocess.run(["ngspice", "-b", str(p2)], capture_output=True, text=True, timeout=600)
    meas.update({"ramp_"+k: v for k, v in
                 re.findall(r"^(\w+)\s*=\s*([-\d.eE+]+)", r2.stdout, re.M)})
    return tag, meas

stamp = time.strftime("%Y%m%d_%H%M%S")
log = BUILD / f"vref_results_{stamp}.log"
ok = True
with open(log, "w") as f, ThreadPoolExecutor(max_workers=3) as ex:
    h = f"{'case':>10} {'ramp@75u':>11} {'pre':>7} {'min(dip)':>9} {'post':>7} {'hp0':>6} {'hn0':>6}"
    print(h); f.write(h + "\n")
    for tag, m in ex.map(run, CASES):
        g = lambda k: float(m.get(k, float("nan")))
        vdd = {"tt":1.8,"ss":1.62,"ff":1.95}[tag.split("_")[0]]
        dip = g("vref_pre") - g("vref_min")
        line = (f"{tag:>10} {g('ramp_v75'):11.4f} {g('vref_pre'):7.4f} "
                f"{g('vref_min'):9.4f} {g('vref_post'):7.4f} {g('hp0'):6.2f} {g('hn0'):6.2f}")
        print(line, f"  dip={dip*1000:.1f}mV"); f.write(line + f"  dip={dip*1000:.1f}mV\n")
        checks = [abs(g("ramp_v75") - vdd/2) < 0.05,
                  dip < 0.035,
                  g("hp0") > 0.8*vdd, g("hn0") < 0.2*vdd]
        if not all(checks):
            ok = False
            msg = f"FAIL {tag}: {checks}"
            print(msg); f.write(msg + "\n")
    v = "PASS: divider+decap holds VREF through the 64-SA strobe" if ok else "FAIL"
    print(v); f.write(v + "\n")
print(f"result log: {log}")
