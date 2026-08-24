"""Write a single SPICE deck for a cirom_array pattern to disk.

CLI:
  uv run gen_array_spice.py -N 64 -M 32 --pattern all_pos --corner tt \\
                             -o /tmp/array_64x32_all_pos_tt.sp

Patterns (from patterns.py):
  all_pos | all_neg | all_zero | checker | stripe_row | stripe_col
  random       -- "--pattern random --seed 7"
  col_hot      -- "--pattern col_hot --col 13"

Programmatic use:
  from deck import emit_array_deck
  from patterns import pattern_all_pos
  W, act = pattern_all_pos(64, 32)
  Path('out.sp').write_text(emit_array_deck(W, act, corner='tt'))
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deck import emit_array_deck
from patterns import (
    pattern_all_neg, pattern_all_pos, pattern_all_zero, pattern_checkerboard,
    pattern_random, pattern_stripe_col, pattern_stripe_row,
)


PATTERN_FNS = {
    "all_pos":    lambda N, M, **_: pattern_all_pos(N, M),
    "all_neg":    lambda N, M, **_: pattern_all_neg(N, M),
    "all_zero":   lambda N, M, **_: pattern_all_zero(N, M),
    "checker":    lambda N, M, **_: pattern_checkerboard(N, M),
    "stripe_row": lambda N, M, row=0, **_: pattern_stripe_row(N, M, hot_row=row),
    "stripe_col": lambda N, M, col=0, **_: pattern_stripe_col(N, M, hot_col=col),
    "random":     lambda N, M, seed=0, **_: pattern_random(N, M, seed),
    "col_hot":    lambda N, M, col=0, **_: pattern_stripe_col(N, M, hot_col=col),
}


def main() -> int:
    p = argparse.ArgumentParser(
        description="Generate one SPICE deck (.sp file) for a cirom_array pattern."
    )
    p.add_argument("-N", type=int, default=8, help="rows")
    p.add_argument("-M", type=int, default=4, help="columns")
    p.add_argument("--pattern", required=True, choices=sorted(PATTERN_FNS.keys()),
                   help="which weight pattern to encode")
    p.add_argument("--corner", default="tt", choices=["tt", "ss", "ff"])
    p.add_argument("--seed", type=int, default=0,
                   help="seed for --pattern random")
    p.add_argument("--row", type=int, default=0,
                   help="hot row index for --pattern stripe_row")
    p.add_argument("--col", type=int, default=0,
                   help="hot column index for --pattern stripe_col / col_hot")
    p.add_argument("--vdd", type=float, default=1.8)
    p.add_argument("--subcol-rows", type=int, default=64,
                   help="BL load capacitance models SUBCOL_ROWS sibling cells")
    p.add_argument("-o", "--output", required=True,
                   help="write the .sp deck to this path")
    args = p.parse_args()

    fn = PATTERN_FNS[args.pattern]
    W, act = fn(args.N, args.M, seed=args.seed, row=args.row, col=args.col)

    deck = emit_array_deck(
        W, act,
        corner=args.corner,
        vdd=args.vdd,
        subcol_rows=args.subcol_rows,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(deck)
    n_active = int(((W != 0) & act[:, None].astype(bool)).sum())
    print(f"wrote {out} ({len(deck)//1024} KB, {args.N}x{args.M}, "
          f"{args.corner}, pattern={args.pattern}, {n_active} active discharges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
