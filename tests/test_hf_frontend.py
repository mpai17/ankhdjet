"""The ternary decode ladder at the frontend boundary: packed uint8,
ternary-valued float, all-zero, and the refusals (asymmetric,
many-valued), plus the absmean transform for QAT master weights.
Pure numpy; no torch, no network."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ankhdjet.frontend.hf import (
    absmean_quantize, decode_ternary, is_group_ternary,
    unpack_ternary_uint8,
)

pytestmark = pytest.mark.package


def _pack(src: np.ndarray) -> np.ndarray:
    """Reference packer for the HF lane convention (inverse of
    unpack_ternary_uint8): lane i holds contiguous block i of axis 0."""
    n4 = src.shape[0]
    assert n4 % 4 == 0
    n = n4 // 4
    enc = (src + 1).astype(np.uint8)
    out = np.zeros((n,) + src.shape[1:], dtype=np.uint8)
    for lane in range(4):
        out |= enc[lane * n : (lane + 1) * n] << (2 * lane)
    return out


def test_packed_uint8_round_trip():
    rng = np.random.default_rng(7)
    src = rng.choice([-1, 0, 1], size=(64, 12)).astype(np.int8)
    decoded = decode_ternary(_pack(src))
    assert decoded is not None
    W, scale = decoded
    assert scale == 1.0
    assert np.array_equal(W, src)
    assert np.array_equal(unpack_ternary_uint8(_pack(src)), src)


def test_ternary_float_decodes_with_embedded_scale():
    rng = np.random.default_rng(8)
    tern = rng.choice([-1, 0, 1], size=(16, 8)).astype(np.float32)
    s = np.float32(0.0071)
    decoded = decode_ternary(tern * s)
    assert decoded is not None
    W, scale = decoded
    assert np.array_equal(W, tern.astype(np.int8))
    assert scale == pytest.approx(float(s))


def test_unit_valued_float_has_scale_one():
    W, scale = decode_ternary(np.array([[1.0, -1.0, 0.0]], dtype=np.float32))
    assert scale == 1.0
    assert np.array_equal(W, [[1, -1, 0]])


def test_all_zero_tensor_decodes():
    W, scale = decode_ternary(np.zeros((4, 4), dtype=np.float32))
    assert scale == 1.0
    assert not W.any()


def test_asymmetric_values_refused():
    assert decode_ternary(np.array([-0.5, 0.0, 0.3], dtype=np.float32)) is None


def test_many_valued_tensor_refused():
    assert decode_ternary(np.array([-0.5, -0.1, 0.0, 0.5], dtype=np.float32)) is None
    rng = np.random.default_rng(9)
    assert decode_ternary(rng.normal(size=(8, 8)).astype(np.float32)) is None


def test_absmean_matches_b158_transform():
    raw = np.array([[0.5, -0.4], [0.05, 0.0]], dtype=np.float32)
    W, scale = absmean_quantize(raw)
    assert scale == pytest.approx(float(np.abs(raw).mean()))
    assert np.array_equal(W, [[1, -1], [0, 0]])


def test_absmean_zero_tensor():
    W, scale = absmean_quantize(np.zeros((3, 3), dtype=np.float32))
    assert scale == 1.0 and not W.any()


def test_group_scaled_ternary_is_diagnosed_not_decoded():
    rng = np.random.default_rng(11)
    tern = rng.choice([-1, 0, 1], size=(16, 512)).astype(np.float32)
    scales = rng.uniform(0.01, 0.1, size=(16, 4))  # one scale per 128-col group
    raw = tern * np.repeat(scales, 128, axis=1).astype(np.float32)
    assert decode_ternary(raw) is None
    assert is_group_ternary(raw)


def test_gaussian_tensor_is_not_group_ternary():
    rng = np.random.default_rng(12)
    assert not is_group_ternary(rng.normal(size=(16, 512)).astype(np.float32))
