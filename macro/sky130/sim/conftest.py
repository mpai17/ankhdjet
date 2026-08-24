"""Common paths for the macro-level regression suite."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
MACRO_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = MACRO_DIR / "build"
GEN_MACRO = MACRO_DIR / "gen_anchor_abstracts.py"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: tests that take minutes to hours (full SPICE sweeps)"
    )
