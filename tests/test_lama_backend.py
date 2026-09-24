# LumaFlow v1.0 (2026-09-24)
# Teste `lama_backend.py` (feature 100, pivot LaMa -- research.md R3) : les helpers purs
# (arrondi au multiple, repli symétrique, redimensionnement au plus grand côté) sans réseau ni
# modèle, plus UN test `@pytest.mark.model` de bout en bout avec la vraie inférence (skippé par
# défaut -- voir conftest.py, `pytest -m model` pour l'exécuter explicitement).

from __future__ import annotations

import numpy
import pytest
from PIL import Image as PILImage

from lumaflow.addons.inpainting import lama_backend


def test_ceil_modulo_already_aligned_is_identity():
    assert lama_backend._ceil_modulo(16, 8) == 16


def test_ceil_modulo_rounds_up():
    assert lama_backend._ceil_modulo(17, 8) == 24
    assert lama_backend._ceil_modulo(1, 8) == 8


def test_pad_to_modulo_grows_to_the_next_multiple():
    array = numpy.zeros((10, 13, 3), dtype=numpy.uint8)
    padded = lama_backend._pad_to_modulo(array, 8)
    assert padded.shape == (16, 16, 3)


def test_pad_to_modulo_preserves_the_original_corner():
    rng = numpy.random.default_rng(1)
    array = rng.integers(0, 255, size=(10, 13, 3), dtype=numpy.uint8)
    padded = lama_backend._pad_to_modulo(array, 8)
    assert numpy.array_equal(padded[:10, :13], array)


def test_pad_to_modulo_works_on_a_2d_mask():
    mask = numpy.zeros((9, 9), dtype=bool)
    padded = lama_backend._pad_to_modulo(mask, 8)
    assert padded.shape == (16, 16)


def test_resize_long_edge_no_op_when_already_under_the_cap():
    array = numpy.zeros((100, 150, 3), dtype=numpy.uint8)
    resized = lama_backend._resize_long_edge(array, 200, PILImage.BICUBIC)
    assert resized.shape == array.shape


def test_resize_long_edge_downscales_preserving_aspect_ratio():
    array = numpy.zeros((300, 600, 3), dtype=numpy.uint8)
    resized = lama_backend._resize_long_edge(array, 150, PILImage.BICUBIC)
    assert max(resized.shape[:2]) == 150
    assert resized.shape[0] / resized.shape[1] == pytest.approx(300 / 600, rel=1e-2)


def test_resize_long_edge_handles_a_2d_mask_with_nearest():
    mask = numpy.zeros((300, 600), dtype=numpy.uint8)
    mask[100:200, 100:200] = 255
    resized = lama_backend._resize_long_edge(mask, 150, PILImage.NEAREST)
    assert resized.ndim == 2
    assert max(resized.shape) == 150


# ---------------------------------------------------------------------------
# Real inference -- requires network (first run) + torch running the actual model.
# ---------------------------------------------------------------------------


@pytest.mark.model
def test_run_fills_the_hole_and_leaves_a_sane_output_shape():
    rng = numpy.random.default_rng(2)
    roi_image = rng.normal(140, 25, size=(96, 128, 3)).clip(0, 255).astype(numpy.float32)
    hole = numpy.zeros((96, 128), dtype=bool)
    hole[30:60, 40:80] = True

    result = lama_backend.run(roi_image, hole, target_long_edge=256)

    assert result.shape == roi_image.shape
    assert result.dtype == numpy.float32
    assert numpy.all(numpy.isfinite(result))
    assert result.min() >= 0.0 - 1e-3
    assert result.max() <= 255.0 + 1e-3


@pytest.mark.model
def test_run_is_deterministic_for_the_same_input():
    rng = numpy.random.default_rng(3)
    roi_image = rng.normal(140, 25, size=(64, 64, 3)).clip(0, 255).astype(numpy.float32)
    hole = numpy.zeros((64, 64), dtype=bool)
    hole[20:40, 20:40] = True

    a = lama_backend.run(roi_image, hole, target_long_edge=128)
    b = lama_backend.run(roi_image, hole, target_long_edge=128)
    assert numpy.array_equal(a, b)
