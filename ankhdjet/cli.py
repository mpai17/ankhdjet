"""The `ankhdjet` command: checkpoint in, mask set out.

Two commands cover the installable package's scope:

    ankhdjet compile   HuggingFace ternary checkpoint -> a complete design
                       bundle: per-layer mask-program macro grids (.wmat
                       chunks + manifests) plus a self-contained RTL view
                       (grid tops + copied library + memh sim views +
                       filelist) that elaborates without the repository
    ankhdjet estimate  area + bracketed-throughput report for any model
                       shape on any bundled PDK descriptor

The physical flow (custom cells, LibreLane hardening, signoff) lives in
the repository, not the wheel: it needs the open-silicon toolchain.
"""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version


def _replay_unexpected_warnings(caught, skip_layers) -> None:
    """Re-emit recorded warnings except the frontend's placeholder
    warnings for layers compile skips as off-fabric by contract: those
    are expected on every run and are reported as a summary line
    instead of an alarm."""
    import warnings

    expected = tuple(f"{name}: weights unavailable" for name in skip_layers)
    for w in caught:
        if not str(w.message).startswith(expected):
            warnings.warn_explicit(w.message, w.category, w.filename, w.lineno)


class _StageProgress:
    """Stage banners, notes, and an in-place progress bar for the
    compile console. Dependency-free by design (the wheel's console UX
    rides the core install): plain ANSI on a TTY, and on a non-TTY the
    bar is silent so logs and CI capture only banners and notes."""

    BAR = 24

    def __init__(self, out=None):
        self._out = sys.stdout if out is None else out
        self._tty = bool(getattr(self._out, "isatty", lambda: False)())
        self._live = False

    def banner(self, text: str) -> None:
        self._finish_live()
        print(f"── {text} " + "─" * max(4, 44 - len(text)), file=self._out)

    def note(self, text: str) -> None:
        self._finish_live()
        print(f"   {text}", file=self._out)

    def step(self, done: int, total: int, label: str) -> None:
        if not self._tty:
            return
        n = int(self.BAR * done / max(total, 1))
        line = f"   [{'#' * n}{'-' * (self.BAR - n)}] {done}/{total} {label}"
        end = "\n" if done >= total else ""
        print(f"\r\x1b[2K{line}", end=end, flush=True, file=self._out)
        self._live = done < total

    def _finish_live(self) -> None:
        if self._live:
            print(file=self._out)
            self._live = False


def _fmt_bytes(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.1f} MB"
    return f"{n / 1e3:.0f} KB"


def _cmd_compile(args: argparse.Namespace) -> int:
    import warnings

    from ankhdjet.backend.bundle import emit_design_bundle
    from ankhdjet.frontend.hf import load_weights

    skip = ("lm_head",)
    stages = 2 if args.no_rtl else 3
    prog = _StageProgress()
    print(f"☥ ankhdjet compile {args.model}")

    prog.banner(f"[1/{stages}] checkpoint")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model, _arch, _scales = load_weights(args.model, quantize=args.quantize)
    _replay_unexpected_warnings(caught, skip)
    prog.note(f"{len(model.layers)} layers, "
              f"{model.total_ternary_weights():,} ternary weights")

    seen = {"stage": None}

    def progress(stage, done, total, label):
        if stage != seen["stage"]:
            seen["stage"] = stage
            prog.banner(f"[2/{stages}] mask programs" if stage == "masks"
                        else f"[3/{stages}] rtl bundle")
        prog.step(done, total, label)

    res = emit_design_bundle(
        model, args.out,
        macro_rows=args.rows, macro_cols=args.cols,
        emit_rtl=not args.no_rtl,
        skip_layers=skip,
        progress=progress,
        jobs=args.jobs,
        pdk=args.pdk,
        harden=args.harden,
    )

    t = res["masks"]["totals"]
    prog.banner("done")
    prog.note(f"{t['weights']:,} weights in {t['macros']:,} macros "
              f"({args.rows}x{args.cols}, {_fmt_bytes(t['wmat_bytes'])} of "
              f"mask programs) -> {args.out}")
    for s in res["masks"].get("off_fabric", []):
        prog.note(f"off-fabric: {s['layer']} ({s['reason']})")
    if res["bundle"] is not None:
        b = res["bundle"]
        prog.note(f"rtl: {len(b['layers'])} grid tops + "
                  f"{len(b['library'])} library modules + sim views")
        ma = b["macro_abstracts"]
        prog.note(f"macros: {ma['name']} lef/lib/bb.v "
                  f"({ma['width_um']:.1f} x {ma['height_um']:.1f} um)")
        if "hardening" in b:
            prog.note(f"hardened view: {b['hardening']['chunk_count']:,} "
                      f"chunk macros (filelist_hard.f + "
                      f"macros/hardening_manifest.json)")
        prog.note(f"elaborate: iverilog -g2012 -f {args.out}/filelist.f")
    return 0


# Commands that forward their arguments verbatim to a module's main().
_PASSTHROUGH = {
    "estimate": ("ankhdjet.estimate.report",
                 "area + bracketed throughput report (all remaining args "
                 "pass through; try: ankhdjet estimate -- --list-pdks)"),
    "compare": ("ankhdjet.estimate.compare",
                "side-by-side area/throughput across the discovered PDK "
                "descriptors"),
    "fit": ("ankhdjet.estimate.fit",
            "largest canonical model shape that fits a die budget"),
    "verify": ("ankhdjet.backend.verify",
               "bit-exact audit of an emitted mask set against its "
               "checkpoint"),
}


def _cmd_pdk(args: argparse.Namespace) -> int:
    from ankhdjet.pdks import discover_packs, discover_pdks, validate_pack

    if args.action == "list":
        packs = discover_packs()
        if packs:
            print(f"{'pack':<12} {'version':>7}  {'tiers':<28} root")
            for name in sorted(packs):
                p = packs[name]
                tiers = ",".join(p.tiers) + (" [restricted]" if p.restricted
                                             else "")
                print(f"{name:<12} {p.version:>7}  {tiers:<28} {p.root}")
        names = sorted(discover_pdks())
        print(f"estimator descriptors: {', '.join(names)}")
        return 0

    if not args.name:
        print("pdk validate needs a pack name", file=sys.stderr)
        return 2
    issues = validate_pack(args.name)
    if issues:
        for i in issues:
            print(f"FAIL: {i}")
        return 1
    tiers = ", ".join(discover_packs()[args.name].tiers)
    print(f"{args.name}: conforms (manifest + tiers: {tiers})")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="ankhdjet",
        description="Compile ternary LLM checkpoints into mask-programmed silicon sources.",
    )
    try:
        v = version("ankhdjet")
    except PackageNotFoundError:
        v = "dev"
    ap.add_argument("--version", action="version", version=f"ankhdjet {v}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile",
                       help="checkpoint -> complete design bundle (masks + "
                            "RTL + sim views + macro abstracts)")
    c.add_argument("model", help="HuggingFace repo id (e.g. microsoft/bitnet-b1.58-2B-4T)")
    c.add_argument("-o", "--out", required=True, help="output directory for the mask set")
    c.add_argument("--rows", type=int, default=64, help="macro rows (bitline depth)")
    c.add_argument("--cols", type=int, default=256, help="macro columns")
    c.add_argument("--no-rtl", action="store_true",
                   help="mask programs only (skip the RTL + sim-view bundle)")
    c.add_argument("-j", "--jobs", type=int, default=None,
                   help="parallel emission processes (default: all cores; 1 = serial)")
    c.add_argument("--pdk", default="sky130",
                   help="PDK pack for the macro abstracts (default: sky130)")
    c.add_argument("--harden", action="store_true",
                   help="also emit the hardened view: per-chunk hard-macro "
                        "bindings + filelist_hard.f + hardening manifest")
    c.add_argument("--quantize", choices=["absmean"], default=None,
                   help="decode QAT master-weight checkpoints by applying "
                        "the b1.58 absmean transform at load (default: "
                        "refuse non-ternary storage)")

    p = sub.add_parser("pdk", help="list or validate PDK packs")
    p.add_argument("action", choices=["list", "validate"])
    p.add_argument("name", nargs="?", help="pack name (validate)")

    for pname, (_, help_text) in _PASSTHROUGH.items():
        sub.add_parser(pname, help=help_text, add_help=False)

    if argv and argv[0] in _PASSTHROUGH:
        from importlib import import_module
        rest = [a for a in argv[1:] if a != "--"]
        return import_module(_PASSTHROUGH[argv[0]][0]).main(rest)

    args = ap.parse_args(argv)
    if args.cmd == "compile":
        return _cmd_compile(args)
    if args.cmd == "pdk":
        return _cmd_pdk(args)
    ap.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
