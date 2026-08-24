#!/usr/bin/env python3
"""Mixed-signal confirm for the REBUILT (signoff-arch, no-mux) controller:
drives the RC-extracted array + sense amps with the new controller's ACTUAL
PRE_N/WL/STROBE waveform, at ff/125 with the real (divider+decap) VREF -- the
tightest case from the earlier sweep. Confirms the rebuilt controller's timing
still resolves the +1 read correctly with healthy margin (re-measuring the
sense path on the actual design rather than assuming it transfers).

Sense path is cell -> SA directly (no mux), which IS the signoff architecture.
Run from the repo root.
"""
import os, re, subprocess, sys, time

ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
BUILD = os.path.join(ROOT, "rtl", "tt", "sim", "build")
RC    = os.path.join(ROOT, "cell", "sky130", "macro", "build", "macro_rc_clean.spice")
SA    = os.path.join(ROOT, "cell", "sky130", "sense_se", "sense_col_schematic.spice")
VDD   = 1.8
os.makedirs(BUILD, exist_ok=True)

def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)

def lib_path(corner):
    base = "/home/mohnishp/.ciel/sky130A/libs.tech/ngspice/sky130.lib.spice"
    return f".lib {base} {corner}"

def gen_vcd(tclk=15.0, cfgval=17):
    vvp = os.path.join(BUILD, "wave.vvp")
    c = run(["iverilog", "-g2012", f"-DTCLK={tclk}", f"-DCFGVAL={cfgval}", "-o", vvp,
             "rtl/tt_analog/cirom_tt_ctrl.sv", "rtl/tt_analog/sim/tb_ctrl_waveform.sv"])
    if c.returncode: raise RuntimeError("iverilog failed:\n" + c.stderr)
    r = run(["vvp", vvp])
    if r.returncode: raise RuntimeError("vvp failed:\n" + r.stdout + r.stderr)
    return os.path.join(BUILD, "ctrl_wave.vcd")

def parse_vcd(path, names):
    code, want = {}, set(names)
    series = {n: [] for n in names}; t_ns = 0.0; in_defs = True
    for line in open(path):
        line = line.strip()
        if in_defs and line.startswith("$var"):
            p = line.split()
            if p[4] in want: code[p[3]] = p[4]
        elif line == "$enddefinitions $end": in_defs = False
        elif line.startswith("#"): t_ns = int(line[1:]) / 1000.0
        elif line and line[0] in "01xz" and not in_defs:
            if line[1:] in code: series[code[line[1:]]].append((t_ns, 1 if line[0] == "1" else 0))
    return series

def first_strobe_window(series, gate):
    intervals, t_on = [], None
    for t, v in series[gate]:
        if v == 1 and t_on is None: t_on = t
        elif v == 0 and t_on is not None: intervals.append((t_on, t)); t_on = None
    if t_on is not None: intervals.append((t_on, 1e12))
    st = series["strobe_w"]
    for i, (t, v) in enumerate(st):
        if v == 1 and any(a <= t < b for a, b in intervals):
            fall = next((tt for tt, vv in st[i+1:] if vv == 0), t + 1.0)
            return t, fall
    return None, None

def shifted_pwl(series, name, shift, vname, idle, vh=VDD, edge=0.1):
    tr = [(round(t - shift, 4), v) for t, v in series[name] if t - shift >= -0.001]
    pts = [(0.0, idle * vh)]
    for t, v in tr:
        if t <= 0: pts = [(0.0, v * vh)]; continue
        pts.append((t, pts[-1][1])); pts.append((round(t + edge, 4), v * vh))
    return f"{vname} {name[:-2].replace('pre_n','PRE_N').replace('wl0','WL_0').replace('strobe','strobe')} 0 " \
           f"pwl({' '.join(f'{t}n {v}' for t, v in pts)})"

def confirm():
    s = parse_vcd(gen_vcd(), ["pre_n_w", "wl0_w", "wl1_w", "strobe_w"])
    t0r, t0f = first_strobe_window(s, "wl0_w")
    pre_falls = [t for t, v in s["pre_n_w"] if v == 0 and t < t0r]
    shift = (max(pre_falls) if pre_falls else 0.0) - 5.0
    sr, sf = round(t0r - shift, 3), round(t0f - shift, 3)        # strobe edge/fall in shifted frame
    wlties = "\n".join(f"V_wl{i} WL_{i} 0 0" for i in range(1, 64))
    deck = "\n".join([
        "* signoff-arch controller waveform on RC + real VREF, ff/125 (read0 +1)",
        lib_path("ff"), ".temp 125", ".param vdd=1.8",
        f".include {RC}", f".include {SA}",
        "Vdd VPWR 0 dc {vdd}", "Vgnd VGND 0 dc 0",
        "R_vrt VPWR vref 180k", "R_vrb vref VGND 180k", "C_vref vref 0 7.5p ic={vdd/2}",
        shifted_pwl(s, "pre_n_w", shift, "Vpre", 1),
        shifted_pwl(s, "wl0_w", shift, "Vwl0", 0),
        shifted_pwl(s, "strobe_w", shift, "Vstr", 0),
        wlties,
        "Xsap BLP_0 vref hit_p hitb_p strobe VPWR 0 sa_se",
        "Xsan BLN_0 vref hit_n hitb_n strobe VPWR 0 sa_se",
        f".tran 0.02n {round(sf + 3, 2)}n uic", ".control", "run",
        f"meas tran bln_edge find v(BLN_0) at={round(sr+0.3,3)}n",
        f"meas tran bln_end  find v(BLN_0) at={round(sf-0.5,3)}n",
        f"meas tran blp_end  find v(BLP_0) at={round(sf-0.5,3)}n",
        f"meas tran hit_p    find v(hit_p)  at={round(sf-0.5,3)}n",
        f"meas tran hitb_p   find v(hitb_p) at={round(sf-0.5,3)}n",
        f"meas tran hit_n    find v(hit_n)  at={round(sf-0.5,3)}n",
        f"meas tran hitb_n   find v(hitb_n) at={round(sf-0.5,3)}n",
        f"meas tran vref_edge find v(vref) at={round(sr+0.3,3)}n",
        "quit", ".endc", ".end"])
    path = os.path.join(BUILD, "cosim_confirm.sp"); open(path, "w").write(deck + "\n")
    out = (lambda r: r.stdout + r.stderr)(run(["ngspice", "-b", path]))
    g = lambda k: (lambda m: float(m.group(1)) if m else None)(re.search(rf"^{k}\s*=\s*([-\d.e+]+)", out, re.M))
    pos_fire = (g("hit_p") or 0) > (g("hitb_p") or 0)
    neg_fire = (g("hit_n") or 0) > (g("hitb_n") or 0)
    ok = pos_fire and not neg_fire
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    log = os.path.join(BUILD, f"cosim_confirm_{stamp}.log")
    lines = [f"mixed-signal confirm (rebuilt no-mux controller) {stamp}",
             "analog: macro_rc_clean.spice + sense_col_schematic.spice; ff/125; real divider+decap VREF",
             f"stimulus: rebuilt cirom_tt_ctrl actual waveform (strobe {sr}->{sf}ns shifted frame)",
             f"read0 (+1): BLP_0(end)={g('blp_end'):.3f} BLN_0(edge)={g('bln_edge'):.3f} BLN_0(end)={g('bln_end'):.3f} VREF(edge)={g('vref_edge'):.3f}",
             f"  hit_p={g('hit_p'):.3f}/hitb_p={g('hitb_p'):.3f} -> fire_pos={pos_fire}; "
             f"hit_n={g('hit_n'):.3f}/hitb_n={g('hitb_n'):.3f} -> fire_neg={neg_fire}",
             "RESULT: " + ("PASS (rebuilt controller reads +1 correctly on RC+realVREF at ff/125)"
                           if ok else "FAIL")]
    txt = "\n".join(lines); open(log, "w").write(txt + "\n"); print(txt); print("logged ->", log)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    confirm()
