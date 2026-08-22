# LumaFlow v1.0 (2026-08-07)
# Teste la fonction pure de correction géométrique combinée rotation + perspective libre à 4 coins
# (correct_geometry) : cas neutre, rotation seule, perspective seule, combinaison des deux,
# clampage/repli sur valeurs invalides, déterminisme, et compatibilité ascendante des recettes.

"""Pure-function tests for the Geometry addon's combined rotation + free-form perspective
correction processing_function (dynamic geometric correction rewrite, superseding the
rotation-only feature 040) -- no Qt, no engine.
"""
from __future__ import annotations

import numpy

from lumaflow.addons.builtin.geometry import ADDON_DESCRIPTION, FRAME_MARGIN, correct_geometry, resolve_zoom_values

_NEUTRAL_CORNERS = {
    "corner_tl_x": FRAME_MARGIN, "corner_tl_y": FRAME_MARGIN,
    "corner_tr_x": 1.0 - FRAME_MARGIN, "corner_tr_y": FRAME_MARGIN,
    "corner_br_x": 1.0 - FRAME_MARGIN, "corner_br_y": 1.0 - FRAME_MARGIN,
    "corner_bl_x": FRAME_MARGIN, "corner_bl_y": 1.0 - FRAME_MARGIN,
}


def _image(val: int = 100, size: int = 20) -> numpy.ndarray:
    return numpy.full((size, size, 3), val, dtype=numpy.uint8)


def _scaled_corners(k: float) -> dict[str, float]:
    """A frame scaled by factor k about the image center (still axis-aligned, no true skew) --
    produces a pure affine (not merely local) transform, a useful known case for correctness
    checks."""
    center = 0.5
    inward = center - k * (center - FRAME_MARGIN)
    outward = center + k * (center - FRAME_MARGIN)
    return {
        "corner_tl_x": inward, "corner_tl_y": inward,
        "corner_tr_x": outward, "corner_tr_y": inward,
        "corner_br_x": outward, "corner_br_y": outward,
        "corner_bl_x": inward, "corner_bl_y": outward,
    }


# --- Combined neutral fast path -----------------------------------------------------------

def test_neutral_angle_and_corners_is_bit_identical_to_input():
    image = _image()
    out = correct_geometry(image, {"rotation_angle": 0.0, **_NEUTRAL_CORNERS})
    assert numpy.array_equal(out, image)


def test_missing_params_default_to_neutral_identity():
    image = _image()
    out = correct_geometry(image, {})
    assert numpy.array_equal(out, image)


# --- Rotation-only path (mirrors feature 040's coverage) ----------------------------------

def test_rotation_only_produces_different_same_shape_output():
    image = _image()
    out = correct_geometry(image, {"rotation_angle": 20.0})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8
    assert not numpy.array_equal(out, image)


def test_rotation_boundary_angles_do_not_fall_back():
    image = _image()
    out_min = correct_geometry(image, {"rotation_angle": -45.0})
    out_max = correct_geometry(image, {"rotation_angle": 45.0})
    assert not numpy.array_equal(out_min, image)
    assert not numpy.array_equal(out_max, image)


def test_angle_non_numeric_or_out_of_range_falls_back_to_neutral():
    image = _image()
    assert numpy.array_equal(correct_geometry(image, {"rotation_angle": "nope"}), image)
    assert numpy.array_equal(correct_geometry(image, {"rotation_angle": 999.0}), image)
    assert numpy.array_equal(correct_geometry(image, {"rotation_angle": -999.0}), image)


# --- Perspective-only path -----------------------------------------------------------------

def test_perspective_only_produces_different_same_shape_output():
    image = _image()
    out = correct_geometry(image, {**_scaled_corners(0.6)})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8
    assert not numpy.array_equal(out, image)


def test_perspective_correction_relocates_a_known_source_point():
    # A bright marker sitting exactly at the default frame's top-left corner should reappear
    # (approximately, given BICUBIC blur) at the dragged destination for that corner -- the core
    # correctness property: the frame's distortion reproduces across the whole image.
    size = 200
    image = numpy.zeros((size, size, 3), dtype=numpy.uint8)
    marker_x = int(FRAME_MARGIN * size)
    marker_y = int(FRAME_MARGIN * size)
    image[marker_y - 1 : marker_y + 2, marker_x - 1 : marker_x + 2] = 255

    corners = _scaled_corners(0.8)  # kept well inside the frame so the expected region isn't
    # near/past the image edge, where slicing with a negative index would silently wrap around.
    out = correct_geometry(image, corners)

    expected_x = int(corners["corner_tl_x"] * size)
    expected_y = int(corners["corner_tl_y"] * size)
    region = out[
        max(0, expected_y - 4) : expected_y + 5,
        max(0, expected_x - 4) : expected_x + 5,
    ]
    assert region.max() > 150


def test_degenerate_collinear_quad_falls_back_to_identity_without_raising():
    image = _image()
    collinear = {
        "corner_tl_x": 0.2, "corner_tl_y": 0.2,
        "corner_tr_x": 0.8, "corner_tr_y": 0.2,
        "corner_br_x": 0.8, "corner_br_y": 0.2,
        "corner_bl_x": 0.2, "corner_bl_y": 0.2,
    }
    out = correct_geometry(image, collinear)
    assert out.shape == image.shape
    assert numpy.array_equal(out, image)


# --- Combined path ---------------------------------------------------------------------------

def test_combined_rotation_and_perspective_differs_from_either_alone():
    image = _image()
    corners = _scaled_corners(0.6)
    rotation_only = correct_geometry(image, {"rotation_angle": 15.0})
    perspective_only = correct_geometry(image, corners)
    combined = correct_geometry(image, {"rotation_angle": 15.0, **corners})
    assert not numpy.array_equal(combined, rotation_only)
    assert not numpy.array_equal(combined, perspective_only)


# --- Clamping / determinism / purity ----------------------------------------------------------

def test_non_numeric_corner_falls_back_to_its_own_default_per_key():
    image = _image()
    out = correct_geometry(image, {"corner_tl_x": "not-a-number"})
    assert numpy.array_equal(out, image)  # every other field still at its own neutral default


def test_out_of_range_corner_is_clamped_not_reset_to_default():
    assert resolve_zoom_values({"corner_tl_x": 999.0})["corner_tl_x"] == 1.5
    assert resolve_zoom_values({"corner_tl_x": -999.0})["corner_tl_x"] == -0.5


def test_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"rotation_angle": 12.5, **_scaled_corners(0.7)}
    out1 = correct_geometry(image, params)
    out2 = correct_geometry(image, params)
    assert numpy.array_equal(out1, out2)


def test_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    correct_geometry(image, {"rotation_angle": 20.0, **_scaled_corners(0.6)})
    assert numpy.array_equal(image, snapshot)


# --- Old-recipe backward compatibility ---------------------------------------------------------

def test_old_rotation_only_recipe_degrades_to_pure_rotation():
    image = _image()
    legacy = correct_geometry(image, {"rotation_angle": 20.0})
    explicit_neutral_corners = correct_geometry(image, {"rotation_angle": 20.0, **_NEUTRAL_CORNERS})
    assert numpy.array_equal(legacy, explicit_neutral_corners)


# --- resolve_zoom_values -----------------------------------------------------------------------

def test_resolve_zoom_values_reflects_committed_values_not_generic_defaults():
    params = {"rotation_angle": 10.0, "corner_tl_x": 0.3, "corner_tl_y": 0.25}
    values = resolve_zoom_values(params)
    assert values["rotation_angle"] == 10.0
    assert values["corner_tl_x"] == 0.3
    assert values["corner_tl_y"] == 0.25
    # Untouched corners still resolve to their own neutral default.
    assert values["corner_br_x"] == 1.0 - FRAME_MARGIN


def test_resolve_zoom_values_defaults_to_neutral_frame_when_no_override_present():
    assert resolve_zoom_values({}) == {"rotation_angle": 0.0, **_NEUTRAL_CORNERS}


# --- ADDON_DESCRIPTION shape --------------------------------------------------------------------

def test_addon_description_shape():
    assert ADDON_DESCRIPTION.identifier == "geometry_correction"
    assert ADDON_DESCRIPTION.category == "geometry"
    assert len(ADDON_DESCRIPTION.thumbnail_presets) == 1
    assert ADDON_DESCRIPTION.thumbnail_presets[0].identifier == "neutral"
    assert ADDON_DESCRIPTION.thumbnail_presets[0].neutral is True
    assert len(ADDON_DESCRIPTION.parameter_descriptions) == 9
    identifiers = {p.identifier for p in ADDON_DESCRIPTION.parameter_descriptions}
    assert identifiers == {
        "rotation_angle",
        "corner_tl_x", "corner_tl_y", "corner_tr_x", "corner_tr_y",
        "corner_br_x", "corner_br_y", "corner_bl_x", "corner_bl_y",
    }
    assert all(p.zoom_only for p in ADDON_DESCRIPTION.parameter_descriptions)
    angle_param = next(p for p in ADDON_DESCRIPTION.parameter_descriptions if p.identifier == "rotation_angle")
    assert angle_param.constraints.minimum == -45.0
    assert angle_param.constraints.maximum == 45.0
    corner_param = next(p for p in ADDON_DESCRIPTION.parameter_descriptions if p.identifier == "corner_tl_x")
    assert corner_param.constraints.minimum == -0.5
    assert corner_param.constraints.maximum == 1.5
    assert ADDON_DESCRIPTION.overlay_descriptions == ()
    assert ADDON_DESCRIPTION.resolve_zoom_values is resolve_zoom_values
