"""Generate sign-off ECO paint patches from a KLayout DRC report.

Reads the flow's drc.klayout.lyrdb, takes the same-net notch categories
(min-width violations: the marker spans the notch between edges of ONE
polygon), and emits a Magic `box ...; paint <layer>` line per marker,
expanded to a small fill that closes the notch. Spacing-class markers
(m*.2) are between different nets and are NOT fillable -- they are
listed as comments for manual action.

Usage: uv run tools/gen_drc_eco.py <drc.klayout.lyrdb> > patches.tcl
"""
import re
import sys

FILL = {"m3.1": "metal3", "m1.1": "metal1", "m2.1": "metal2", "m4.1": "metal4"}
GROW = 0.07   # grow the marker bbox so the painted fill fully closes the notch

t = open(sys.argv[1]).read()
items = re.findall(r"<item>(.*?)</item>", t, re.S)
n = 0
skipped = {}
for it in items:
    c = re.search(r"<category>'([^']+)'</category>", it)
    v = re.search(r"<value>([^<]+)</value>", it)
    if not (c and v):
        continue
    cat = c.group(1)
    pts = [(float(a), float(b)) for a, b in re.findall(r"\(([-\d.]+),([-\d.]+)", v.group(1))]
    if not pts:
        continue
    x0 = min(p[0] for p in pts); x1 = max(p[0] for p in pts)
    y0 = min(p[1] for p in pts); y1 = max(p[1] for p in pts)
    if cat in FILL:
        def g(z): return round(round((z) / 0.005) * 0.005, 3)
        print(f"box {g(x0-GROW)}um {g(y0-GROW)}um {g(x1+GROW)}um {g(y1+GROW)}um ;# E{n:03d} {cat}")
        print(f"paint {FILL[cat]}")
        n += 1
    else:
        skipped[cat] = skipped.get(cat, 0) + 1
print(f"# generated {n} fills; skipped (not fillable): {skipped}", file=sys.stderr)
