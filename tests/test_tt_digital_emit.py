"""Bit-exact validation of ankhdjet.backend.tt_digital.

Emits the digital-tier tile (top + front-end binding), compiles it with
the library controller and the behavioral array macro, and runs the
tile's self-checking bench: a full matrix-vector multiply and all-row
raw reads must match the golden model computed from the same weight
memh the macro loads. Three configurations are pinned: the library
default (all 32 columns sensed, on-die activation store), the
subset-sensing path (16 of 32 columns), and the hardened tile's shape
(all 32 columns, streamed activations).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.backend.tt_digital import emit_tt_digital

CTRL_SV  = REPO_ROOT / "rtl" / "tt_digital" / "cirom_dig_ctrl.sv"
MACRO_SV = REPO_ROOT / "rtl" / "chip" / "sim" / "macro_array_beh.sv"
TB_SV    = REPO_ROOT / "rtl" / "tt_digital" / "sim" / "tb_tt_um_digital.sv"
MEMH     = REPO_ROOT / "macro" / "sky130" / "abstracts" / "macro_array_pc_64x32_checker"


def _run_config(tmp_path: Path, label: str, extra_defines: list[str], **emit_kw) -> None:
    emitted = emit_tt_digital(tmp_path / label, weights="checker", **emit_kw)
    assert emitted["top"].exists() and emitted["afe"].exists()

    vvp = tmp_path / label / "tile.vvp"
    compile_cmd = [
        "iverilog", "-g2012",
        f"-DANKHDJET_ARRAY_MODULE={emitted['macro_module']}",
        f"-DANKHDJET_WEIGHTS_MEMH_BASE=\"{MEMH}\"",
        *extra_defines,
        "-o", str(vvp),
        str(emitted["top"]), str(emitted["afe"]),
        str(CTRL_SV), str(MACRO_SV), str(TB_SV),
    ]
    r = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"[{label}] iverilog failed:\n{r.stderr}"

    r = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, f"[{label}] vvp failed:\n{r.stderr}"
    assert "TB PASS" in r.stdout, f"[{label}] bench did not pass:\n{r.stdout[-2000:]}"


def test_tt_digital_emit(tmp_path: Path) -> None:
    _run_config(tmp_path, "default32_stored", [])
    _run_config(tmp_path, "subset16_stored",
                ["-DANKHDJET_TB_NCOLS=16"], n_cols=16)
    _run_config(
        tmp_path, "hardened32_streamed",
        ["-DANKHDJET_STREAM_ACTS", "-DANKHDJET_TB_PASSES=8"],
        n_cols=32, n_acc=4, store_acts=0,
    )


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_tt_digital_emit(Path(d))
    print("[ok] emitted digital tile is bit-exact through the tile bench "
          "(default 32-col stored + 16-col subset + hardened 32-col streamed)")
