"""Functional SPICE regression of the layout-extracted CiROM macro.

Drives the capacitance-extracted `macro_array_pc_<N>x<M>_<program>` netlist
(bitcells + precharge row exactly as laid out, with the real bitline and
coupling capacitance) through the read contract row by row -- precharge,
evaluate with one wordline asserted, sample -- and checks every (row,
column) bitline pair against the mask program's weight source.

This is the link the other macro checks cannot provide. DRC and LVS prove
the layout matches the generated schematic; the behavioral bench proves the
RTL reads the memh views. Only a transient of the extracted layout shows
that the programmed bitline actually discharges and the unprogrammed one
actually holds, for every cell, at the timing the controllers drive.

Reference: the weight matrix is read from the program's {+,-,0} text source
(weights/<program>.wmat, or the built-in pattern for checker / all_pos /
all_neg), not from the memh views or the LVS schematic, so the comparison is
independent of both generated views.

Per-line verdicts, sampled where the controller's flops capture hit = ~BL
(the clock edge that ends the sample state, one clock after evaluate ends,
with the wordline still high). A line is judged against the sampler
threshold: VDD/2 by default, or the digital tier's measured register-input
threshold (DIGITAL_SAMPLER_VTH, --digital-sampler), which is how the
readout of record samples a bitline. The run fails on any line that sits
on the wrong side of that threshold; lines inside the margin band (default
0.2 VDD) are reported as marginal but do not fail, since the margin is a
design-review number, not the read itself:

  pass                 programmed line < vth - margin, unprogrammed > vth + margin
  decision_flip        a line sits on the wrong side of vth (fails the run)
  marginal_low         programmed line below vth but inside the margin band
  marginal_high        unprogrammed line above vth but inside the margin band
  measurement_missing  ngspice produced no value for the line (fails the run)

The bitline load beyond the macro (chip routing plus the sampler input) can
be applied uniformly or per line from a load file for chip-level review;
the regression itself judges the macro alone.

Row chunks run in parallel ngspice processes. Every run writes a timestamped
summary log and a per-line CSV under macro/sky130/build/extracted_macro/.

CLI (from anywhere):
  python macro/sky130/sim/extracted_macro/runner.py --digital-sampler
  python macro/sky130/sim/extracted_macro/runner.py --rows 0-7 --corner ss --workers 4
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
CELL_BUILD = REPO / "cell" / "sky130" / "macro" / "build"
ABSTRACTS = REPO / "macro" / "sky130" / "abstracts"
WEIGHTS = REPO / "weights"
LOG_DIR = REPO / "macro" / "sky130" / "build" / "extracted_macro"

sys.path.insert(0, str(REPO))
from tools.regression_log import write_summary  # noqa: E402

MACRO_RE = re.compile(r"^macro_array_pc_(\d+)x(\d+)_([A-Za-z0-9]+)$")

# Corner presets: (temperature C, VDD V). ss stresses the discharge (slow,
# low supply); ff stresses the hold (hot, high supply, maximum leakage and
# strongest coupling); tt is the nominal signoff point.
CORNERS = {"tt": (27.0, 1.80), "ss": (100.0, 1.62), "ff": (125.0, 1.95)}

# Reported clearance band around the sampler threshold, as a fraction of VDD.
MARGIN_FRAC = 0.20

# Measured input threshold of the digital tier's sampler per corner (volts):
# a bitline drives an inverter-class sky130_fd_sc_hd input (1.0 um high-Vt
# PMOS over a 0.65 um NMOS) ahead of the capture register; DC transfer
# sweeps of inv_1, nand2_1 and mux2_1 agree within 50 mV, these are the
# inv_1 values.
DIGITAL_SAMPLER_VTH = {"tt": 0.785, "ss": 0.770, "ff": 0.840}

PASS = "pass"
FAIL_FLIP = "decision_flip"
FAIL_WEAK = "marginal_low"
FAIL_DROOP = "marginal_high"
FAIL_MISSING = "measurement_missing"
FAIL_NGSPICE = "ngspice_failed"


# ---------------------------------------------------------------- inputs --

def pdk_root() -> Path:
    return Path(os.environ.get("PDK_ROOT", Path.home() / ".ciel"))


def sky130_lib() -> Path:
    return pdk_root() / "sky130A" / "libs.tech" / "ngspice" / "sky130.lib.spice"


def magicrc() -> Path:
    return pdk_root() / "sky130A" / "libs.tech" / "magic" / "sky130A.magicrc"


def discover_macros() -> list[str]:
    """Built macros (a .mag under cell/sky130/macro/build), any program name."""
    if not CELL_BUILD.exists():
        return []
    return sorted(p.stem for p in CELL_BUILD.glob("macro_array_pc_*.mag")
                  if MACRO_RE.match(p.stem))


def macro_shape(macro: str) -> tuple[int, int, str]:
    m = MACRO_RE.match(macro)
    if not m:
        raise ValueError(f"not a macro name: {macro}")
    return int(m.group(1)), int(m.group(2)), m.group(3)


def load_weights(program: str, n_rows: int, n_cols: int) -> np.ndarray:
    """(N, M) int8 in {-1, 0, +1} from the program's text source."""
    wmat = WEIGHTS / f"{program}.wmat"
    if wmat.exists():
        rows = [ln.strip() for ln in wmat.read_text().splitlines() if ln.strip()]
        assert len(rows) == n_rows and all(len(r) == n_cols for r in rows), \
            f"{wmat}: expected {n_rows}x{n_cols}"
        return np.array([[{"+": 1, "-": -1, "0": 0}[ch] for ch in r] for r in rows],
                        dtype=np.int8)
    if program == "all_pos":
        return np.ones((n_rows, n_cols), dtype=np.int8)
    if program == "all_neg":
        return -np.ones((n_rows, n_cols), dtype=np.int8)
    if program == "checker":
        r, c = np.indices((n_rows, n_cols))
        return np.where((r + c) % 2 == 0, 1, -1).astype(np.int8)
    raise FileNotFoundError(f"no weight source for program {program!r}: {wmat}")


def load_memh(macro: str, n_rows: int, n_cols: int) -> tuple[np.ndarray, np.ndarray]:
    """(wpos, wneg) bool (N, M) from the abstracts' simulation views."""
    out = []
    for pol in ("pos", "neg"):
        words = [int(w, 16) for w in
                 (ABSTRACTS / f"{macro}.w{pol}.memh").read_text().split()]
        assert len(words) == n_rows
        out.append(np.array([[(w >> c) & 1 for c in range(n_cols)] for w in words],
                            dtype=bool))
    return out[0], out[1]


# ------------------------------------------------------------ extraction --

def extract_for_sim(macro: str, force: bool = False) -> Path:
    """Flatten the macro and extract it with capacitance (no resistance)
    into cell/sky130/macro/build/<macro>_csim.spice; cached per checkout."""
    out = CELL_BUILD / f"{macro}_csim.spice"
    if out.exists() and not force:
        return out
    if not (CELL_BUILD / f"{macro}.mag").exists():
        raise FileNotFoundError(f"macro not built: {CELL_BUILD / (macro + '.mag')}")
    flat = f"{macro}_csim"
    tcl = "\n".join([
        "drc off",
        "crashbackups stop",
        f"load {macro}",
        f"flatten {flat}",
        f"load {flat}",
        "select top cell",
        "extract no resistance",
        "extract do capacitance",
        "extract do coupling",
        "extract unique",
        "extract all",
        "ext2spice format ngspice",
        "ext2spice cthresh 0",
        "ext2spice rthresh infinite",
        "ext2spice subcircuit on",
        "ext2spice subcircuit top on",
        f"ext2spice -o {out.name}",
        'puts "CSIM_EXTRACT_DONE"',
        "quit -noprompt",
    ]) + "\n"
    # the PDK's rcfile locates the tech file through PDK_ROOT, falling back to the
    # path it was built at, so the environment has to carry the root
    env = {**os.environ, "PDK_ROOT": str(pdk_root())}
    r = subprocess.run(
        ["magic", "-dnull", "-noconsole", "-rcfile", str(magicrc())],
        cwd=CELL_BUILD, input=tcl, text=True, capture_output=True, timeout=1800, env=env,
    )
    if "CSIM_EXTRACT_DONE" not in r.stdout or not out.exists():
        raise RuntimeError(f"magic extraction failed for {macro}:\n"
                           f"{(r.stdout + r.stderr)[-3000:]}")
    return out


def subckt_ports(netlist: Path) -> tuple[str, list[str]]:
    """(subckt name, port list) from the first .subckt header, continuation-aware."""
    hdr: list[str] = []
    for ln in netlist.read_text().splitlines():
        if ln.lower().startswith(".subckt"):
            hdr.append(ln)
        elif hdr:
            if ln.startswith("+"):
                hdr.append(ln[1:])
            else:
                break
    toks = " ".join(hdr).split()
    if len(toks) < 2:
        raise ValueError(f"no .subckt header in {netlist}")
    return toks[1], toks[2:]


# ----------------------------------------------------------------- deck --

@dataclass(frozen=True)
class ReadTiming:
    """Read-contract timing as the controllers drive it: PRE_N low for
    `pre_cycles` clocks, then one WL high for `eval_cycles` clocks plus the
    one-clock sample state; the flops capture on the edge that ends the
    sample state, then one more clock covers accumulate/next before the
    next precharge. Defaults match the digital tile bench (20 MHz,
    pre_width = strobe_delay = 2)."""
    tclk_ns: float = 50.0
    pre_cycles: int = 3
    eval_cycles: int = 3
    edge_ns: float = 0.2      # driver rise/fall
    wl_delay_ns: float = 0.5  # decoder delay: break-before-make after PRE_N rises

    @property
    def pre_ns(self) -> float:
        return self.pre_cycles * self.tclk_ns

    @property
    def eval_ns(self) -> float:
        return self.eval_cycles * self.tclk_ns

    @property
    def cycle_ns(self) -> float:
        return self.pre_ns + self.eval_ns + 2 * self.tclk_ns

    def wl_off_ns(self, slot: int) -> float:
        return slot * self.cycle_ns + self.pre_ns + self.eval_ns + self.tclk_ns

    def sample_ns(self, slot: int) -> float:
        return self.wl_off_ns(slot) - 0.1   # the capture edge, WL still high


def _t(x: float) -> str:
    return f"{round(x, 4):.4f}n"


def _pwl(name: str, node: str, pts: list[tuple[float, float]]) -> str:
    body = " ".join(f"{_t(t)} {v:.4g}" for t, v in pts)
    return f"{name} {node} 0 PWL({body})"


def load_bl_caps(path: str | Path) -> dict[str, float]:
    """Per-line external capacitance in fF from a two-column text file
    ("BLP_3 11.2" per line), e.g. the chip routing + sampler load taken
    from a tile extraction; lines not listed get the --extra-bl-cap value."""
    caps = {}
    for ln in Path(path).read_text().splitlines():
        toks = ln.split()
        if len(toks) >= 2 and not ln.startswith("#"):
            caps[toks[0]] = float(toks[1])
    return caps


def emit_deck(netlist: Path, subckt: str, ports: list[str], rows: list[int],
              n_cols: int, corner: str, timing: ReadTiming,
              extra_bl_cap_ff: float = 0.0,
              bl_caps_ff: dict[str, float] | None = None) -> str:
    temp_c, vdd = CORNERS[corner]
    e = timing.edge_ns
    stop = len(rows) * timing.cycle_ns + timing.tclk_ns

    # PRE_N: low during every slot's precharge state, high otherwise.
    pre_pts: list[tuple[float, float]] = [(0.0, 0.0)]
    for k in range(len(rows)):
        t0 = k * timing.cycle_ns
        if k:
            pre_pts += [(t0, vdd), (t0 + e, 0.0)]
        pre_pts += [(t0 + timing.pre_ns, 0.0), (t0 + timing.pre_ns + e, vdd)]
    pre_pts.append((stop, vdd))

    # WL_r: high from after PRE_N rises through the sample cycle of its slot.
    wl_lines = []
    slot_of = {r: k for k, r in enumerate(rows)}
    for r in range(_n_rows(ports)):
        if r in slot_of:
            t0 = slot_of[r] * timing.cycle_ns
            t_on = t0 + timing.pre_ns + e + timing.wl_delay_ns
            t_off = timing.wl_off_ns(slot_of[r])
            wl_lines.append(_pwl(f"Vwl{r}", f"WL_{r}", [
                (0.0, 0.0), (t_on, 0.0), (t_on + e, vdd),
                (t_off, vdd), (t_off + e, 0.0), (stop, 0.0)]))
        else:
            wl_lines.append(f"Vwl{r} WL_{r} 0 0")

    # Connect the extracted subckt by port name; power to the rails, any
    # extra port (substrate, unlabeled) to ground.
    def node(p: str) -> str:
        if p == "VPWR":
            return "vdd"
        if p == "VGND":
            return "0"
        if p == "PRE_N" or p.startswith("WL_") or p.startswith("BLP_") or p.startswith("BLN_"):
            return p
        return "0"
    conn = [node(p) for p in ports]
    inst = ["Xmacro " + " ".join(conn[:12])]
    inst += ["+ " + " ".join(conn[i:i + 16]) for i in range(12, len(conn), 16)]
    inst.append(f"+ {subckt}")

    # External load per bitline beyond the macro: chip routing + sampler input.
    ext = []
    for c in range(n_cols):
        for pol in ("BLP", "BLN"):
            name = f"{pol}_{c}"
            cap = (bl_caps_ff or {}).get(name, extra_bl_cap_ff)
            if cap > 0:
                ext.append(f"Cext_{name} {name} 0 {cap:.4f}f")

    meas = []
    for k, r in enumerate(rows):
        ts = timing.sample_ns(k)
        for c in range(n_cols):
            meas.append(f".meas tran v_blp_r{r}_c{c} find v(BLP_{c}) at={_t(ts)}")
            meas.append(f".meas tran v_bln_r{r}_c{c} find v(BLN_{c}) at={_t(ts)}")

    lines = [
        f"* extracted-macro read sweep: {subckt} rows={rows} corner={corner}",
        f'.lib "{sky130_lib()}" {corner}',
        f".temp {temp_c}",
        f".param VDD_V = {vdd}",
        ".option klu",
        ".option noinit",
        ".option reltol=1e-3",
        ".option method=trap",
        f".include {netlist}",
        "Vvdd vdd 0 'VDD_V'",
        _pwl("Vpre", "PRE_N", pre_pts),
        *wl_lines,
        *inst,
        *ext,
        *meas,
        f".tran 0.1n {_t(stop)} 0 0.5n",
        ".end",
    ]
    return "\n".join(lines) + "\n"


def _n_rows(ports: list[str]) -> int:
    return sum(1 for p in ports if p.startswith("WL_"))


# ------------------------------------------------------------- run/check --

_MEAS_RE = re.compile(r"^\s*v_(blp|bln)_r(\d+)_c(\d+)\s*=\s*([-\d.eE+]+)", re.M)


def run_chunk(deck_path: Path, timeout_s: float) -> tuple[dict, float, str]:
    """Run one deck; return ({(pol, r, c): volts}, seconds, error-or-empty)."""
    t0 = time.time()
    try:
        r = subprocess.run(["ngspice", "-b", str(deck_path)],
                           capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {}, time.time() - t0, f"ngspice timeout after {timeout_s:.0f}s"
    out = r.stdout + r.stderr
    vals = {(m.group(1), int(m.group(2)), int(m.group(3))): float(m.group(4))
            for m in _MEAS_RE.finditer(out)}
    err = "" if (r.returncode == 0 or vals) else f"ngspice rc={r.returncode}:\n{out[-2000:]}"
    return vals, time.time() - t0, err


def check_rows(W: np.ndarray, rows: list[int], vals: dict, vdd: float,
               margin_frac: float = MARGIN_FRAC, vth: float | None = None) -> list[dict]:
    """Per-line verdicts for the swept rows; one dict per line. `margin` is
    the line's clearance from the sampler threshold (`vth`, default VDD/2)
    in the correct direction (negative when flipped)."""
    v_mid = 0.5 * vdd if vth is None else vth
    v_low, v_high = v_mid - margin_frac * vdd, v_mid + margin_frac * vdd
    out = []
    for r in rows:
        for c in range(W.shape[1]):
            for pol, programmed in (("blp", W[r, c] == 1), ("bln", W[r, c] == -1)):
                v = vals.get((pol, r, c))
                if v is None:
                    kind, margin = FAIL_MISSING, None
                elif programmed:
                    kind = PASS if v < v_low else (FAIL_WEAK if v < v_mid else FAIL_FLIP)
                    margin = v_mid - v
                else:
                    kind = PASS if v > v_high else (FAIL_DROOP if v > v_mid else FAIL_FLIP)
                    margin = v - v_mid
                out.append(dict(r=r, c=c, pol=pol, w=int(W[r, c]), v=v, kind=kind,
                                margin=margin))
    return out


def parse_rows(spec: str, n_rows: int) -> list[int]:
    if spec == "all":
        return list(range(n_rows))
    rows: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            rows += list(range(int(a), int(b) + 1))
        else:
            rows.append(int(part))
    bad = [r for r in rows if not 0 <= r < n_rows]
    if bad:
        raise ValueError(f"rows out of range: {bad}")
    return rows


def run_macro(macro: str, rows: str | list[int] = "all", corner: str = "tt",
              timing: ReadTiming = ReadTiming(), workers: int | None = None,
              timeout_s: float = 1800.0, force_extract: bool = False,
              margin_frac: float = MARGIN_FRAC, argv: list[str] | None = None,
              extra_bl_cap_ff: float = 0.0, bl_caps_ff: dict[str, float] | None = None,
              tag: str = "", vth: float | None = None) -> dict:
    """Sweep `rows` of `macro` at `corner`; write the summary log; return
    {"ok", "macro", "corner", "rows", "n_lines", "counts", "failures",
     "log", "runtime_s"}."""
    t_start = time.time()
    n_rows, n_cols, program = macro_shape(macro)
    W = load_weights(program, n_rows, n_cols)
    row_list = parse_rows(rows, n_rows) if isinstance(rows, str) else list(rows)
    _, vdd = CORNERS[corner]

    netlist = extract_for_sim(macro, force=force_extract)
    subckt, ports = subckt_ports(netlist)
    assert _n_rows(ports) == n_rows, f"{netlist}: {_n_rows(ports)} WL ports, expected {n_rows}"

    workers = workers or max(1, min(8, (os.cpu_count() or 4) - 1))
    n_chunks = min(workers, len(row_list))
    chunks = [row_list[i::n_chunks] for i in range(n_chunks)]
    work = LOG_DIR / "decks"
    work.mkdir(parents=True, exist_ok=True)

    def job(i_chunk: int) -> tuple[list[int], dict, float, str]:
        chunk = sorted(chunks[i_chunk])
        deck = work / f"{macro}_{corner}_chunk{i_chunk}.sp"
        deck.write_text(emit_deck(netlist, subckt, ports, chunk, n_cols, corner, timing,
                                  extra_bl_cap_ff, bl_caps_ff))
        vals, secs, err = run_chunk(deck, timeout_s)
        return chunk, vals, secs, err

    lines: list[dict] = []
    chunk_notes: list[str] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=n_chunks) as ex:
        for chunk, vals, secs, err in ex.map(job, range(n_chunks)):
            chunk_notes.append(f"rows {chunk[0]}..{chunk[-1]} ({len(chunk)}): {secs:.1f}s"
                               + (f"  ERROR {err.splitlines()[0]}" if err else ""))
            if err:
                errors.append(err)
            lines += check_rows(W, chunk, vals, vdd, margin_frac, vth)

    counts: dict[str, int] = {}
    for ln in lines:
        counts[ln["kind"]] = counts.get(ln["kind"], 0) + 1
    failures = [ln for ln in lines if ln["kind"] != PASS]
    hard = [ln for ln in failures if ln["kind"] in (FAIL_FLIP, FAIL_MISSING)]
    ok = not hard and not errors
    runtime = time.time() - t_start
    v_th = 0.5 * vdd if vth is None else vth
    margins = [ln["margin"] for ln in lines if ln["margin"] is not None]
    prog = [ln["margin"] for ln in lines if ln["margin"] is not None and ln["w"] != 0
            and ((ln["pol"] == "blp") == (ln["w"] == 1))]
    held = [ln["margin"] for ln in lines if ln["margin"] is not None and
            not (ln["w"] != 0 and (ln["pol"] == "blp") == (ln["w"] == 1))]

    body = [
        f"macro:        {macro}   ({n_rows} rows x {n_cols} cols, program {program})",
        f"netlist:      {netlist}",
        f"weight src:   {WEIGHTS / (program + '.wmat')}"
        if (WEIGHTS / (program + '.wmat')).exists() else f"weight src:   built-in pattern {program}",
        f"corner:       {corner}  (T={CORNERS[corner][0]:.0f}C, VDD={vdd:.2f}V)",
        f"timing:       tclk={timing.tclk_ns}ns pre={timing.pre_cycles}cyc "
        f"eval={timing.eval_cycles}cyc  sample at end of evaluate",
        "external BL load: " + (f"per-line file, {len(bl_caps_ff)} lines listed, "
                                f"others {extra_bl_cap_ff:.2f}fF" if bl_caps_ff
                                else f"{extra_bl_cap_ff:.2f}fF on every line"),
        f"thresholds:   sampler threshold {v_th:.3f}V ({'VDD/2' if vth is None else 'measured digital sampler'}), "
        f"required clearance {margin_frac * vdd:.2f}V "
        f"(discharged < {v_th - margin_frac * vdd:.2f}V, held > {v_th + margin_frac * vdd:.2f}V)",
        f"rows swept:   {len(row_list)} of {n_rows}   lines checked: {len(lines)}",
        "counts:       " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        "min clearance from threshold:  "
        + (f"discharged lines {min(prog):+.3f}V, " if prog else "")
        + (f"held lines {min(held):+.3f}V" if held else "")
        + (f"  (overall {min(margins):+.3f}V)" if margins else ""),
        "",
        "chunks:",
        *[f"  {n}" for n in chunk_notes],
        "",
    ]
    if errors:
        body += ["ngspice errors:", *errors, ""]
    if failures:
        # every flip / missing line, then the marginal lines nearest the
        # threshold; the CSV beside the log carries all lines.
        sev = {FAIL_FLIP: 0, FAIL_MISSING: 0, FAIL_WEAK: 1, FAIL_DROOP: 1}
        failures.sort(key=lambda f: (sev[f["kind"]],
                                     f["margin"] if f["margin"] is not None else -9.0))
        n_hard = sum(1 for f in failures if sev[f["kind"]] == 0)
        body.append(f"failures ({len(failures)}: {n_hard} flip/missing, "
                    f"{len(failures) - n_hard} marginal), worst first, first 200:")
        for f in failures[:200]:
            vtxt = "n/a" if f["v"] is None else f"{f['v']:.3f}V"
            mtxt = "" if f["margin"] is None else f" clearance={f['margin']:+.3f}V"
            body.append(f"  r={f['r']:2d} c={f['c']:2d} {f['pol'].upper()} w={f['w']:+d} "
                        f"v={vtxt}{mtxt} {f['kind']}")
    else:
        body.append("every swept line reads its programmed value with margin")
    body.append("")
    body.append("RESULT: " + ("PASS" if ok else "FAIL")
                + (f" ({len(failures) - len(hard)} marginal lines reported)" if ok and failures else ""))

    log = write_summary(LOG_DIR, f"{macro}_{corner}{('_' + tag) if tag else ''}",
                        argv if argv is not None else [sys.argv[0]],
                        "\n".join(body) + "\n", ok, runtime)
    csv = log.with_name(log.name.replace("summary_", "lines_")).with_suffix(".csv")
    with open(csv, "w") as fh:
        fh.write("row,col,line,weight,volts,clearance_v,verdict\n")
        for ln in sorted(lines, key=lambda x: (x["r"], x["c"], x["pol"])):
            v = "" if ln["v"] is None else f"{ln['v']:.4f}"
            m = "" if ln["margin"] is None else f"{ln['margin']:+.4f}"
            fh.write(f"{ln['r']},{ln['c']},{ln['pol'].upper()},{ln['w']:+d},{v},{m},{ln['kind']}\n")
    return dict(ok=ok, macro=macro, corner=corner, rows=row_list, n_lines=len(lines),
                counts=counts, failures=failures, hard=hard, errors=errors, log=log,
                runtime_s=runtime)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--macro", default=None,
                    help="built macro name (default: every built macro)")
    ap.add_argument("--rows", default="all", help="all | 0,5,63 | 0-7")
    ap.add_argument("--corner", default="tt", choices=sorted(CORNERS))
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--tclk", type=float, default=ReadTiming.tclk_ns)
    ap.add_argument("--pre-cycles", type=int, default=ReadTiming.pre_cycles)
    ap.add_argument("--eval-cycles", type=int, default=ReadTiming.eval_cycles)
    ap.add_argument("--timeout", type=float, default=1800.0, help="per-chunk ngspice seconds")
    ap.add_argument("--margin", type=float, default=MARGIN_FRAC,
                    help="required clearance from VDD/2 as a fraction of VDD")
    ap.add_argument("--force-extract", action="store_true")
    ap.add_argument("--extra-bl-cap", type=float, default=0.0,
                    help="external capacitance per bitline in fF (chip routing + sampler)")
    ap.add_argument("--bl-cap-file", default=None,
                    help="per-line external capacitance file: '<BLP_c|BLN_c> <fF>' per line")
    ap.add_argument("--tag", default="", help="suffix for the summary log name")
    ap.add_argument("--vth", type=float, default=None,
                    help="sampler threshold in volts (default VDD/2); e.g. the measured "
                         "input threshold of the tile's sampling gate at this corner")
    ap.add_argument("--digital-sampler", action="store_true",
                    help="judge against the digital tier's measured register-input "
                         "threshold for the corner (DIGITAL_SAMPLER_VTH) instead of VDD/2")
    args = ap.parse_args(argv)

    macros = [args.macro] if args.macro else discover_macros()
    if not macros:
        print(f"no built macro under {CELL_BUILD} (run tools/gen_macro.sh first)")
        return 2
    timing = ReadTiming(tclk_ns=args.tclk, pre_cycles=args.pre_cycles,
                        eval_cycles=args.eval_cycles)
    vth, cap_file = args.vth, args.bl_cap_file
    if args.digital_sampler and vth is None:
        vth = DIGITAL_SAMPLER_VTH[args.corner]
    all_ok = True
    for macro in macros:
        res = run_macro(macro, args.rows, args.corner, timing, args.workers,
                        args.timeout, args.force_extract, args.margin, argv=sys.argv,
                        extra_bl_cap_ff=args.extra_bl_cap,
                        bl_caps_ff=load_bl_caps(cap_file) if cap_file else None,
                        tag=args.tag, vth=vth)
        counts = ", ".join(f"{k}={v}" for k, v in sorted(res["counts"].items()))
        print(f"{macro} @{args.corner}: {'PASS' if res['ok'] else 'FAIL'}  "
              f"{res['n_lines']} lines [{counts}]  {res['runtime_s']:.0f}s  -> {res['log']}")
        for f in res["failures"][:20]:
            print(f"  r={f['r']} c={f['c']} {f['pol']} w={f['w']:+d} v={f['v']} "
                  f"clearance={f['margin']} {f['kind']}")
        all_ok &= res["ok"]
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
