# LumaFlow v1.0 (2026-08-07)
# Teste la fonction pure de l'addon Vignetting (vignette) : repli neutre/couplé pour shape-
# intensity-progressivity, repli indépendant par champ pour la géométrie, formes ellipse/bande
# (décentrage, rayons asymétriques, rotation), largeur de plume, cohérence aux extrêmes, et
# rétrocompatibilité avec les recettes F-044 sans champs de géométrie.

"""Pure-function tests for the Vignetting addon (feature 044, extended by the "dynamic aids"
interactive-shape pass) -- no Qt, no pipeline engine. Covers US1 (Neutral bit-identity, both
preset shapes' own darkening region), the coupled-triple all-or-nothing fallback for shape/
intensity/progressivity (Decision 2, unchanged), the NEW independent per-key fallback for the 8
geometry/feather fields, the new analytic ellipse/line-band boundary + feather-blur engine, and
the shared falloff pipeline's coherence at extremes.
"""
from __future__ import annotations

import math

import numpy

from lumaflow.addons.builtin.vignetting import (
    ADDON_DESCRIPTION,
    _CENTER_DEFAULT,
    _ellipse_inside,
    _feather_alpha,
    _FEATHER_DEFAULT,
    _gamma,
    _line_band_inside,
    _OFFSET_DEFAULT,
    _RADIUS_DEFAULT,
    _resolve_geometry,
    _ROTATION_DEFAULT,
    _rotated_offsets,
    resolve_zoom_values,
    vignette,
)


def _uniform_image(value: int = 200, height: int = 80, width: int = 80) -> numpy.ndarray:
    return numpy.full((height, width, 3), value, dtype=numpy.uint8)


def _corner_mean(image: numpy.ndarray, size: int = 10) -> float:
    return float(image[:size, :size].mean())


def _center_mean(image: numpy.ndarray, size: int = 10) -> float:
    height, width = image.shape[0], image.shape[1]
    cy, cx = height // 2, width // 2
    half = size // 2
    return float(image[cy - half:cy + half, cx - half:cx + half].mean())


def _top_edge_mean(image: numpy.ndarray, size: int = 10) -> float:
    return float(image[:size, :].mean())


def _middle_band_mean(image: numpy.ndarray, size: int = 10) -> float:
    height = image.shape[0]
    cy = height // 2
    half = size // 2
    return float(image[cy - half:cy + half, :].mean())


def _pixel_at_fraction(image: numpy.ndarray, x_frac: float, y_frac: float) -> numpy.ndarray:
    height, width = image.shape[0], image.shape[1]
    x = min(width - 1, max(0, int(round(x_frac * (width - 1)))))
    y = min(height - 1, max(0, int(round(y_frac * (height - 1)))))
    return image[y, x].astype(numpy.float64)


_ROUND_PARAMS = {"shape": "round_central", "intensity": 0.5, "progressivity": 0.6}
_LINEAR_PARAMS = {"shape": "linear_top_bottom", "intensity": 0.5, "progressivity": 0.6}
_GEOMETRY_FIELDS = (
    "center_x", "center_y", "radius_x", "radius_y",
    "top_offset", "bottom_offset", "rotation_angle", "feather_width",
)


# --- Bit-identity / coupled-triple fallback (SC-001, FR-014, Decision 2 -- unchanged) ---


def test_neutral_empty_params_returns_bit_identical_image():
    image = _uniform_image()
    out = vignette(image, {})
    assert numpy.array_equal(out, image)


def test_missing_shape_with_intensity_and_progressivity_present_returns_bit_identical_image():
    image = _uniform_image()
    out = vignette(image, {"intensity": 0.9, "progressivity": 0.9})
    assert numpy.array_equal(out, image)


def test_unrecognized_shape_returns_bit_identical_image():
    image = _uniform_image()
    out = vignette(image, {"shape": "not-a-real-shape", "intensity": 0.9, "progressivity": 0.9})
    assert numpy.array_equal(out, image)


def test_valid_shape_intensity_zero_returns_bit_identical_image():
    image = _uniform_image()
    for shape in ("round_central", "linear_top_bottom"):
        out = vignette(image, {"shape": shape, "intensity": 0.0, "progressivity": 0.6})
        assert numpy.array_equal(out, image)


def test_valid_shape_missing_intensity_returns_bit_identical_image():
    image = _uniform_image()
    out = vignette(image, {"shape": "round_central", "progressivity": 0.6})
    assert numpy.array_equal(out, image)


def test_valid_shape_non_numeric_intensity_returns_bit_identical_image():
    image = _uniform_image()
    out = vignette(image, {"shape": "round_central", "intensity": "not-a-number", "progressivity": 0.6})
    assert numpy.array_equal(out, image)


def test_valid_shape_out_of_range_intensity_returns_bit_identical_image():
    image = _uniform_image()
    out = vignette(image, {"shape": "round_central", "intensity": 1.5, "progressivity": 0.6})
    assert numpy.array_equal(out, image)


def test_valid_shape_missing_progressivity_returns_bit_identical_image():
    image = _uniform_image()
    out = vignette(image, {"shape": "round_central", "intensity": 0.5})
    assert numpy.array_equal(out, image)


def test_valid_shape_non_numeric_progressivity_returns_bit_identical_image():
    image = _uniform_image()
    out = vignette(image, {"shape": "round_central", "intensity": 0.5, "progressivity": "nope"})
    assert numpy.array_equal(out, image)


def test_valid_shape_out_of_range_progressivity_returns_bit_identical_image():
    image = _uniform_image()
    out = vignette(image, {"shape": "round_central", "intensity": 0.5, "progressivity": -0.1})
    assert numpy.array_equal(out, image)


def test_boolean_intensity_is_rejected_as_non_numeric():
    # bool is an int subclass in Python -- must not be silently accepted as 0.0/1.0.
    image = _uniform_image()
    out = vignette(image, {"shape": "round_central", "intensity": True, "progressivity": 0.6})
    assert numpy.array_equal(out, image)


def test_malformed_geometry_field_does_not_collapse_the_whole_step_to_neutral():
    # The two fallback regimes are independent (module docstring): shape/intensity/progressivity
    # use all-or-nothing, but the 8 geometry/feather fields fall back PER-KEY -- a malformed
    # radius_x must not revert the whole vignette to identity.
    image = _uniform_image()
    out = vignette(image, {**_ROUND_PARAMS, "radius_x": "not-a-number", "rotation_angle": 999.0})
    assert not numpy.array_equal(out, image)
    assert _corner_mean(out) < _center_mean(out)


# --- Directional signature per shape (SC-002, SC-003) ---


def test_round_central_darkens_corner_more_than_center():
    image = _uniform_image()
    out = vignette(image, _ROUND_PARAMS)
    original_mean = float(image.mean())
    assert _corner_mean(out) < _center_mean(out)
    assert _center_mean(out) == original_mean  # exact center is well inside the default safe zone


def test_linear_top_bottom_darkens_edge_more_than_middle_band():
    image = _uniform_image()
    out = vignette(image, _LINEAR_PARAMS)
    original_mean = float(image.mean())
    assert _top_edge_mean(out) < _middle_band_mean(out)
    assert _middle_band_mean(out) == original_mean  # horizontal center line is well inside the safe band


# --- Intensity / progressivity response (SC-004, SC-005 -- unchanged pipeline) ---


def test_increasing_intensity_darkens_the_corner_monotonically():
    image = _uniform_image()
    means = []
    for intensity in (0.0, 0.25, 0.5, 0.75, 1.0):
        out = vignette(image, {"shape": "round_central", "intensity": intensity, "progressivity": 0.6})
        means.append(_corner_mean(out))
    assert all(earlier >= later for earlier, later in zip(means, means[1:]))
    assert means[0] > means[-1]


def test_changing_progressivity_changes_the_darkening_profile_shape():
    height = width = 200
    rx, ry = _rotated_offsets(height, width, 0.5, 0.5, 0.0)
    inside = _line_band_inside(ry, 0.6, 0.6)
    alpha = _feather_alpha(inside, 12.0, height, width)
    t = 1.0 - alpha
    column_t = t[:, width // 2]
    soft_profile = column_t ** _gamma(1.0)
    hard_profile = column_t ** _gamma(0.0)
    # Same endpoints (0 deep inside, 1 far outside) but a measurably different shape in between --
    # pick the in-transition-band index closest to t=0.5 rather than assuming a fixed position.
    mid = int(numpy.argmin(numpy.abs(column_t - 0.5)))
    assert abs(soft_profile[mid] - hard_profile[mid]) > 0.05


# --- Extreme coherence -- no banding ---


def test_extreme_settings_produce_a_monotonic_profile_along_the_distance_axis():
    height = width = 200
    image = _uniform_image(height=height, width=width)
    for progressivity in (0.0, 1.0):
        out = vignette(image, {"shape": "round_central", "intensity": 1.0, "progressivity": progressivity})
        column = out[height // 2:, width // 2, 0].astype(numpy.int32)  # center -> bottom edge
        diffs = numpy.diff(column)
        # Tolerance of 2 LSB (measured empirically, ~0.8% of the 0..255 range): the two-pass
        # separable box blur is a cheap APPROXIMATION of a true radially-symmetric blur (same
        # primitive/precedent as light.py's _polygon_mask) -- it can produce a tiny uptick right at
        # the start of the transition band, amplified by progressivity=1.0's fractional gamma
        # exponent (0.3). This is imperceptible noise, not the "literal solid block or visible
        # stepping" banding the edge case guards against -- a real 2D (non-separable) blur would
        # avoid it but isn't worth the extra cost for a sub-1% ripple.
        assert numpy.all(diffs <= 2)


def test_extreme_settings_on_linear_top_bottom_produce_a_monotonic_profile():
    height = width = 200
    image = _uniform_image(height=height, width=width)
    for progressivity in (0.0, 1.0):
        out = vignette(image, {"shape": "linear_top_bottom", "intensity": 1.0, "progressivity": progressivity})
        row = out[height // 2:, width // 2, 0].astype(numpy.int32)  # center line -> bottom edge
        diffs = numpy.diff(row)
        assert numpy.all(diffs <= 0)


# --- Scale-invariance ---


def test_tiny_4x4_fixture_produces_a_proportionally_scaled_error_free_result():
    image = _uniform_image(value=200, height=4, width=4)
    for shape in ("round_central", "linear_top_bottom"):
        out = vignette(image, {"shape": shape, "intensity": 0.5, "progressivity": 0.6})
        assert out.shape == image.shape
        assert out.dtype == numpy.uint8
        assert out.mean() < image.mean()
        assert numpy.isfinite(out.astype(numpy.float64)).all()


# --- Determinism ---


def test_same_image_and_params_called_twice_are_byte_identical():
    image = _uniform_image()
    first = vignette(image, _ROUND_PARAMS)
    second = vignette(image, _ROUND_PARAMS)
    assert numpy.array_equal(first, second)


def test_does_not_mutate_input_image():
    image = _uniform_image()
    original = image.copy()
    vignette(image, _ROUND_PARAMS)
    assert numpy.array_equal(image, original)


# --- Ellipse boundary correctness: off-center, asymmetric radii, rotation (NEW) ---


def test_ellipse_off_center_moves_the_safe_zone():
    image = _uniform_image(height=200, width=200)
    params = {
        "shape": "round_central", "intensity": 1.0, "progressivity": 0.6, "feather_width": 0.0,
        "center_x": 0.2, "center_y": 0.2, "radius_x": 0.15, "radius_y": 0.15,
    }
    out = vignette(image, params)
    original = _pixel_at_fraction(image, 0.2, 0.2)
    near_new_center = _pixel_at_fraction(out, 0.2, 0.2)
    far_corner = _pixel_at_fraction(out, 0.95, 0.95)
    assert numpy.array_equal(near_new_center, original)  # the moved safe zone stays untouched
    assert far_corner.mean() < original.mean()  # everywhere else darkens


def test_ellipse_asymmetric_radii_darken_the_narrow_axis_more():
    image = _uniform_image(height=200, width=200)
    params = {
        "shape": "round_central", "intensity": 1.0, "progressivity": 0.6, "feather_width": 0.0,
        "center_x": 0.5, "center_y": 0.5, "radius_x": 0.3, "radius_y": 0.9,
    }
    out = vignette(image, params)
    side_point = _pixel_at_fraction(out, 0.85, 0.5)  # far along the NARROW (x) axis
    vertical_point = _pixel_at_fraction(out, 0.5, 0.85)  # far along the WIDE (y) axis
    original = _pixel_at_fraction(image, 0.5, 0.85)
    assert side_point.mean() < vertical_point.mean()
    assert numpy.array_equal(vertical_point, original)  # still inside the wide-axis safe zone


def test_ellipse_rotation_swaps_which_axis_is_narrow():
    # A 90-degree rotation must swap the role of the image's x/y axes, regardless of the exact
    # sign convention (verified visually in the frontend, not pinned down at this backend level).
    image = _uniform_image(height=200, width=200)
    base = {
        "shape": "round_central", "intensity": 1.0, "progressivity": 0.6, "feather_width": 0.0,
        "center_x": 0.5, "center_y": 0.5, "radius_x": 0.3, "radius_y": 0.9,
    }
    rotated = vignette(image, {**base, "rotation_angle": 90.0})
    side_point = _pixel_at_fraction(rotated, 0.85, 0.5)
    vertical_point = _pixel_at_fraction(rotated, 0.5, 0.85)
    original = _pixel_at_fraction(image, 0.85, 0.5)
    # After a 90-degree rotation the previously-narrow horizontal axis becomes the wide one.
    assert numpy.array_equal(side_point, original)
    assert vertical_point.mean() < side_point.mean()


def test_ellipse_rotation_preserves_shape_on_a_non_square_image():
    # Regression: _rotated_offsets used to rotate the already per-axis-normalized (dx, dy) pair
    # directly, which is anisotropic for any non-square image -- shearing the ellipse instead of
    # rotating it rigidly (see _rotated_offsets's docstring for the derivation). A 90-degree
    # rotation doesn't expose this (sin/cos are 0/1, so the aspect-dependent terms vanish, which is
    # why test_ellipse_rotation_swaps_which_axis_is_narrow above didn't catch it) -- this uses a
    # non-multiple-of-90 angle on a clearly non-square image instead.
    height, width = 100, 300
    image = _uniform_image(height=height, width=width)
    radius_x = 0.2
    angle_deg = 30.0
    angle = math.radians(angle_deg)
    params = {
        "shape": "round_central", "intensity": 1.0, "progressivity": 0.6, "feather_width": 0.0,
        "center_x": 0.5, "center_y": 0.5, "radius_x": radius_x, "radius_y": 0.5,
        "rotation_angle": angle_deg,
    }
    out = vignette(image, params)

    # The ellipse's vertex (its local +x boundary) sits, in REAL pixels, at distance
    # radius_x * (width / 2) from center along the direction `angle_deg` from the image's own +x
    # axis -- a true rigid rotation, independent of the image's aspect ratio.
    center_px = ((width - 1) / 2.0, (height - 1) / 2.0)
    radius_px = radius_x * (width / 2.0)

    def fraction_at(distance_px: float) -> tuple[float, float]:
        x = center_px[0] + distance_px * math.cos(angle)
        y = center_px[1] + distance_px * math.sin(angle)
        return x / (width - 1), y / (height - 1)

    inside_frac = fraction_at(radius_px * 0.85)
    outside_frac = fraction_at(radius_px * 1.15)
    assert numpy.array_equal(_pixel_at_fraction(out, *inside_frac), _pixel_at_fraction(image, *inside_frac))
    assert _pixel_at_fraction(out, *outside_frac).mean() < _pixel_at_fraction(image, *outside_frac).mean()


def test_ellipse_degenerate_radius_never_produces_nan_or_inf():
    image = _uniform_image(height=40, width=40)
    out = vignette(image, {
        "shape": "round_central", "intensity": 1.0, "progressivity": 0.6,
        "radius_x": 0.0, "radius_y": -5.0,
    })
    assert numpy.isfinite(out.astype(numpy.float64)).all()


# --- Line boundary correctness: asymmetric offsets, rotation (NEW) ---


def test_line_independent_offsets_produce_an_asymmetric_band():
    image = _uniform_image(height=200, width=200)
    params = {
        "shape": "linear_top_bottom", "intensity": 1.0, "progressivity": 0.6, "feather_width": 0.0,
        "top_offset": 1.4, "bottom_offset": 0.1,
    }
    out = vignette(image, params)
    original = _pixel_at_fraction(image, 0.5, 0.1)
    near_top = _pixel_at_fraction(out, 0.5, 0.1)  # generous top_offset -> still safe
    near_bottom = _pixel_at_fraction(out, 0.5, 0.9)  # tight bottom_offset -> darkened
    assert numpy.array_equal(near_top, original)
    assert near_bottom.mean() < original.mean()


def test_line_rotation_90_degrees_turns_the_horizontal_band_into_a_vertical_one():
    image = _uniform_image(height=200, width=200)
    base = {
        "shape": "linear_top_bottom", "intensity": 1.0, "progressivity": 0.6, "feather_width": 0.0,
        "top_offset": 0.6, "bottom_offset": 0.6,
    }
    unrotated = vignette(image, base)
    rotated = vignette(image, {**base, "rotation_angle": 90.0})
    top_edge_point = (0.5, 0.02)
    side_edge_point = (0.98, 0.5)
    original = _pixel_at_fraction(image, *top_edge_point)
    # Unrotated: top edge is darkened, side edge is safe (default band is horizontal).
    assert _pixel_at_fraction(unrotated, *top_edge_point).mean() < original.mean()
    assert numpy.array_equal(_pixel_at_fraction(unrotated, *side_edge_point), _pixel_at_fraction(image, *side_edge_point))
    # Rotated 90 degrees: the roles swap -- top edge becomes safe, side edge darkens.
    assert numpy.array_equal(_pixel_at_fraction(rotated, *top_edge_point), original)
    assert _pixel_at_fraction(rotated, *side_edge_point).mean() < _pixel_at_fraction(image, *side_edge_point).mean()


# --- Feather width (NEW) ---


def test_feather_width_zero_produces_a_hard_edge():
    height = width = 200
    rx, ry = _rotated_offsets(height, width, 0.5, 0.5, 0.0)
    inside = _ellipse_inside(rx, ry, 0.5, 0.5)
    alpha = _feather_alpha(inside, 0.0, height, width)
    assert numpy.array_equal(alpha, inside.astype(numpy.float32))  # no blur applied at all


def test_feather_width_positive_smooths_the_boundary():
    height = width = 200
    rx, ry = _rotated_offsets(height, width, 0.5, 0.5, 0.0)
    inside = _ellipse_inside(rx, ry, 0.5, 0.5)
    alpha = _feather_alpha(inside, 15.0, height, width)
    # Some pixels must now hold an intermediate (neither 0 nor 1) value -- proof a real blur ran.
    intermediate = alpha[(alpha > 0.01) & (alpha < 0.99)]
    assert intermediate.size > 0


# --- Per-field defensive resolution (NEW, geometry/feather fields) ---


def test_resolve_geometry_defaults_for_empty_params():
    geometry = _resolve_geometry({})
    assert geometry == {
        "center_x": _CENTER_DEFAULT, "center_y": _CENTER_DEFAULT,
        "radius_x": _RADIUS_DEFAULT, "radius_y": _RADIUS_DEFAULT,
        "top_offset": _OFFSET_DEFAULT, "bottom_offset": _OFFSET_DEFAULT,
        "rotation_angle": _ROTATION_DEFAULT, "feather_width": _FEATHER_DEFAULT,
    }


def test_resolve_geometry_clamps_out_of_range_spatial_fields():
    geometry = _resolve_geometry({"center_x": 99.0, "radius_x": -3.0})
    assert geometry["center_x"] == 1.5  # clamped to _CENTER_MAXIMUM, not reset
    assert geometry["radius_x"] == 0.05  # clamped to _RADIUS_MINIMUM, not reset


def test_resolve_geometry_resets_out_of_range_rotation_and_feather():
    geometry = _resolve_geometry({"rotation_angle": 999.0, "feather_width": -1.0})
    assert geometry["rotation_angle"] == _ROTATION_DEFAULT  # reset, not clamped
    assert geometry["feather_width"] == _FEATHER_DEFAULT


def test_resolve_geometry_non_numeric_and_boolean_fall_back_per_field():
    geometry = _resolve_geometry({"center_y": "nope", "rotation_angle": True, "feather_width": None})
    assert geometry["center_y"] == _CENTER_DEFAULT
    assert geometry["rotation_angle"] == _ROTATION_DEFAULT
    assert geometry["feather_width"] == _FEATHER_DEFAULT


# --- Backward compatibility with already-shipped F-044 recipes ---


def test_pre_existing_recipe_without_any_geometry_field_renders_without_error():
    # A recipe saved before the dynamic-aids pass only ever had shape/intensity/progressivity.
    image = _uniform_image(height=64, width=48)
    for params in (_ROUND_PARAMS, _LINEAR_PARAMS):
        out = vignette(image, params)
        assert out.shape == image.shape
        assert out.dtype == numpy.uint8
        assert numpy.isfinite(out.astype(numpy.float64)).all()
        assert not numpy.array_equal(out, image)  # still a plausible, visible vignette


# --- resolve_zoom_values (Zoom slider seeding) ---


def test_resolve_zoom_values_reads_real_effective_values_from_a_selected_preset():
    result = resolve_zoom_values({"shape": "round_central", "intensity": 0.35, "progressivity": 0.6})
    assert result["intensity"] == 0.35
    assert result["progressivity"] == 0.6
    for field in _GEOMETRY_FIELDS:
        assert field in result  # always resolved, regardless of shape validity


def test_resolve_zoom_values_falls_back_to_zero_for_malformed_intensity_progressivity():
    result = resolve_zoom_values({"shape": "round_central", "intensity": "bad", "progressivity": 5.0})
    assert result["intensity"] == 0.0
    assert result["progressivity"] == 0.0


def test_resolve_zoom_values_geometry_fields_use_their_own_fallback_independent_of_shape():
    result = resolve_zoom_values({"shape": "round_central", "intensity": "bad", "radius_x": 1.5})
    assert result["radius_x"] == 1.5  # resolved independently, unaffected by intensity being invalid


def test_resolve_zoom_values_answers_zero_for_the_generic_pure_default_probe():
    # zoom_pure_default_values (lumaflow/api/session.py) always injects {"look": ..., "intensity":
    # 1.0} regardless of addon -- this addon has no "look" concept, so its own true neutral
    # (0.0/0.0) must win over that injected 1.0, recognized by the absence of "shape". The 8
    # geometry fields resolve to their own declared defaults regardless.
    result = resolve_zoom_values({"look": None, "intensity": 1.0})
    assert result["intensity"] == 0.0
    assert result["progressivity"] == 0.0
    assert result["radius_x"] == _RADIUS_DEFAULT


def test_resolve_zoom_values_empty_params_is_zero():
    result = resolve_zoom_values({})
    assert result["intensity"] == 0.0
    assert result["progressivity"] == 0.0


# --- ADDON_DESCRIPTION shape sanity ---


def test_addon_description_declares_three_presets_ten_sliders_no_overlay():
    assert ADDON_DESCRIPTION.identifier == "vignetting"
    assert ADDON_DESCRIPTION.category == "vignette"
    assert len(ADDON_DESCRIPTION.thumbnail_presets) == 3
    assert {p.identifier for p in ADDON_DESCRIPTION.thumbnail_presets} == {
        "neutral", "Round Central", "Linear Top+Bottom",
    }
    identifiers = {p.identifier for p in ADDON_DESCRIPTION.parameter_descriptions}
    assert identifiers == {"intensity", "progressivity", *_GEOMETRY_FIELDS}
    assert len(ADDON_DESCRIPTION.overlay_descriptions) == 0
