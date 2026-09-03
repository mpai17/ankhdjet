"""Functional regression of the layout-extracted macro through ngspice.

For every built mask program (a macro_array_pc_<N>x<M>_<program>.mag under
cell/sky130/macro/build), the capacitance-extracted layout is read row by row
at the controllers' timing and every bitline pair is checked against the
program's weight source, judged the way the digital tier samples it: the
measured register-input threshold of the standard-cell sampler per corner,
on the macro alone. A run fails on any line that reads wrong; lines inside
the margin band are reported in the log. The memh simulation views the
behavioral benches read are also checked against the same source, so the
RTL benches and the layout are proven to carry one program.

The default suite sweeps all rows at tt; ss and ff are marked slow. Design
review at the generic VDD/2 threshold, with a chip-level bitline load, or
at other timing goes through the CLI:

  python macro/sky130/sim/extracted_macro/runner.py --corner ss --tclk 20 --eval-cycles 1
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

from conftest import MACRO_DIR

sys.path.insert(0, str(MACRO_DIR / "sim" / "extracted_macro"))
import runner as xm  # noqa: E402


MACROS = xm.discover_macros()


@pytest.mark.parametrize("macro", MACROS)
def test_memh_views_match_weight_source(macro: str) -> None:
    n_rows, n_cols, program = xm.macro_shape(macro)
    W = xm.load_weights(program, n_rows, n_cols)
    wpos, wneg = xm.load_memh(macro, n_rows, n_cols)
    assert np.array_equal(wpos, W == 1), f"{macro}: wpos.memh differs from {program} source"
    assert np.array_equal(wneg, W == -1), f"{macro}: wneg.memh differs from {program} source"


def _sweep(macro: str, corner: str) -> None:
    res = xm.run_macro(macro, "all", corner, argv=["pytest", macro, corner],
                       vth=xm.DIGITAL_SAMPLER_VTH[corner], tag="digital")
    assert not res["errors"], f"{macro}@{corner}: ngspice errors:\n" + "\n".join(res["errors"])
    if res["hard"]:
        head = "\n".join(
            f"  r={f['r']} c={f['c']} {f['pol'].upper()} w={f['w']:+d} v={f['v']} "
            f"clearance={f['margin']} {f['kind']}" for f in res["hard"][:25])
        pytest.fail(f"{macro}@{corner}: {len(res['hard'])} of {res['n_lines']} lines read "
                    f"wrong ({res['counts']}); log {res['log']}\n{head}")


@pytest.mark.parametrize("macro", MACROS)
def test_extracted_read_sweep_tt(macro: str) -> None:
    _sweep(macro, "tt")


@pytest.mark.slow
@pytest.mark.parametrize("macro", MACROS)
def test_extracted_read_sweep_ss(macro: str) -> None:
    _sweep(macro, "ss")


@pytest.mark.slow
@pytest.mark.parametrize("macro", MACROS)
def test_extracted_read_sweep_ff(macro: str) -> None:
    _sweep(macro, "ff")
