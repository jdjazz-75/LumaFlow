# LumaFlow v1.0 (2026-08-07)
# Teste la fonction pure de l'addon Color Splash (color_splash) : sélection de preset par teinte,
# fenêtre de dégradé (feather), désaturation de fond, seuil de saturation, plusieurs plages
# simultanées, repli sur valeurs malformées, et cohérence des utilitaires HSL internes.

"""Pure-function tests for the Color Splash addon's color_splash processing_function
(feature 046) -- no Qt, no engine.
"""
from __future__ import annotations

import colorsys

import numpy

from lumaflow.addons.builtin.color_splash import (
    ADDON_DESCRIPTION,
    _GENERIC_DEFAULTS,
    _hue_window_weight,
    _read_float,
    _read_range,
    _rgb_to_hsl,
    _hsl_to_rgb,
    color_splash,
    resolve_zoom_values,
)

_PATCH_SIZE = 20

# hue (deg), label -- red/orange/yellow/green/blue/violet mirror the 6 presets whose hue centers
# are far enough apart (>=90 deg) to never overlap at the default feather (30 deg), so each can be
# tested for "this patch is the only one that stays colored" without ambiguity. "Orange" is
# deliberately excluded from that pairwise-distinctness set since it shares its hue center with
# "Brun" -- tested separately.
_FAR_APART_HUES = {"red": 0.0, "green": 120.0, "blue": 240.0}


def _solid_patch(hue_deg: float, saturation: float, lightness: float) -> numpy.ndarray:
    r, g, b = colorsys.hls_to_rgb(hue_deg / 360.0, lightness, saturation)
    patch = numpy.empty((_PATCH_SIZE, _PATCH_SIZE, 3), dtype=numpy.uint8)
    patch[:] = (round(r * 255), round(g * 255), round(b * 255))
    return patch


def _image_with_patches(patches: dict[str, numpy.ndarray]) -> tuple[numpy.ndarray, dict[str, tuple[slice, slice]]]:
    """Concatenates named patches side by side; returns the image plus each patch's (row, col)
    slice so a test can inspect just that region afterward."""
    ordered = list(patches.items())
    image = numpy.concatenate([patch for _, patch in ordered], axis=1)
    regions: dict[str, tuple[slice, slice]] = {}
    col = 0
    for name, patch in ordered:
        regions[name] = (slice(0, _PATCH_SIZE), slice(col, col + _PATCH_SIZE))
        col += _PATCH_SIZE
    return image, regions


def _mean_saturation(region: numpy.ndarray) -> float:
    _, saturation, _ = _rgb_to_hsl(region.astype(numpy.float32))
    return float(saturation.mean())


def _standard_image() -> tuple[numpy.ndarray, dict[str, tuple[slice, slice]]]:
    patches = {
        name: _solid_patch(hue, saturation=0.8, lightness=0.5)
        for name, hue in {**_FAR_APART_HUES, "orange": 30.0, "yellow": 60.0, "violet": 285.0}.items()
    }
    patches["gray"] = _solid_patch(0.0, saturation=0.0, lightness=0.5)
    return _image_with_patches(patches)


# --- User Story 1: preset selection ---


def test_neutral_empty_params_is_bit_identical():
    image, _ = _standard_image()
    out = color_splash(image, {})
    assert numpy.array_equal(out, image)


def test_each_far_apart_preset_keeps_only_its_own_patch_colored():
    image, regions = _standard_image()
    input_saturation = {name: _mean_saturation(image[region]) for name, region in regions.items()}
    assert all(input_saturation[name] > 0.5 for name in _FAR_APART_HUES)

    for name, hue in _FAR_APART_HUES.items():
        out = color_splash(image, {"range_1_enabled": 1.0, "range_1_hue_center": hue})
        own_region = regions[name]
        assert _mean_saturation(out[own_region]) > 0.5 * input_saturation[name]
        for other_name in _FAR_APART_HUES:
            if other_name == name:
                continue
            # >=120 deg away at feather=30 -- well outside the cosine window, must be fully
            # desaturated (background_desaturation defaults to 100%).
            assert _mean_saturation(out[regions[other_name]]) < 0.05


def test_presets_produce_visibly_distinct_results_from_each_other():
    image, regions = _standard_image()
    outputs = {
        name: color_splash(image, {"range_1_enabled": 1.0, "range_1_hue_center": hue})
        for name, hue in _FAR_APART_HUES.items()
    }
    names = list(outputs)
    for i, name_a in enumerate(names):
        for name_b in names[i + 1 :]:
            assert not numpy.array_equal(outputs[name_a], outputs[name_b])


def test_applying_same_preset_twice_is_identical():
    image, _ = _standard_image()
    params = {"range_1_enabled": 1.0, "range_1_hue_center": 0.0}
    first = color_splash(image, params)
    second = color_splash(image, dict(params))
    assert numpy.array_equal(first, second)


# --- User Story 2: feather, background desaturation, saturation threshold ---


def test_wider_feather_extends_the_transition_zone():
    # A point 50 deg from center: outside a narrow feather's window, inside a wide one's.
    narrow = _hue_window_weight(numpy.array([50.0]), center=0.0, feather=10.0)[0]
    wide = _hue_window_weight(numpy.array([50.0]), center=0.0, feather=80.0)[0]
    assert narrow == 0.0
    assert wide > 0.0


def test_background_desaturation_below_100_leaves_residual_color():
    image, regions = _standard_image()
    # green (120 deg) is far outside the red (0 deg) range at any feather <= 90 -- pure background.
    background_region = regions["green"]
    input_saturation = _mean_saturation(image[background_region])

    full = color_splash(image, {"range_1_enabled": 1.0, "range_1_hue_center": 0.0, "background_desaturation": 100.0})
    partial = color_splash(image, {"range_1_enabled": 1.0, "range_1_hue_center": 0.0, "background_desaturation": 50.0})

    assert _mean_saturation(full[background_region]) < 0.05
    partial_saturation = _mean_saturation(partial[background_region])
    assert 0.3 < partial_saturation / input_saturation < 0.7


def test_near_gray_pixel_in_active_range_is_excluded_by_saturation_threshold():
    low_saturation_patch = _solid_patch(hue_deg=0.0, saturation=0.05, lightness=0.5)
    image, regions = _image_with_patches({"target": low_saturation_patch})
    region = regions["target"]
    input_saturation = _mean_saturation(image[region])

    kept = color_splash(
        image, {"range_1_enabled": 1.0, "range_1_hue_center": 0.0, "saturation_threshold": 2.0}
    )
    excluded = color_splash(
        image, {"range_1_enabled": 1.0, "range_1_hue_center": 0.0, "saturation_threshold": 20.0}
    )

    # Below its own (low) threshold, the patch is boosted/kept like any in-range pixel.
    assert _mean_saturation(kept[region]) >= input_saturation * 0.9
    # Above its saturation, the same patch must fall back to the (fully desaturated) background
    # treatment despite its hue matching the active range exactly.
    assert _mean_saturation(excluded[region]) < 0.02


# --- User Story 3: multiple simultaneous ranges ---


def test_two_active_ranges_are_both_kept_simultaneously():
    image, regions = _standard_image()
    out = color_splash(
        image,
        {
            "range_1_enabled": 1.0, "range_1_hue_center": 0.0,
            "range_2_enabled": 1.0, "range_2_hue_center": 120.0,
        },
    )
    assert _mean_saturation(out[regions["red"]]) > 0.5
    assert _mean_saturation(out[regions["green"]]) > 0.5
    assert _mean_saturation(out[regions["blue"]]) < 0.05


def test_output_never_exceeds_valid_saturation_range_with_overlapping_ranges():
    # orange (30 deg) and yellow (60 deg) overlap at the default 30 deg feather -- their boosts
    # (200%) must blend, never push the result out of the valid [0, 255] uint8 range.
    image, regions = _standard_image()
    out = color_splash(
        image,
        {
            "range_1_enabled": 1.0, "range_1_hue_center": 30.0, "range_1_saturation_boost": 200.0,
            "range_2_enabled": 1.0, "range_2_hue_center": 60.0, "range_2_saturation_boost": 200.0,
        },
    )
    assert out.dtype == numpy.uint8
    assert out.min() >= 0 and out.max() <= 255


def test_disabling_one_of_several_active_ranges_leaves_only_the_rest_colored():
    image, regions = _standard_image()
    params = {
        "range_1_enabled": 1.0, "range_1_hue_center": 0.0,
        "range_2_enabled": 1.0, "range_2_hue_center": 120.0,
        "range_3_enabled": 1.0, "range_3_hue_center": 240.0,
    }
    both = color_splash(image, params)
    assert _mean_saturation(both[regions["red"]]) > 0.5
    assert _mean_saturation(both[regions["green"]]) > 0.5
    assert _mean_saturation(both[regions["blue"]]) > 0.5

    params_disabled = {**params, "range_2_enabled": 0.0}
    out = color_splash(image, params_disabled)
    assert _mean_saturation(out[regions["red"]]) > 0.5
    assert _mean_saturation(out[regions["green"]]) < 0.05
    assert _mean_saturation(out[regions["blue"]]) > 0.5


# --- User Story 4: malformed/out-of-range parameters never raise, always fall back ---


def test_all_ranges_disabled_is_bit_identical_not_fully_desaturated():
    # A corrupted/malformed recipe that loses every range_N_enabled flag must degrade to Neutre
    # (FR-017), not to "every pixel desaturated" -- background_desaturation alone (its default is
    # 100%) must never have an effect without at least one active range.
    image, _ = _standard_image()
    out = color_splash(image, {"range_1_enabled": 0.0, "range_2_enabled": 0.0, "range_3_enabled": 0.0})
    assert numpy.array_equal(out, image)

    # Same guarantee when background_desaturation is present but no range is ever enabled.
    out2 = color_splash(image, {"background_desaturation": 100.0, "saturation_threshold": 50.0})
    assert numpy.array_equal(out2, image)


def test_malformed_or_out_of_range_values_fall_back_to_defaults_without_raising():
    image, _ = _standard_image()
    bad_values = (None, "far", True, -999.0, 999.0, [], {})
    for bad in bad_values:
        out = color_splash(
            image,
            {
                "range_1_enabled": 1.0,
                "range_1_hue_center": bad,
                "range_1_feather": bad,
                "range_1_saturation_boost": bad,
                "background_desaturation": bad,
                "saturation_threshold": bad,
            },
        )
        assert out.dtype == numpy.uint8
        assert out.shape == image.shape


def test_read_float_wraps_hue_instead_of_clamping():
    assert _read_float({"h": 370.0}, "h", 0.0, wrap=True) == 10.0
    assert _read_float({"h": -10.0}, "h", 0.0, wrap=True) == 350.0


def test_read_range_disabled_below_half():
    assert _read_range({"range_1_enabled": 0.4}, 1).enabled is False
    assert _read_range({"range_1_enabled": 0.5}, 1).enabled is True


# --- resolve_zoom_values: overrides win, generic defaults fill the rest ---


def test_resolve_zoom_values_surfaces_preset_override_and_fills_generic_defaults():
    orange_preset = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Orange")
    values = resolve_zoom_values(orange_preset.preset_parameters)
    assert values["range_1_hue_center"] == 30.0
    assert values["saturation_threshold"] == _GENERIC_DEFAULTS["saturation_threshold"]
    assert values["range_2_enabled"] == _GENERIC_DEFAULTS["range_2_enabled"]


# --- Round-trip sanity for the addon's own HSL utilities ---


def test_rgb_hsl_round_trip_is_approximately_stable():
    image, _ = _standard_image()
    hue, saturation, luminance = _rgb_to_hsl(image.astype(numpy.float32))
    back = _hsl_to_rgb(hue, saturation, luminance)
    assert numpy.allclose(back, image.astype(numpy.float32), atol=1.5)
