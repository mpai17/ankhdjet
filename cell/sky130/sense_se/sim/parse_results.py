"""Parse single-ended sense validation logs (build_val/) into pass/fail
tables. Standalone (run with `uv run` from this dir) to avoid
heredoc/quoting corruption.

HIT decode: v_hit_final > 0.9*VDD -> HIT=1 (BL discharged), else HIT=0.
A log with no v_hit_final measure is an INFRA-FAIL (ngspice produced a
DC-op-point-only log under load) -- reported separately from sense-fails.
"""
import re, glob, os

HERE = os.path.dirname(os.path.abspath(__file__))
VAL = os.path.join(HERE, "build_val")


def meas(path, key):
    try:
        t = open(path).read()
    except OSError:
        return None
    m = re.search(rf"{key}\s*=\s*([-\d.eE+]+)", t)
    return float(m.group(1)) if m else None


def vdd_of(path):
    # decks set ".param VDD_V = X"; default 1.8
    try:
        t = open(path).read()
    except OSError:
        return 1.8
    m = re.search(r"\.param VDD_V\s*=\s*([\d.]+)", t)
    return float(m.group(1)) if m else 1.8


def dyn_per_corner():
    print("=== [1] dynamic per-corner (ideal VREF) ===")
    ok = True
    for c in ("tt", "ss", "ff"):
        for w in (1, 0):
            f = os.path.join(VAL, f"dyn_{c}_w{w}.log")
            h = meas(f, "v_hit_final"); bl = meas(f, "v_bl_at_strobe")
            if h is None:
                print(f"  {c} w={w}: INFRA-FAIL"); ok = False; continue
            dec = 1 if h > 0.9 else 0
            ok = ok and dec == w
            print(f"  {c} w={w}: BL@strobe={bl:.3f}V HIT={h:.2f}V dec={dec} exp={w} "
                  f"{'OK' if dec==w else 'FAIL'}")
    print("  =>", "ALL OK" if ok else "FAILURES")


def divider_per_corner():
    print("=== [2] real resistor-divider VREF (with strobe kickback) ===")
    ok = True; kicks = []
    for c in ("tt", "ss", "ff"):
        for w in (1, 0):
            f = os.path.join(VAL, f"vd_{c}_w{w}.log")
            vdc = meas(f, "vref_dc"); vmn = meas(f, "vref_min")
            vmx = meas(f, "vref_max"); h = meas(f, "v_hit_final")
            if h is None or vdc is None:
                print(f"  {c} w={w}: INFRA-FAIL"); ok = False; continue
            kick = max(abs((vmx or vdc) - vdc), abs(vdc - (vmn or vdc))) * 1000
            kicks.append(kick)
            dec = 1 if h > 0.9 else 0
            ok = ok and dec == w
            print(f"  {c} w={w}: VREF_dc={vdc:.3f}V kickback={kick:.0f}mV "
                  f"HIT={h:.2f}V dec={dec} exp={w} {'OK' if dec==w else 'FAIL'}")
    if kicks:
        print(f"  => {'ALL OK' if ok else 'FAILURES'}; "
              f"worst VREF kickback during strobe = {max(kicks):.0f} mV")


def dyn_mc():
    print("=== [3] dynamic Monte Carlo (SS + mismatch) ===")
    for w, exp in ((1, 1), (0, 0)):
        hi = bad = n = 0
        for f in sorted(glob.glob(os.path.join(VAL, f"dmc_w{w}_s*.log"))):
            h = meas(f, "v_hit_final")
            if h is None:
                bad += 1; continue
            n += 1
            if h > 0.9:
                hi += 1
        correct = hi if exp == 1 else n - hi
        pct = f"{100*correct/n:.1f}%" if n else "n/a"
        print(f"  weight={w}: correct {correct}/{n} ({pct})  infra-fail {bad}")


def vt_sweep():
    print("=== [4] V/T/process sweep (divider VREF) ===")
    rows = fails = infra = 0
    for f in sorted(glob.glob(os.path.join(VAL, "vt_*.log"))):
        m = re.match(r"vt_(\w+?)_v([\d.]+)_t(-?\d+)_w(\d)\.log", os.path.basename(f))
        if not m:
            continue
        c, v, t, w = m.group(1), m.group(2), m.group(3), int(m.group(4))
        rows += 1
        h = meas(f, "v_hit_final")
        if h is None:
            infra += 1; print(f"  {c} {v}V {t}C w={w}: INFRA-FAIL"); continue
        # Decide HIT vs no-HIT at mid-rail (VDD/2) for this deck's VDD. A
        # valid HIT resolves above VDD/2 (toward VDD); a no-HIT sits near 0.
        # (Do NOT use 0.9*VDD: with the divider VREF a valid HIT settles
        #  ~1.5V at 1.8V VDD, which is a clear '1' but below 0.9*VDD.)
        dec = 1 if h > 0.5 * float(v) else 0
        if dec != w:
            fails += 1
            print(f"  {c} {v}V {t}C w={w}: HIT={h:.2f} dec={dec} exp={w} *** FAIL")
    print(f"  => {rows} corners, {fails} sense-fails, {infra} infra-fails"
          + ("  ALL OK" if (rows and fails == 0 and infra == 0) else ""))


if __name__ == "__main__":
    dyn_per_corner()
    divider_per_corner()
    dyn_mc()
    vt_sweep()
