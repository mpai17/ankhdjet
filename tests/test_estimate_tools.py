"""The estimator frontends at the pip envelope: the cross-PDK
comparison and the fit search run to completion on the bundled
descriptors with no checkpoint and no repository collateral."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.estimate.compare import main as compare_main
from ankhdjet.estimate.fit import main as fit_main

pytestmark = pytest.mark.package


def test_compare_runs_on_synthetic_demo(capsys):
    assert compare_main([]) == 0
    out = capsys.readouterr().out
    assert "sky130_v4" in out and "asap7" in out


def test_fit_runs_at_tiny_budget(capsys):
    assert fit_main(["--die-budget-mm2", "2"]) == 0
    out = capsys.readouterr().out
    assert "Die budget: 2.0 mm^2" in out
