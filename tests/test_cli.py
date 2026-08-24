"""CLI behavior at the pip envelope: the compile path reports expected
off-fabric placeholder warnings as summary output instead of alarms,
while any other warning is replayed untouched."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.cli import _StageProgress, _fmt_bytes, _replay_unexpected_warnings

pytestmark = pytest.mark.package


class _Tty(__import__("io").StringIO):
    def isatty(self):
        return True


def test_progress_bar_silent_off_tty():
    import io
    out = io.StringIO()
    p = _StageProgress(out)
    p.banner("[1/3] checkpoint")
    p.step(1, 4, "blk.0")
    p.note("a note")
    text = out.getvalue()
    assert "[1/3] checkpoint" in text and "a note" in text
    assert "blk.0" not in text


def test_progress_bar_on_tty_closes_completed_line():
    out = _Tty()
    p = _StageProgress(out)
    p.step(1, 2, "a")
    p.step(2, 2, "b")
    text = out.getvalue()
    assert "1/2 a" in text and "2/2 b" in text
    assert text.endswith("\n")


def test_help_lists_every_command(capsys):
    from ankhdjet.cli import main
    with pytest.raises(SystemExit) as e:
        main(["-h"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("compile", "pdk", "estimate", "compare", "fit", "verify"):
        assert cmd in out


@pytest.mark.parametrize("cmd", ["estimate", "compare", "fit", "verify"])
def test_passthrough_help_names_the_command(cmd, capsys):
    from ankhdjet.cli import main
    with pytest.raises(SystemExit) as e:
        main([cmd, "-h"])
    assert e.value.code == 0
    assert f"ankhdjet {cmd}" in capsys.readouterr().out


def test_fmt_bytes():
    assert _fmt_bytes(2_110_000_000) == "2.11 GB"
    assert _fmt_bytes(5_200_000) == "5.2 MB"
    assert _fmt_bytes(700) == "1 KB"


def _record(messages: list[str]):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for m in messages:
            warnings.warn(m, stacklevel=1)
    return caught


def test_expected_placeholder_warning_is_absorbed():
    caught = _record([
        "lm_head: weights unavailable (stored unpacked (bf16), not "
        "ternary); keeping 1x1 placeholder with scale=1.0",
    ])
    with warnings.catch_warnings(record=True) as replayed:
        warnings.simplefilter("always")
        _replay_unexpected_warnings(caught, ("lm_head",))
    assert replayed == []


def test_unexpected_warnings_are_replayed():
    caught = _record([
        "lm_head: weights unavailable (bf16); keeping 1x1 placeholder",
        "b3_q: weights unavailable (missing tensor); keeping 1x1 placeholder",
        "some unrelated condition",
    ])
    with warnings.catch_warnings(record=True) as replayed:
        warnings.simplefilter("always")
        _replay_unexpected_warnings(caught, ("lm_head",))
    texts = [str(w.message) for w in replayed]
    assert len(texts) == 2
    assert any(t.startswith("b3_q:") for t in texts)
    assert any(t == "some unrelated condition" for t in texts)
