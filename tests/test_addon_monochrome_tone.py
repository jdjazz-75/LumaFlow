# LumaFlow v1.0 (2026-08-07)
# Teste la fonction pure de l'addon Monochrome Tone (monochrome_tone) : dispatch neutre/preset,
# mélange par intensité, mécanisme de colorisation, pré-échelle de saturation d'origine, vignettage,
# grain, et résolution des valeurs de zoom pour les 6 presets hex-dérivés.

"""Pure-function tests for the Monochrome Tone addon's monochrome_tone
processing_function (feature 2026-07-27) -- no Qt, no engine.

Revised 2026-07-27 (later the same day): the addon's 5 original presets
(Ambre/Bleu Nuit/Vert Cactus/Jaune Léger/Sépia Chaud) were replaced by 6
hex-derived presets (Rouge/Sepia/Jaune/Vert/Bleu/Violet) -- see
lumaflow/addons/builtin/monochrome_tone.py's module docstring.
"""
from __future__ import annotations

import numpy

from lumaflow.addons.builtin.monochrome_tone import (
    _apply_original_saturation,
    _apply_tone,
    _apply_vignette,
    _NEUTRAL_TONE,
    _ROUGE_TONE,
    _TONE_GRADES,
    _ToneParams,
    _VIOLET_TONE,
    ADDON_DESCRIPTION,
    monochrome_tone,
    resolve_zoom_values,
)

_PRESETS = ("rouge", "sepia", "jaune", "vert", "bleu", "violet")


def _image() -> numpy.ndarray:
    """A colorful, non-uniform gradient -- distinct R/G/B per pixel so
    luminance/saturation statistics are meaningfully testable.
    """
    height, width = 40, 60
    arr = numpy.zeros((height, width, 3), dtype=numpy.uint8)
    for y in range(height):
        for x in range(width):
            arr[y, x] = ((x * 4) % 256, (y * 4) % 256, ((x + y) * 3) % 256)
    return arr


# --- Addon shape ---


def test_addon_description_shape():
    assert ADDON_DESCRIPTION.identifier == "monochrome_tone"
    assert ADDON_DESCRIPTION.category == "monochrome_tone"
    identifiers = {preset.identifier for preset in ADDON_DESCRIPTION.thumbnail_presets}
    assert identifiers == {"neutral", "Rouge", "Sepia", "Jaune", "Vert", "Bleu", "Violet"}
    neutral = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "neutral")
    assert neutral.neutral is True
    assert neutral.preset_parameters is None
    for identifier, preset_key in (
        ("Rouge", "rouge"),
        ("Sepia", "sepia"),
        ("Jaune", "jaune"),
        ("Vert", "vert"),
        ("Bleu", "bleu"),
        ("Violet", "violet"),
    ):
        preset = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == identifier)
        assert preset.preset_parameters == {"preset": preset_key, "intensity": 1.0}


def test_addon_declares_14_zoom_only_sliders():
    descriptions = ADDON_DESCRIPTION.parameter_descriptions
    assert len(descriptions) == 14
    assert all(description.zoom_only for description in descriptions)
    assert all(description.kind == "numeric_slider" for description in descriptions)
    identifiers = {description.identifier for description in descriptions}
    assert identifiers == {
        "original_saturation", "hue", "tint_saturation", "force",
        "contrast", "shadows", "highlights", "black_point", "grain",
        "temperature_shift", "tint_magenta", "clarity", "sharpness", "vignette",
    }


# --- Neutral / dispatch ---


def test_neutral_empty_params_is_bit_identical():
    image = _image()
    out = monochrome_tone(image, {})
    assert numpy.array_equal(out, image)


def test_unrecognized_preset_falls_back_to_identity():
    image = _image()
    out = monochrome_tone(image, {"preset": "not_a_real_preset", "intensity": 1.0})
    assert numpy.array_equal(out, image)


def test_missing_non_numeric_or_out_of_range_intensity_falls_back_to_identity():
    image = _image()
    for bad_intensity in (None, "high", -0.1, 1.5, True):
        params: dict = {"preset": "rouge"}
        if bad_intensity is not None:
            params["intensity"] = bad_intensity
        out = monochrome_tone(image, params)
        assert numpy.array_equal(out, image)


def test_intensity_zero_is_bit_identical_regardless_of_preset():
    image = _image()
    for preset in _PRESETS:
        out = monochrome_tone(image, {"preset": preset, "intensity": 0.0})
        assert numpy.array_equal(out, image)


def test_intensity_one_matches_direct_apply_tone():
    image = _image()
    for preset in _PRESETS:
        via_dispatch = monochrome_tone(image, {"preset": preset, "intensity": 1.0})
        direct = numpy.clip(
            _apply_tone(image.astype(numpy.float32), _TONE_GRADES[preset]), 0, 255
        ).round().astype(numpy.uint8)
        assert numpy.array_equal(via_dispatch, direct)


def test_fractional_intensity_blends_toward_original():
    image = _image()
    for preset in _PRESETS:
        full = monochrome_tone(image, {"preset": preset, "intensity": 1.0}).astype(numpy.int16)
        half = monochrome_tone(image, {"preset": preset, "intensity": 0.5}).astype(numpy.int16)
        original = image.astype(numpy.int16)
        # Half-intensity must sit strictly between the original and full-strength
        # output (not equal to either) for a preset with a visible effect.
        assert not numpy.array_equal(half, full)
        assert not numpy.array_equal(half, original)


def test_neutral_still_honors_zoom_only_manual_overrides():
    """Same convention as film.py's film_look (2026-07-23 fix) -- a missing
    `preset` (Neutral) still applies Zoom-only overrides via _NEUTRAL_TONE
    rather than being silently discarded.
    """
    image = _image()
    untouched = monochrome_tone(image, {})
    overridden = monochrome_tone(image, {"hue": 200.0, "tint_saturation": 50.0, "force": 80.0})
    assert not numpy.array_equal(untouched, overridden)


# --- Per-preset determinism / non-mutation / shape+dtype ---


def test_each_preset_deterministic_repeat_call_is_byte_identical():
    image = _image()
    for preset in _PRESETS:
        params = {"preset": preset, "intensity": 1.0}
        out1 = monochrome_tone(image, params)
        out2 = monochrome_tone(image, dict(params))
        assert numpy.array_equal(out1, out2)


def test_each_preset_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    for preset in _PRESETS:
        monochrome_tone(image, {"preset": preset, "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_each_preset_output_shape_and_dtype_unchanged():
    image = _image()
    for preset in _PRESETS:
        out = monochrome_tone(image, {"preset": preset, "intensity": 0.5})
        assert out.shape == image.shape
        assert out.dtype == numpy.uint8


def test_presets_produce_visibly_distinct_statistics_from_each_other_and_input():
    image = _image()
    outputs = {preset: monochrome_tone(image, {"preset": preset, "intensity": 1.0}) for preset in _PRESETS}
    for preset, out in outputs.items():
        assert not numpy.array_equal(out, image), preset
    names = list(outputs)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            assert not numpy.array_equal(outputs[a], outputs[b]), f"{a} == {b}"


# --- Colorization mechanism ---


def test_colorized_output_is_not_equal_channel_since_tint_saturation_is_nonzero():
    """Every one of the 6 presets sets a nonzero tint_saturation/force, so the
    final output must NOT have R == G == B (that would mean colorization had
    no visible effect at all).
    """
    image = _image()
    for preset in _PRESETS:
        out = monochrome_tone(image, {"preset": preset, "intensity": 1.0})
        assert not (
            numpy.array_equal(out[..., 0], out[..., 1]) and numpy.array_equal(out[..., 1], out[..., 2])
        ), preset


def test_force_zero_is_plain_grayscale_no_colorization():
    # temperature_shift/tint_magenta zeroed too -- those are a separate,
    # independent post-cast nudge (see _apply_tone) that would otherwise
    # break the equal-channel guarantee on their own, same as
    # test_monochrome_output_has_equal_channels_absent_mono_colour_toning's
    # precedent in test_addon_film.py.
    image = _image()
    tone = _ROUGE_TONE._replace(force=0.0, temperature_shift=0.0, tint_magenta=0.0)
    out = numpy.clip(_apply_tone(image.astype(numpy.float32), tone), 0, 255).round().astype(numpy.uint8)
    assert numpy.array_equal(out[..., 0], out[..., 1])
    assert numpy.array_equal(out[..., 1], out[..., 2])


def test_higher_force_produces_a_more_saturated_result():
    image = _image()
    low = _apply_tone(image.astype(numpy.float32), _ROUGE_TONE._replace(force=10.0))
    high = _apply_tone(image.astype(numpy.float32), _ROUGE_TONE._replace(force=90.0))
    assert not numpy.array_equal(numpy.round(low), numpy.round(high))


# --- original_saturation pre-scale ---


def test_apply_original_saturation_is_identity_at_neutral_factor_one():
    image = _image().astype(numpy.float32)
    out = _apply_original_saturation(image, 1.0)
    assert numpy.allclose(out, image, atol=1e-3)


def test_apply_original_saturation_at_zero_produces_equal_channel_output():
    image = _image().astype(numpy.float32)
    out = _apply_original_saturation(image, 0.0)
    assert numpy.allclose(out[..., 0], out[..., 1], atol=1e-3)
    assert numpy.allclose(out[..., 1], out[..., 2], atol=1e-3)


# --- Vignette ---


def test_apply_vignette_is_noop_at_zero():
    image = _image().astype(numpy.float32)
    out = _apply_vignette(image, 0.0)
    assert numpy.array_equal(out, image)


def test_apply_vignette_darkens_corners_more_than_center_at_negative_amount():
    image = numpy.full((41, 61, 3), 200.0, dtype=numpy.float32)
    out = _apply_vignette(image, -80.0)
    center = out[20, 30]
    corner = out[0, 0]
    assert corner[0] < center[0]


def test_no_current_preset_uses_a_nonzero_vignette_clarity_or_sharpness():
    """Since 2026-07-27's hex-derived revision, all 6 presets share one flat
    template (no per-preset grade was supplied, only a target color) --
    clarity/sharpness/vignette all stay at the _ToneParams default of 0.0.
    (The retired Sépia Chaud preset was the sole one exercising a nonzero
    vignette; that coverage is gone with it, kept in mind if a future preset
    reintroduces one.)
    """
    for preset in _PRESETS:
        tone = _TONE_GRADES[preset]
        assert tone.clarity == 0.0
        assert tone.sharpness == 0.0
        assert tone.vignette == 0.0


# --- Grain ---


def test_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_tone(image.astype(numpy.float32), _ROUGE_TONE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain = numpy.clip(
        _apply_tone(image.astype(numpy.float32), _ROUGE_TONE._replace(grain=0.0)), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, no_grain)


# --- resolve_zoom_values ---


def test_resolve_zoom_values_unrecognized_preset_only_returns_intensity():
    values = resolve_zoom_values({"preset": "not_a_real_preset", "intensity": 0.6})
    assert values == {"intensity": 0.6}


def test_resolve_zoom_values_missing_preset_only_returns_intensity():
    values = resolve_zoom_values({})
    assert values == {"intensity": 1.0}


def test_resolve_zoom_values_seeds_from_the_presets_own_calibration():
    values = resolve_zoom_values({"preset": "violet", "intensity": 1.0})
    assert values["hue"] == _VIOLET_TONE.hue
    assert values["tint_saturation"] == _VIOLET_TONE.tint_saturation
    assert values["force"] == _VIOLET_TONE.force
    assert values["contrast"] == _VIOLET_TONE.contrast
    assert values["grain"] == _VIOLET_TONE.grain


def test_resolve_zoom_values_override_wins_over_calibration():
    values = resolve_zoom_values({"preset": "rouge", "intensity": 1.0, "hue": 300.0})
    assert values["hue"] == 300.0
    # Untouched fields still come from Rouge's own calibration.
    assert values["force"] == _ROUGE_TONE.force


def test_resolve_zoom_values_hue_override_wraps_at_360():
    values = resolve_zoom_values({"preset": "rouge", "intensity": 1.0, "hue": 370.0})
    assert values["hue"] == 10.0


def test_apply_tone_overrides_returns_same_object_when_nothing_overridden():
    from lumaflow.addons.builtin.monochrome_tone import _apply_tone_overrides

    resolved = _apply_tone_overrides(_ROUGE_TONE, {"preset": "rouge", "intensity": 1.0})
    assert resolved is _ROUGE_TONE


# --- Neutral base ---


def test_neutral_tone_is_all_defaults():
    assert _NEUTRAL_TONE == _ToneParams()


# --- Hex-derived hue/saturation sanity (2026-07-27 revision) ---


def test_hex_derived_hue_and_saturation_match_the_supplied_colors():
    """Cross-check against colorsys.rgb_to_hls on the exact hex values the
    user supplied -- guards against a transcription slip when hand-copying
    the decoded hue/saturation into each _ToneParams literal.
    """
    import colorsys

    expected_hex = {
        "rouge": "#AC5753",
        "sepia": "#998A66",
        "jaune": "#9F9A60",
        "vert": "#709966",
        "bleu": "#3660C9",
        "violet": "#855CA3",
    }
    for preset, hex_value in expected_hex.items():
        hex_value = hex_value.lstrip("#")
        r, g, b = (int(hex_value[i : i + 2], 16) / 255 for i in (0, 2, 4))
        h, _l, s = colorsys.rgb_to_hls(r, g, b)
        tone = _TONE_GRADES[preset]
        assert tone.hue == round(h * 360, 1)
        assert tone.tint_saturation == round(s * 100, 1)
