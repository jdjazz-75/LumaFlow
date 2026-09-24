# LumaFlow v1.1 (2026-09-24)
# Teste les briques pures du moteur d'inpainting (feature 100) : le pilote (engine.py) -- dilatation,
# push-pull, et l'API publique inpaint_regions de bout en bout (déterminisme, non-mutation, pixels
# hors zone inchangés) -- avec `lama_backend.run` stubbé par défaut (voir conftest.py), donc ces
# tests couvrent le CADRAGE/COMPOSITE, pas la qualité du remplissage LaMa réel (tests/test_lama_backend.py
# `@pytest.mark.model` pour ça). Les anciens tests spécifiques aux noyaux PatchMatch (kernels.py :
# patch_cost/propagate/vote/jump_steps) ont été retirés avec ce module, retiré au pivot LaMa
# (specs/100-addon-object-removal-v1/research.md R3).

"""Pure-function tests for `lumaflow.addons.inpainting` (feature 100) -- no addon, no pipeline."""
from __future__ import annotations

import numpy

from lumaflow.addons.inpainting import inpaint_regions
from lumaflow.addons.inpainting import engine


def _textured_image(height: int, width: int, seed: int = 0) -> numpy.ndarray:
    rng = numpy.random.default_rng(seed)
    base = rng.normal(140, 25, size=(height, width, 3))
    gradient = numpy.linspace(-15, 15, width)[None, :, None]
    return numpy.clip(base + gradient, 0, 255).astype(numpy.uint8)


def _square_zone(cx: float, cy: float, half: float) -> list[tuple[float, float]]:
    return [(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)]


def _square_zone_px(cx_px: float, cy_px: float, half_px: float, width: int, height: int) -> list[tuple[float, float]]:
    """Like `_square_zone`, but `half_px` is a PIXEL radius converted separately for x (/width) and
    y (/height) -- required on a non-square image, where a single fractional half-width would cover
    a different pixel extent on each axis."""
    return [
        ((cx_px - half_px) / width, (cy_px - half_px) / height),
        ((cx_px + half_px) / width, (cy_px - half_px) / height),
        ((cx_px + half_px) / width, (cy_px + half_px) / height),
        ((cx_px - half_px) / width, (cy_px + half_px) / height),
    ]


# ---------------------------------------------------------------------------
# engine.py -- dilation, push-pull, full driver
# ---------------------------------------------------------------------------


def test_dilate_bool_grows_by_exactly_radius_on_a_single_pixel():
    mask = numpy.zeros((21, 21), dtype=bool)
    mask[10, 10] = True
    dilated = engine._dilate_bool(mask, 3)
    ys, xs = numpy.nonzero(dilated)
    assert ys.min() == 7 and ys.max() == 13
    assert xs.min() == 7 and xs.max() == 13
    assert dilated.sum() == 7 * 7  # square structuring element


def test_dilate_bool_radius_zero_is_identity():
    rng = numpy.random.default_rng(10)
    mask = rng.random((15, 15)) > 0.5
    assert numpy.array_equal(engine._dilate_bool(mask, 0), mask)


def test_push_pull_preserves_known_pixels_exactly():
    image = _textured_image(24, 24, seed=11).astype(numpy.float32)
    hole = numpy.zeros((24, 24), dtype=bool)
    hole[9:15, 9:15] = True
    filled = engine._push_pull_fill(image, hole)
    assert numpy.array_equal(filled[~hole], image[~hole])


def test_push_pull_leaves_no_hole_and_stays_in_plausible_range():
    image = _textured_image(24, 24, seed=12).astype(numpy.float32)
    hole = numpy.zeros((24, 24), dtype=bool)
    hole[9:15, 9:15] = True
    filled = engine._push_pull_fill(image, hole)
    assert numpy.all(numpy.isfinite(filled))
    assert filled[hole].min() >= 0.0 - 1e-3
    assert filled[hole].max() <= 255.0 + 1e-3


def test_push_pull_whole_roi_hole_falls_back_to_flat_grey():
    image = _textured_image(10, 10, seed=13).astype(numpy.float32)
    hole = numpy.ones((10, 10), dtype=bool)
    filled = engine._push_pull_fill(image, hole)
    assert numpy.all(filled == 128.0)


# ---------------------------------------------------------------------------
# inpaint_regions -- the public entry point
# ---------------------------------------------------------------------------


def test_inpaint_regions_no_zones_returns_the_same_object():
    image = _textured_image(20, 20)
    assert inpaint_regions(image, [], dilation_pct=0.5, feather_pct=0.3, variant=0) is image


def test_inpaint_regions_never_mutates_the_input():
    image = _textured_image(60, 80, seed=14)
    before = image.copy()
    inpaint_regions(image, [_square_zone(0.5, 0.5, 0.1)], dilation_pct=0.5, feather_pct=0.3, variant=0)
    assert numpy.array_equal(image, before)


def test_inpaint_regions_removes_a_distinctly_colored_object():
    image = _textured_image(120, 160, seed=15)
    cy, cx, half = 60, 80, 18
    yy, xx = numpy.mgrid[0:120, 0:160]
    disc = (yy - cy) ** 2 + (xx - cx) ** 2 <= half * half
    image = image.copy()
    image[disc] = (255, 0, 255)
    zone = _square_zone_px(cx, cy, half + 4, width=160, height=120)
    out = inpaint_regions(image, [zone], dilation_pct=0.5, feather_pct=0.3, variant=0)
    inside = out[disc].astype(numpy.float32)
    distance = numpy.sqrt(((inside - numpy.array([255.0, 0.0, 255.0])) ** 2).sum(axis=1))
    assert distance.min() > 60.0


def test_inpaint_regions_is_deterministic_per_variant():
    image = _textured_image(60, 80, seed=16)
    zone = _square_zone(0.5, 0.5, 0.15)
    a = inpaint_regions(image, [zone], dilation_pct=0.5, feather_pct=0.3, variant=0)
    b = inpaint_regions(image, [zone], dilation_pct=0.5, feather_pct=0.3, variant=0)
    assert numpy.array_equal(a, b)


def test_inpaint_regions_different_variant_changes_only_inside():
    image = _textured_image(80, 100, seed=17)
    zone = _square_zone(0.5, 0.5, 0.2)
    a = inpaint_regions(image, [zone], dilation_pct=0.5, feather_pct=0.3, variant=0)
    b = inpaint_regions(image, [zone], dilation_pct=0.5, feather_pct=0.3, variant=1)
    assert not numpy.array_equal(a, b)
    far_outside = numpy.ones(a.shape[:2], dtype=bool)
    far_outside[10:70, 10:90] = False  # generous margin around the zone
    assert numpy.array_equal(a[far_outside], image[far_outside])
    assert numpy.array_equal(b[far_outside], image[far_outside])


def test_inpaint_regions_pixels_far_outside_are_bit_identical():
    image = _textured_image(100, 120, seed=18)
    zone = _square_zone(0.3, 0.3, 0.08)
    out = inpaint_regions(image, [zone], dilation_pct=0.5, feather_pct=0.3, variant=0)
    far = numpy.ones(image.shape[:2], dtype=bool)
    far[0:60, 0:60] = False
    assert numpy.array_equal(out[far], image[far])


def test_inpaint_regions_two_far_apart_zones_both_removed():
    image = _textured_image(120, 200, seed=19)
    left = _square_zone_px(30, 60, 14, width=200, height=120)
    right = _square_zone_px(170, 60, 14, width=200, height=120)
    image = image.copy()
    yy, xx = numpy.mgrid[0:120, 0:200]
    left_disc = (yy - 60) ** 2 + (xx - 30) ** 2 <= 10 * 10
    right_disc = (yy - 60) ** 2 + (xx - 170) ** 2 <= 10 * 10
    image[left_disc] = (0, 255, 255)
    image[right_disc] = (255, 255, 0)
    out = inpaint_regions(image, [left, right], dilation_pct=0.5, feather_pct=0.3, variant=0)
    cyan_dist = numpy.sqrt(((out[left_disc].astype(numpy.float32) - numpy.array([0.0, 255.0, 255.0])) ** 2).sum(axis=1))
    yellow_dist = numpy.sqrt(((out[right_disc].astype(numpy.float32) - numpy.array([255.0, 255.0, 0.0])) ** 2).sum(axis=1))
    assert cyan_dist.min() > 60.0
    assert yellow_dist.min() > 60.0


def test_inpaint_regions_overlapping_zones_do_not_crash():
    image = _textured_image(80, 80, seed=20)
    zone_a = _square_zone(0.45, 0.5, 0.15)
    zone_b = _square_zone(0.55, 0.5, 0.15)
    out = inpaint_regions(image, [zone_a, zone_b], dilation_pct=0.5, feather_pct=0.3, variant=0)
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_inpaint_regions_degenerate_polygon_does_not_crash():
    """A collinear (zero-mathematical-area) polygon may still rasterize a thin line of pixels
    (PIL's scanline fill) -- the requirement is "does not crash", not "exactly no-op"."""
    image = _textured_image(40, 40, seed=21)
    collinear = [(0.2, 0.2), (0.5, 0.2), (0.8, 0.2)]  # zero area
    out = inpaint_regions(image, [collinear], dilation_pct=0.5, feather_pct=0.3, variant=0)
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8
    # Far from the degenerate line, nothing should be touched at all.
    assert numpy.array_equal(out[30:, :], image[30:, :])


def test_inpaint_regions_zone_touching_border_does_not_crash():
    image = _textured_image(50, 50, seed=22)
    zone = [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)]
    out = inpaint_regions(image, [zone], dilation_pct=0.5, feather_pct=0.3, variant=0)
    assert out.shape == image.shape


def test_inpaint_regions_whole_image_zone_falls_back_without_crashing():
    image = _textured_image(60, 60, seed=23)
    zone = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    out = inpaint_regions(image, [zone], dilation_pct=0.5, feather_pct=0.3, variant=0)
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8
    assert numpy.all(numpy.isfinite(out.astype(numpy.float32)))


def test_inpaint_regions_resolution_independent_geometry():
    """The same fractional zone on a photo and on a half-resolution copy of it should remove the
    same relative object in both -- a loose, structural check (working-resolution preview vs
    full-resolution render must both actually erase the target, even if fine texture differs)."""
    big = _textured_image(160, 200, seed=24)
    cy, cx, half = 80, 100, 20
    yy, xx = numpy.mgrid[0:160, 0:200]
    disc = (yy - cy) ** 2 + (xx - cx) ** 2 <= half * half
    big = big.copy()
    big[disc] = (255, 0, 255)
    small = numpy.asarray(
        __import__("PIL.Image", fromlist=["Image"]).fromarray(big).resize((100, 80))
    )
    zone = _square_zone_px(cx, cy, half + 4, width=200, height=160)

    out_big = inpaint_regions(big, [zone], dilation_pct=0.5, feather_pct=0.3, variant=0)
    out_small = inpaint_regions(small, [zone], dilation_pct=0.5, feather_pct=0.3, variant=0)

    small_disc = numpy.asarray(
        __import__("PIL.Image", fromlist=["Image"]).fromarray((disc.astype(numpy.uint8) * 255)).resize((100, 80))
    ) > 127
    big_dist = numpy.sqrt(((out_big[disc].astype(numpy.float32) - numpy.array([255.0, 0.0, 255.0])) ** 2).sum(axis=1))
    small_dist = numpy.sqrt(
        ((out_small[small_disc].astype(numpy.float32) - numpy.array([255.0, 0.0, 255.0])) ** 2).sum(axis=1)
    )
    assert big_dist.min() > 60.0
    assert small_dist.min() > 60.0
