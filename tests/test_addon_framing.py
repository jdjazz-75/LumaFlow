# LumaFlow v1.0 (2026-08-07)
# Teste les fonctions pures de l'addon Framing : recadrage libre (crop), catalogue de guides de
# composition (overlays), et résolution des valeurs de zoom — sans dépendance moteur.

"""Pure-function tests for the Framing addon's crop processing_function and
free-form-crop catalog (feature 041, reworked for the free-form crop-frame UI)
-- no Qt, no engine.
"""
from __future__ import annotations

import numpy

from lumaflow.addons.builtin.framing import ADDON_DESCRIPTION, crop, resolve_zoom_values


def _image(val: int = 100, width: int = 200, height: int = 100) -> numpy.ndarray:
    arr = numpy.zeros((height, width, 3), dtype=numpy.uint8)
    arr[...] = val
    return arr


def test_full_frame_box_is_bit_identical_to_input():
    image = _image()
    out = crop(image, {"crop_x": 0.0, "crop_y": 0.0, "crop_width": 1.0, "crop_height": 1.0})
    assert numpy.array_equal(out, image)


def test_missing_params_default_to_full_frame_identity():
    image = _image()
    out = crop(image, {})
    assert numpy.array_equal(out, image)


def test_16_9_box_matches_target_ratio_and_is_centered():
    image = _image(width=200, height=100)
    # Centered 16:9 box on a 2:1 image: box_width = height * 16/9, box_height = height.
    box_width = 100 * (16 / 9)
    crop_width = box_width / 200
    crop_x = (1.0 - crop_width) / 2.0
    out = crop(image, {"crop_x": crop_x, "crop_y": 0.0, "crop_width": crop_width, "crop_height": 1.0})
    ratio = out.shape[1] / out.shape[0]
    assert abs(ratio - 16 / 9) < 0.05
    assert out.shape[0] == 100  # full height kept, centered horizontally


def test_1_1_box_is_square_and_centered():
    image = _image(width=200, height=100)
    crop_width = 100 / 200
    crop_x = (1.0 - crop_width) / 2.0
    out = crop(image, {"crop_x": crop_x, "crop_y": 0.0, "crop_width": crop_width, "crop_height": 1.0})
    assert abs(out.shape[0] - out.shape[1]) <= 1


def test_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"crop_x": 0.1, "crop_y": 0.1, "crop_width": 0.5, "crop_height": 0.5}
    out1 = crop(image, params)
    out2 = crop(image, params)
    assert numpy.array_equal(out1, out2)


def test_non_numeric_value_falls_back_to_default_per_key():
    image = _image()
    out = crop(image, {"crop_width": "not-a-number"})
    # crop_width falls back to 1.0, everything else at its own default -> full frame identity.
    assert numpy.array_equal(out, image)


def test_degenerate_zero_size_does_not_raise_or_produce_empty_array():
    image = _image()
    out = crop(image, {"crop_width": 0.0, "crop_height": 0.0})
    assert out.shape[0] > 0
    assert out.shape[1] > 0


def test_out_of_bounds_box_is_shrunk_not_shifted_off_frame():
    image = _image()
    out = crop(image, {"crop_x": 0.9, "crop_y": 0.9, "crop_width": 0.5, "crop_height": 0.5})
    assert out.shape[0] <= image.shape[0]
    assert out.shape[1] <= image.shape[1]
    assert out.shape[0] > 0 and out.shape[1] > 0


def test_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    crop(image, {"crop_x": 0.1, "crop_y": 0.1, "crop_width": 0.5, "crop_height": 0.5})
    assert numpy.array_equal(image, snapshot)


def test_addon_description_shape():
    assert ADDON_DESCRIPTION.identifier == "framing_crop"
    assert ADDON_DESCRIPTION.category == "framing"
    # No aspect-ratio-locked presets: free-form crop only, always starting full-frame.
    assert len(ADDON_DESCRIPTION.thumbnail_presets) == 1
    neutral = ADDON_DESCRIPTION.thumbnail_presets[0]
    assert neutral.identifier == "neutral"
    assert neutral.neutral is True
    assert neutral.preset_parameters is None
    assert len(ADDON_DESCRIPTION.parameter_descriptions) == 4
    identifiers = {p.identifier for p in ADDON_DESCRIPTION.parameter_descriptions}
    assert identifiers == {"crop_x", "crop_y", "crop_width", "crop_height"}
    assert all(p.zoom_only for p in ADDON_DESCRIPTION.parameter_descriptions)
    assert ADDON_DESCRIPTION.resolve_zoom_values is resolve_zoom_values


def test_overlay_catalog_has_one_guide_per_kind_with_thirds_default_active():
    overlays = ADDON_DESCRIPTION.overlay_descriptions
    kinds = [overlay.kind for overlay in overlays]
    assert kinds == [
        "thirds", "golden_section", "golden_triangles", "golden_spiral",
        "center_lines", "diagonal", "pyramid", "compound_curve",
    ]
    assert len(set(kinds)) == len(kinds)  # no duplicate kind
    active = [overlay.kind for overlay in overlays if overlay.default_active]
    assert active == ["thirds"]  # exactly one default-active guide


def test_golden_guide_labels_stay_untranslated():
    # "Golden Section"/"Golden Triangles"/"Golden Spiral" are established English composition-
    # guide names -- a literal French translation reads as unnatural/meaningless (user feedback).
    by_kind = {overlay.kind: overlay.label for overlay in ADDON_DESCRIPTION.overlay_descriptions}
    assert by_kind["golden_section"] == "Golden Section"
    assert by_kind["golden_triangles"] == "Golden Triangles"
    assert by_kind["golden_spiral"] == "Golden Spiral"


def test_resolve_zoom_values_reflects_the_active_crop_box_not_generic_defaults():
    params = {"crop_x": 0.2, "crop_y": 0.1, "crop_width": 0.5, "crop_height": 0.4}
    assert resolve_zoom_values(params) == {
        "crop_x": 0.2, "crop_y": 0.1, "crop_width": 0.5, "crop_height": 0.4,
    }


def test_resolve_zoom_values_defaults_to_full_frame_when_no_override_present():
    assert resolve_zoom_values({}) == {
        "crop_x": 0.0, "crop_y": 0.0, "crop_width": 1.0, "crop_height": 1.0,
    }
