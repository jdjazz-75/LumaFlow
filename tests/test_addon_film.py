# LumaFlow v1.0 (2026-08-07)
# Tests unitaires purs de l'addon Film (film_look/_apply_parametric_grade,
# lumaflow/addons/builtin/film.py) : primitives du moteur de grade (courbe de
# tons, teinte/luminance par teinte HSL, split-tone, grain, Color Chrome
# Effect/Blue, Dynamic Range) et chaque look/preset (Classic Chrome Pro,
# Velvia Pro, Acros Pro, Astia, Pro Neg. Std, Eterna, Eterna Bleach Bypass,
# looks Bleach Bypass/B&W, Kodak/Ilford) ainsi que les overrides Zoom
# (resolve_zoom_values, _apply_grade_overrides) et le filtre couleur N&B.
"""Pure-function tests for the Film addon's film_look processing_function
(feature 042) -- no Qt, no engine.
"""
from __future__ import annotations

import colorsys

import numpy

from lumaflow.addons.builtin.film import (
    _ACROS_GREEN_FILTER_GRADE,
    _ACROS_PRO_GRADE,
    _ACROS_YELLOW_FILTER_GRADE,
    ADDON_DESCRIPTION,
    _apply_color_chrome_blue,
    _apply_color_chrome_effect,
    _apply_grade_overrides,
    _apply_monochrome_grade,
    _apply_parametric_grade,
    _apply_grain,
    _apply_hsl_hue_rotation,
    _apply_hsl_luminance_by_hue,
    _apply_hsl_saturation_by_hue,
    _apply_split_tone,
    _apply_temperature_tint,
    _apply_tone_curve,
    _box_blur,
    _CLASSIC_CHROME_PRO_GRADE,
    _CLASSIC_NEGATIVE_GRADE,
    _ECOWARRIOR_GRADE,
    _ETERNA_BLEACH_BYPASS_GRADE,
    _ETERNA_GRADE,
    _FILTER_WEIGHTS_TABLE,
    _GLACIER_BLUE_GRADE,
    _GRADES,
    _GradeParams,
    _hsl_to_rgb,
    _ILFORD_FP4_GRADE,
    _INKY_DEPTHS_GRADE,
    _KODAK_TMAX_3200_GRADE,
    _KODAK_TRIX_GRADE,
    _LOKI_GRADE,
    _MILESTONE_GRADE,
    _mono_color_to_temperature_tint,
    _MONOCHROME_BASE_GRADE,
    _PRO_NEG_STD_GRADE,
    _QUICKLIME_GRADE,
    _relative_gate,
    _resolve_dynamic_range,
    _resolve_filter_weights,
    _rgb_to_hsl,
    _RIZZLE_CLICKS_GRADE,
    _ASTIA_GRADE,
    _SUNSET_STRIP_GRADE,
    _TITANIUM_GRADE,
    _VELVIA_PRO_GRADE,
    film_look,
    resolve_zoom_values,
)

# _GILT_TRIP_GRADE, _MONOCHROME_GRADE, _SUMMER_STORY_GRADE, _UNDERGLOW_GRADE
# retired 2026-07-27 (user request, see film.py's module docstring) -- no
# longer importable, so removed from this import block and their own tests
# deleted. _DAIDO_MORIYAMA_GRADE, _MONO_MOONLIGHT_GRADE retired 2026-08-04
# (user request, see film.py's module docstring) -- same treatment.
# _NEWSPRINT_GRADE, _SILVERTONE_99_GRADE retired 2026-08-05 (user request,
# see film.py's module docstring) -- same treatment.

_PRE_EXISTING_LOOKS = (
    "classic_chrome_pro",
    "velvia_pro",
    "acros_pro",
    "astia",
    "pro_neg_std",
    "eterna",
    "eterna_bleach_bypass",
)

# Looks added 2026-07-25, on top of _PRE_EXISTING_LOOKS -- Summer Story/Inky
# Depths (Film row), then Classic Negative (a new base, exposed standalone)
# and the 5 recipes built on Eterna Bleach Bypass/Classic Negative that moved
# into their own "Bleach Bypass" workflow row (config_workflow.json; same
# film_look addon, no engine change -- see _resolve_addon_for_row).
# "summer_story" retired 2026-07-27 (user request, see film.py's module
# docstring) -- removed from this tuple the same way.
_NEW_LOOKS = (
    "inky_depths",
    "classic_negative",
    "ecowarrior",
    "loki",
    "sunset_strip",
    "rizzle_clicks",
    "glacier_blue",
)

# Looks added 2026-07-26, in the new "Monochrome" workflow row -- Monochrome
# itself and Mono Moonlight build on a new, module-internal calibration
# anchor (_MONOCHROME_BASE_GRADE, not itself a selectable look); Titanium on
# Eterna Bleach Bypass; Underglow/Milestone/Quicklime on Classic
# Negative/Classic Chrome Pro; Gilt Trip on Acros Pro. Three of the seven
# (Monochrome, Mono Moonlight, Gilt Trip) also exercise the new
# mono_color_wc/mono_color_mg fields.
# "monochrome"/"underglow"/"gilt_trip" retired 2026-07-27 (user request, see
# film.py's module docstring) -- removed from this tuple the same way.
# "mono_moonlight" retired 2026-08-04 (user request, see film.py's module
# docstring) -- removed the same way.
_MONOCHROME_ROW_LOOKS = (
    "titanium",
    "milestone",
    "quicklime",
)

# Looks added 2026-07-26 (later the same day), in the new "B&W" workflow row
# -- "daido_moriyama" (a DELIBERATE duplicate of "Monochrome") retired
# 2026-08-04, "newsprint"/"silvertone_99" (built on the module-internal Acros
# Yellow/Green Filter calibration anchors) retired 2026-08-05, both user
# requests (see film.py's module docstring) -- removed from this tuple the
# same way (the "B&W" row's other pre-2026-08-05 looks, "acros_pro" and its
# filter-override presets, are already covered by _PRE_EXISTING_LOOKS / the
# dedicated Acros + Couleur tests below). "kodak_tmax"/"kodak_tmax_3200"/
# "kodak_trix" added 2026-08-05 (later the same day) -- Kodak T-MAX built on
# the module-internal Monochrome base, T-MAX 3200/Tri-X on Acros Pro.
# "agfa_apx"/"ilford_delta"/"ilford_fp4"/"ilford_hp5"/"ilford_xp2" added
# 2026-08-05 (later still) -- Agfa APX/Ilford XP2 on Acros Pro, Ilford
# Delta/FP4/HP5 on the module-internal Monochrome base. "kodak_tmax"/
# "agfa_apx"/"ilford_delta"/"ilford_hp5"/"ilford_xp2" retired (still later
# the same day, user request, see film.py's module docstring) -- removed
# from this tuple the same way, leaving "kodak_tmax_3200"/"kodak_trix"/
# "ilford_fp4".
_BW_ROW_LOOKS: tuple[str, ...] = (
    "kodak_tmax_3200",
    "kodak_trix",
    "ilford_fp4",
)

_ALL_LOOKS = _PRE_EXISTING_LOOKS + _NEW_LOOKS + _MONOCHROME_ROW_LOOKS + _BW_ROW_LOOKS


def _image() -> numpy.ndarray:
    """A colorful, non-uniform gradient -- distinct R/G/B per pixel so
    saturation/luma statistics and the Acros monochrome guarantee are
    meaningfully testable.
    """
    height, width = 40, 60
    arr = numpy.zeros((height, width, 3), dtype=numpy.uint8)
    for y in range(height):
        for x in range(width):
            arr[y, x] = (int(255 * x / width), int(255 * y / height), 128)
    return arr


def _mean_saturation(image: numpy.ndarray) -> float:
    arr = image.astype(numpy.float32)
    maximum = arr.max(axis=-1)
    minimum = arr.min(axis=-1)
    saturation = numpy.where(maximum > 0, (maximum - minimum) / numpy.maximum(maximum, 1e-6), 0.0)
    return float(saturation.mean())


def _mean_luma(image: numpy.ndarray) -> float:
    arr = image.astype(numpy.float32)
    return float((arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114).mean())


def test_missing_look_is_bit_identical_at_any_intensity():
    image = _image()
    for intensity in (0.0, 0.5, 1.0):
        out = film_look(image, {"intensity": intensity})
        assert numpy.array_equal(out, image)


def test_unrecognized_look_is_bit_identical():
    image = _image()
    out = film_look(image, {"look": "sepia", "intensity": 1.0})
    assert numpy.array_equal(out, image)


def test_neutral_empty_params_is_bit_identical():
    image = _image()
    out = film_look(image, {})
    assert numpy.array_equal(out, image)


def test_intensity_zero_is_bit_identical_regardless_of_look():
    image = _image()
    for look in _ALL_LOOKS:
        out = film_look(image, {"look": look, "intensity": 0.0})
        assert numpy.array_equal(out, image)


def test_missing_non_numeric_or_out_of_range_intensity_falls_back_to_identity():
    image = _image()
    for bad_intensity in (None, "high", -0.1, 1.5, True):
        params = {"look": "velvia_pro"}
        if bad_intensity is not None:
            params["intensity"] = bad_intensity
        out = film_look(image, params)
        assert numpy.array_equal(out, image)


def test_missing_intensity_key_falls_back_to_identity():
    image = _image()
    out = film_look(image, {"look": "velvia_pro"})
    assert numpy.array_equal(out, image)


def test_looks_produce_visibly_distinct_statistics_from_each_other_and_input():
    image = _image()
    input_saturation = _mean_saturation(image)

    outputs = {
        look: film_look(image, {"look": look, "intensity": 1.0})
        for look in _ALL_LOOKS
    }

    stats = {look: (_mean_saturation(out), _mean_luma(out)) for look, out in outputs.items()}

    # Each look differs from the unmodified input (saturation or luma).
    for look in _ALL_LOOKS:
        assert stats[look] != (input_saturation, _mean_luma(image)), look
    assert stats["acros_pro"][0] < 1e-6  # fully desaturated

    # Each look differs from every other (at least one of saturation/luma differs) --
    # "daido_moriyama" was a deliberate field-for-field duplicate of
    # "monochrome" (excluded here for that reason), but "monochrome" itself
    # was retired 2026-07-27 (user request) and is no longer in _ALL_LOOKS,
    # so this skip-set is now inert -- kept for history/reversibility rather
    # than removed outright.
    known_identical_pairs = {frozenset({"monochrome", "daido_moriyama"})}
    names = list(_ALL_LOOKS)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if frozenset({a, b}) in known_identical_pairs:
                continue
            assert stats[a] != stats[b], f"{a} == {b}"


# Retired 2026-07-16 alongside "Classic Chrome"/"Velvia"/"Acros" themselves
# (module docstring in lumaflow/addons/builtin/film.py) -- with these looks
# no longer resolvable, film_look() now falls back to identity for them, so
# these assertions no longer hold and their tests were removed.


def test_intensity_one_matches_full_strength_look_directly():
    image = _image()
    for look in _ALL_LOOKS:
        via_blend_boundary = film_look(image, {"look": look, "intensity": 1.0})
        # Calling twice at intensity=1.0 must be identical (no blend-arithmetic drift).
        again = film_look(image, {"look": look, "intensity": 1.0})
        assert numpy.array_equal(via_blend_boundary, again)


def test_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "velvia_pro", "intensity": 0.4}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "acros_pro", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "velvia_pro", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_addon_description_shape():
    assert ADDON_DESCRIPTION.identifier == "film_look"
    assert ADDON_DESCRIPTION.category == "film"
    identifiers = {preset.identifier for preset in ADDON_DESCRIPTION.thumbnail_presets}
    # "Classic Chrome", "Velvia", "Acros" all retired 2026-07-16 in favor of
    # their "*_pro" counterparts (module docstring); "Astia"/"Pro Neg. Std"/
    # "Eterna"/"Eterna Bleach Bypass" added the same day. The "*_pro"
    # counterparts' displayed identifiers were later (2026-07-17) simplified
    # back to the bare names "Classic Chrome"/"Velvia"/"Acros" -- the internal
    # "look" parameter values ("classic_chrome_pro" etc.) are unchanged.
    # "Summer Story", "Monochrome", "Underglow", "Gilt Trip" retired 2026-07-27
    # (user request, see film.py's module docstring) -- absent here the same
    # way "Classic Chrome"/"Velvia"/"Acros" (the original, 2026-07-16 ones)
    # would be. "Mono Moonlight"/"Daido Moriyama" retired 2026-08-04, then
    # "Newsprint"/"Silvertone 99" retired 2026-08-05 (both user requests) the
    # same way, all four replaced by the four new filter-based presets.
    # "Kodak T-MAX"/"Kodak T-MAX 3200"/"Kodak Tri-X" added 2026-08-05 (later
    # the same day), then "Agfa APX"/"Ilford Delta"/"Ilford FP4"/"Ilford HP5"/
    # "Ilford XP2" (later still). "Kodak T-MAX"/"Agfa APX"/"Ilford Delta"/
    # "Ilford HP5"/"Ilford XP2" retired (still later the same day, user
    # request), leaving "Kodak T-MAX 3200"/"Kodak Tri-X"/"Ilford FP4".
    assert identifiers == {
        "neutral", "Classic Chrome", "Velvia", "Acros",
        "Astia", "Pro Neg. Std", "Eterna", "Eterna Bleach Bypass",
        "Classic Negative", "Inky Depths",
        "Ecowarrior", "Loki", "Sunset Strip", "Rizzle Clicks", "Glacier Blue",
        "Titanium",
        "Milestone", "Quicklime",
        "Acros + Yellow", "Acros + Red", "Acros + Green", "Acros + Blue",
        "Kodak T-MAX 3200", "Kodak Tri-X", "Ilford FP4",
    }
    neutral = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "neutral")
    assert neutral.neutral is True
    assert neutral.preset_parameters is None
    classic_chrome_pro = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Classic Chrome")
    assert classic_chrome_pro.preset_parameters == {"look": "classic_chrome_pro", "intensity": 1.0}
    velvia_pro = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Velvia")
    assert velvia_pro.preset_parameters == {"look": "velvia_pro", "intensity": 1.0}
    acros_pro = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Acros")
    assert acros_pro.preset_parameters == {"look": "acros_pro", "intensity": 1.0}
    astia = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Astia")
    assert astia.preset_parameters == {"look": "astia", "intensity": 1.0}
    pro_neg_std = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Pro Neg. Std")
    assert pro_neg_std.preset_parameters == {"look": "pro_neg_std", "intensity": 1.0}
    eterna = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Eterna")
    assert eterna.preset_parameters == {"look": "eterna", "intensity": 1.0}
    eterna_bleach_bypass = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Eterna Bleach Bypass")
    assert eterna_bleach_bypass.preset_parameters == {"look": "eterna_bleach_bypass", "intensity": 1.0}
    inky_depths = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Inky Depths")
    assert inky_depths.preset_parameters == {"look": "inky_depths", "intensity": 1.0}
    classic_negative = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Classic Negative")
    assert classic_negative.preset_parameters == {"look": "classic_negative", "intensity": 1.0}
    ecowarrior = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Ecowarrior")
    assert ecowarrior.preset_parameters == {"look": "ecowarrior", "intensity": 1.0}
    loki = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Loki")
    assert loki.preset_parameters == {"look": "loki", "intensity": 1.0}
    sunset_strip = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Sunset Strip")
    assert sunset_strip.preset_parameters == {"look": "sunset_strip", "intensity": 1.0}
    rizzle_clicks = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Rizzle Clicks")
    assert rizzle_clicks.preset_parameters == {"look": "rizzle_clicks", "intensity": 1.0}
    glacier_blue = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Glacier Blue")
    assert glacier_blue.preset_parameters == {"look": "glacier_blue", "intensity": 1.0}
    titanium = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Titanium")
    assert titanium.preset_parameters == {"look": "titanium", "intensity": 1.0}
    milestone = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Milestone")
    assert milestone.preset_parameters == {"look": "milestone", "intensity": 1.0}
    quicklime = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Quicklime")
    assert quicklime.preset_parameters == {"look": "quicklime", "intensity": 1.0}
    acros_yellow = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Acros + Yellow")
    assert acros_yellow.preset_parameters == {
        "look": "acros_pro", "intensity": 1.0, "filter_color": 1.0, "filter_intensity": 1.0,
    }
    acros_red = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Acros + Red")
    assert acros_red.preset_parameters == {
        "look": "acros_pro", "intensity": 1.0, "filter_color": 2.0, "filter_intensity": 1.0,
    }
    acros_green = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Acros + Green")
    assert acros_green.preset_parameters == {
        "look": "acros_pro", "intensity": 1.0, "filter_color": 3.0, "filter_intensity": 1.0,
    }
    acros_blue = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Acros + Blue")
    assert acros_blue.preset_parameters == {
        "look": "acros_pro", "intensity": 1.0, "filter_color": 4.0, "filter_intensity": 1.0,
    }
    kodak_tmax_3200 = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Kodak T-MAX 3200")
    assert kodak_tmax_3200.preset_parameters == {"look": "kodak_tmax_3200", "intensity": 1.0}
    kodak_trix = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Kodak Tri-X")
    assert kodak_trix.preset_parameters == {"look": "kodak_trix", "intensity": 1.0}
    ilford_fp4 = next(p for p in ADDON_DESCRIPTION.thumbnail_presets if p.identifier == "Ilford FP4")
    assert ilford_fp4.preset_parameters == {"look": "ilford_fp4", "intensity": 1.0}
    # Zoom overlay screen (2026-07-22): "intensity" plus 20 manual grade-
    # override sliders (contrast/highlights/shadows/black_clip/saturation/
    # HSL saturation+luminance/temperature/tint/split-tone/clarity/sharpness/
    # grain/color_chrome_effect/color_chrome_blue/dynamic_range/mono_color_wc/
    # mono_color_mg/filter_color/filter_intensity) -- see _apply_grade_overrides
    # in film.py. The three Color Chrome/DR sliders were added 2026-07-25 for
    # the Summer Story/Inky Depths recipes; mono_color_wc/mono_color_mg added
    # 2026-07-26 for the "Monochrome" workflow row's recipes;
    # filter_color/filter_intensity added 2026-08-04 for the "B&W" row's
    # colored-filter selector.
    assert len(ADDON_DESCRIPTION.parameter_descriptions) == 21
    by_identifier = {p.identifier: p for p in ADDON_DESCRIPTION.parameter_descriptions}
    assert set(by_identifier) == {
        "intensity",
        "contrast",
        "highlights",
        "shadows",
        "black_clip",
        "global_saturation",
        "hsl_saturation_scale",
        "hsl_luminance_scale",
        "temperature",
        "tint",
        "split_tone_scale",
        "clarity",
        "sharpness",
        "grain_std",
        "color_chrome_effect",
        "color_chrome_blue",
        "dynamic_range",
        "mono_color_wc",
        "mono_color_mg",
        "filter_color",
        "filter_intensity",
    }
    assert all(p.zoom_only is True for p in ADDON_DESCRIPTION.parameter_descriptions)
    intensity_param = by_identifier["intensity"]
    assert intensity_param.default == 1.0
    assert by_identifier["hsl_saturation_scale"].default == 1.0
    assert by_identifier["contrast"].default == 0.0
    for identifier in ("color_chrome_effect", "color_chrome_blue", "dynamic_range"):
        param = by_identifier[identifier]
        assert param.default == 0.0
        assert param.constraints.minimum == 0.0
        assert param.constraints.maximum == 2.0
        assert param.constraints.step == 1.0
    for identifier in ("mono_color_wc", "mono_color_mg"):
        param = by_identifier[identifier]
        assert param.default == 0.0
        assert param.constraints.minimum == -20.0
        assert param.constraints.maximum == 20.0
        assert param.constraints.step == 1.0
    filter_color_param = by_identifier["filter_color"]
    assert filter_color_param.default == 0.0
    assert filter_color_param.constraints.minimum == 0.0
    assert filter_color_param.constraints.maximum == 4.0
    assert filter_color_param.constraints.step == 1.0
    filter_intensity_param = by_identifier["filter_intensity"]
    assert filter_intensity_param.default == 1.0
    assert filter_intensity_param.constraints.minimum == 0.0
    assert filter_intensity_param.constraints.maximum == 2.0
    assert filter_intensity_param.constraints.step == 1.0
    assert ADDON_DESCRIPTION.overlay_descriptions == ()


# ---------------------------------------------------------------------------
# Generic parametric grade engine -- pure-primitive tests, independent of
# any specific calibration (see _CLASSIC_CHROME_PRO_GRADE tests further
# below for the concrete Classic Chrome Pro preset).
# ---------------------------------------------------------------------------


def test_apply_parametric_grade_neutral_params_rounds_to_bit_identical_uint8():
    """The RGB<->HSL round trip has negligible float noise (~1e-4 out of
    255), but every _GradeParams() default is a mathematically exact no-op,
    so rounding to uint8 -- the only way this engine's output is ever
    actually consumed -- recovers the original image exactly.
    """
    image = _image()
    result = _apply_parametric_grade(image.astype(numpy.float32), _GradeParams())
    rounded = numpy.clip(result, 0, 255).round().astype(numpy.uint8)
    assert numpy.array_equal(rounded, image)


def test_rgb_hsl_round_trip_is_near_identity():
    image = _image().astype(numpy.float32)
    hue, saturation, luminance = _rgb_to_hsl(image)
    back = _hsl_to_rgb(hue, saturation, luminance)
    assert numpy.max(numpy.abs(back - image)) < 0.01


def test_apply_tone_curve_shadows_negative_darkens_shadow_zone():
    l = numpy.array([0.05, 0.5, 0.95], dtype=numpy.float32)
    out = _apply_tone_curve(l, contrast=0.0, highlights=0.0, shadows=-20.0)
    assert out[0] < l[0]  # deep shadow darkened
    assert out[1] == l[1]  # mid-gray untouched by shadow zone weighting
    assert out[2] == l[2]  # highlight zone untouched by shadows param


def test_apply_tone_curve_highlights_negative_compresses_highlight_zone():
    l = numpy.array([0.05, 0.5, 0.95], dtype=numpy.float32)
    out = _apply_tone_curve(l, contrast=0.0, highlights=-12.0, shadows=0.0)
    assert out[2] < l[2]  # highlight compressed toward mid
    assert out[0] == l[0]  # shadow zone untouched by highlights param


def test_apply_tone_curve_all_neutral_is_exact_identity():
    l = numpy.array([0.0, 0.1, 0.5, 0.9, 1.0], dtype=numpy.float32)
    out = _apply_tone_curve(l, contrast=0.0, highlights=0.0, shadows=0.0)
    assert numpy.array_equal(out, l)


def test_apply_hsl_saturation_by_hue_targets_only_named_hues():
    hue = numpy.array([300.0, 0.0, 120.0, 240.0, 60.0], dtype=numpy.float32)  # magenta,red,green,blue,yellow
    saturation = numpy.full(5, 0.8, dtype=numpy.float32)
    out = _apply_hsl_saturation_by_hue(
        hue, saturation, {"magenta": -25.0, "red": -15.0, "green": -15.0, "blue": -10.0}
    )
    assert out[0] < saturation[0]  # magenta reduced
    assert out[1] < saturation[1]  # red reduced
    assert out[2] < saturation[2]  # green reduced
    assert out[3] < saturation[3]  # blue reduced
    assert out[4] == saturation[4]  # yellow untouched (not in the deltas dict)


def test_apply_hsl_saturation_by_hue_empty_deltas_is_identity():
    hue = numpy.array([10.0, 200.0], dtype=numpy.float32)
    saturation = numpy.array([0.3, 0.7], dtype=numpy.float32)
    out = _apply_hsl_saturation_by_hue(hue, saturation, {})
    assert numpy.array_equal(out, saturation)


def test_apply_hsl_luminance_by_hue_targets_only_named_hues():
    hue = numpy.array([240.0, 30.0, 120.0], dtype=numpy.float32)  # blue, orange, green
    luminance = numpy.full(3, 0.5, dtype=numpy.float32)
    out = _apply_hsl_luminance_by_hue(hue, luminance, {"orange": 4.0})
    assert out[0] == luminance[0]  # blue untouched -- 210 deg from orange, past the 40 deg window
    assert out[1] > luminance[1]  # orange brightened (full weight, zero distance)
    assert out[2] == luminance[2]  # green untouched -- 90 deg from orange, past the 40 deg window


def test_apply_hsl_luminance_by_hue_negative_delta_darkens():
    hue = numpy.array([30.0], dtype=numpy.float32)
    luminance = numpy.array([0.5], dtype=numpy.float32)
    out = _apply_hsl_luminance_by_hue(hue, luminance, {"orange": -4.0})
    assert out[0] < luminance[0]


def test_apply_hsl_luminance_by_hue_empty_deltas_is_identity():
    hue = numpy.array([10.0, 200.0], dtype=numpy.float32)
    luminance = numpy.array([0.3, 0.7], dtype=numpy.float32)
    out = _apply_hsl_luminance_by_hue(hue, luminance, {})
    assert numpy.array_equal(out, luminance)


def test_apply_temperature_tint_negative_temperature_cools_gray():
    rgb = numpy.zeros((1, 1, 3), dtype=numpy.float32)
    rgb[0, 0] = (100.0, 100.0, 100.0)
    out = _apply_temperature_tint(rgb, temperature=-100.0, tint=0.0)
    assert out[0, 0, 0] < 100.0  # red reduced
    assert out[0, 0, 2] > 100.0  # blue increased


def test_apply_temperature_tint_zero_is_exact_identity():
    rgb = numpy.array([[[10.0, 20.0, 30.0]]], dtype=numpy.float32)
    out = _apply_temperature_tint(rgb, temperature=0.0, tint=0.0)
    assert numpy.array_equal(out, rgb)


def test_box_blur_of_constant_array_is_unchanged():
    constant = numpy.full((12, 12), 42.0, dtype=numpy.float32)
    assert numpy.allclose(_box_blur(constant, 3), 42.0)


def test_box_blur_zero_radius_is_identity():
    data = numpy.arange(9, dtype=numpy.float32).reshape(3, 3)
    assert numpy.array_equal(_box_blur(data, 0), data)


def test_box_blur_preserves_total_sum_of_a_spike():
    spike = numpy.zeros((11, 11), dtype=numpy.float32)
    spike[5, 5] = 100.0
    blurred = _box_blur(spike, 2)
    assert abs(float(blurred.sum()) - 100.0) < 1e-3


def test_box_blur_matches_naive_edge_padded_reference():
    """Perf remediation (2026-07-17): _blur_axis switched from
    numpy.take(cumsum, range(...)) to plain slice indexing (a view instead of
    a fancy-indexing copy). This test is independent of that internal detail
    -- it pins the function's actual CONTRACT (edge-clamped box average)
    against an obviously-correct nested-loop reference, so a future rewrite
    of the internals can't silently change the edge-handling semantics
    without this test catching it.
    """
    rng = numpy.random.default_rng(42)
    data = rng.random((7, 9)).astype(numpy.float32)
    radius = 2

    def _naive_box_blur(data: numpy.ndarray, radius: int) -> numpy.ndarray:
        height, width = data.shape
        out = numpy.zeros_like(data)
        for y in range(height):
            for x in range(width):
                total = 0.0
                count = 0
                for dy in range(-radius, radius + 1):
                    for dx in range(-radius, radius + 1):
                        yy = min(max(y + dy, 0), height - 1)
                        xx = min(max(x + dx, 0), width - 1)
                        total += data[yy, xx]
                        count += 1
                out[y, x] = total / count
        return out

    expected = _naive_box_blur(data, radius)
    actual = _box_blur(data, radius)
    assert numpy.allclose(actual, expected, atol=1e-4)


def test_apply_split_tone_converges_to_independent_hsl_reference_color():
    """Perf remediation (2026-07-17): _apply_split_tone now computes its
    constant target color via a 1x1 array instead of a full (H, W) one. This
    test locks in the actual SEMANTICS (the target is a real HSL(hue, 1.0,
    0.5) color) against colorsys, an independent reference -- not just
    today's _hsl_to_rgb implementation -- so it protects the target-color
    formula itself, not merely today's optimization.

    Full shadow zone (luminance=0 -> shadow_weight=1.0) and a strength of
    100 (outside the 0..20 range real calibrations use, but the function
    itself doesn't clamp it) forces blend=1.0, so the result must equal the
    target color exactly regardless of the input rgb.
    """
    luminance = numpy.zeros((2, 2), dtype=numpy.float32)
    rgb = numpy.full((2, 2, 3), 200.0, dtype=numpy.float32)
    grade = _GradeParams(split_tone_shadow_hue=120.0, split_tone_shadow_strength=100.0)

    out = _apply_split_tone(rgb, luminance, grade)

    expected_r, expected_g, expected_b = colorsys.hls_to_rgb(120.0 / 360.0, 0.5, 1.0)
    expected = numpy.array([expected_r, expected_g, expected_b], dtype=numpy.float32) * 255.0
    assert numpy.allclose(out[0, 0], expected, atol=0.5)
    # Spatially constant input (uniform hue/luminance) must yield a spatially
    # constant output -- also guards against a future regression that
    # reintroduces per-pixel variation where there should be none.
    assert numpy.allclose(out, out[0, 0])


# ---------------------------------------------------------------------------
# Color Chrome Effect / Color Chrome Blue / Dynamic Range (2026-07-25) -- the
# three new primitives added for Summer Story/Inky Depths. Pure-primitive
# tests, independent of either concrete recipe.
# ---------------------------------------------------------------------------


def test_relative_gate_is_zero_at_or_below_the_low_percentile():
    values = numpy.linspace(0.0, 1.0, 100, dtype=numpy.float32)
    gate = _relative_gate(values, 60.0, 95.0)
    assert gate[0] == 0.0
    assert gate[59] == 0.0  # at the 60th percentile boundary


def test_relative_gate_is_one_at_or_above_the_high_percentile():
    values = numpy.linspace(0.0, 1.0, 100, dtype=numpy.float32)
    gate = _relative_gate(values, 60.0, 95.0)
    assert gate[-1] == 1.0


def test_relative_gate_still_triggers_on_a_heavily_compressed_range():
    """The whole point of the fix: a range that sits entirely under the OLD
    fixed 0.45 threshold (e.g. 0.0..0.15, Inky Depths's actual post-grade
    saturation span) must still produce a meaningful 0..1 gate.
    """
    values = numpy.linspace(0.0, 0.15, 100, dtype=numpy.float32)
    gate = _relative_gate(values, 60.0, 95.0)
    assert gate[0] == 0.0
    assert gate[-1] == 1.0


def test_relative_gate_degenerate_constant_array_is_zero_everywhere():
    values = numpy.full(10, 0.5, dtype=numpy.float32)
    gate = _relative_gate(values, 60.0, 95.0)
    assert numpy.array_equal(gate, numpy.zeros_like(values))


def _saturation_luminance_spread(count: int = 100) -> tuple[numpy.ndarray, numpy.ndarray]:
    """A wide, evenly-spread range of saturation/luminance values -- the
    trigger gate is now PERCENTILE-based (bug fix 2026-07-25, see
    `_relative_gate`'s docstring), so a single-pixel or two-pixel array (the
    original tests here, before the fix) has no meaningful percentile
    spread and can't exercise it; these tests need enough distinct values
    for "top ~5-10%" and "bottom ~30-60%" to mean something.
    """
    saturation = numpy.linspace(0.0, 1.0, count, dtype=numpy.float32)
    luminance = numpy.linspace(0.0, 1.0, count, dtype=numpy.float32)
    return saturation, luminance


def test_apply_color_chrome_effect_is_noop_at_level_zero():
    saturation, luminance = _saturation_luminance_spread()
    out_sat, out_luma = _apply_color_chrome_effect(saturation, luminance, level=0.0)
    assert numpy.array_equal(out_sat, saturation)
    assert numpy.array_equal(out_luma, luminance)


def test_apply_color_chrome_effect_reduces_saturation_and_luminance_of_the_most_saturated_bright_pixel():
    saturation, luminance = _saturation_luminance_spread()
    out_sat, out_luma = _apply_color_chrome_effect(saturation, luminance, level=2.0)
    assert out_sat[-1] < saturation[-1]
    assert out_luma[-1] < luminance[-1]


def test_apply_color_chrome_effect_does_not_affect_the_least_saturated_darkest_pixels():
    # Below both percentile gates (saturation p60, luminance p30) by construction.
    saturation, luminance = _saturation_luminance_spread()
    out_sat, out_luma = _apply_color_chrome_effect(saturation, luminance, level=2.0)
    assert out_sat[0] == saturation[0]
    assert out_luma[0] == luminance[0]


def test_apply_color_chrome_effect_has_a_visible_effect_on_a_heavily_desaturated_lows_saturation_range():
    """Regression test for the bug reported by the user: the original
    absolute-threshold gate (`saturation > 0.45`) silently never fired on a
    heavily desaturated look (e.g. Eterna Bleach Bypass/Inky Depths, whose
    own global_saturation crush of 0.30/0.21 keeps post-grade saturation
    under ~0.15 everywhere) -- confirmed by rendering both real presets and
    finding byte-identical output at every Color Chrome Effect level before
    this fix. The percentile-relative gate must still trigger even when the
    entire saturation range sits far below the old fixed cutoff.
    """
    saturation = numpy.linspace(0.0, 0.15, 100, dtype=numpy.float32)  # Inky Depths's actual post-grade range
    luminance = numpy.linspace(0.0, 1.0, 100, dtype=numpy.float32)
    out_sat, _ = _apply_color_chrome_effect(saturation, luminance, level=2.0)
    assert out_sat[-1] < saturation[-1]


def test_apply_color_chrome_blue_is_noop_at_level_zero():
    saturation, luminance = _saturation_luminance_spread()
    hue = numpy.full_like(saturation, 240.0)  # blue
    out_sat, out_luma = _apply_color_chrome_blue(hue, saturation, luminance, level=0.0)
    assert numpy.array_equal(out_sat, saturation)
    assert numpy.array_equal(out_luma, luminance)


def test_apply_color_chrome_blue_only_affects_blue_and_cyan_hues():
    saturation, luminance = _saturation_luminance_spread()
    hue_blue = numpy.full_like(saturation, 240.0)
    hue_cyan = numpy.full_like(saturation, 180.0)
    hue_red = numpy.full_like(saturation, 0.0)
    out_sat_blue, _ = _apply_color_chrome_blue(hue_blue, saturation, luminance, level=2.0)
    out_sat_cyan, _ = _apply_color_chrome_blue(hue_cyan, saturation, luminance, level=2.0)
    out_sat_red, _ = _apply_color_chrome_blue(hue_red, saturation, luminance, level=2.0)
    assert out_sat_blue[-1] < saturation[-1]  # blue's most-saturated pixel reduced
    assert out_sat_cyan[-1] < saturation[-1]  # cyan's most-saturated pixel reduced
    assert out_sat_red[-1] == saturation[-1]  # red untouched -- outside the hue window


def test_resolve_dynamic_range_is_noop_at_dr100():
    grade = _GradeParams(highlights=10.0, shadows=-10.0, black_clip=0.02, dynamic_range=0.0)
    resolved = _resolve_dynamic_range(grade)
    assert resolved is grade


def test_resolve_dynamic_range_dr200_shifts_highlights_shadows_black_clip():
    grade = _GradeParams(highlights=10.0, shadows=-10.0, black_clip=0.02, dynamic_range=1.0)
    resolved = _resolve_dynamic_range(grade)
    assert resolved.highlights == 10.0 - 15.0
    assert resolved.shadows == -10.0 + 10.0
    assert resolved.black_clip == 0.02 - 0.008
    assert resolved.dynamic_range == 1.0  # the field itself is untouched


def test_resolve_dynamic_range_clips_to_field_bounds():
    grade = _GradeParams(highlights=-95.0, shadows=95.0, black_clip=0.001, dynamic_range=2.0)
    resolved = _resolve_dynamic_range(grade)
    assert resolved.highlights == -100.0
    assert resolved.shadows == 100.0
    assert resolved.black_clip == 0.0


# ---------------------------------------------------------------------------
# Classic Chrome Pro -- the concrete calibration built on the engine above,
# and (2026-07-16) the sole surviving Classic Chrome look; the original
# "Classic Chrome" and its own tests were retired alongside it (module
# docstring in lumaflow/addons/builtin/film.py).
# ---------------------------------------------------------------------------


def test_classic_chrome_pro_decreases_saturation_relative_to_input():
    image = _image()
    out = film_look(image, {"look": "classic_chrome_pro", "intensity": 1.0})
    assert _mean_saturation(out) < _mean_saturation(image)


# Retired 2026-07-16 alongside "Classic Chrome" itself -- comparing against a
# look that now falls back to identity no longer tests anything meaningful,
# so this test was removed.


def test_classic_chrome_pro_deterministic_repeat_call_is_byte_identical():
    """The critical grain-determinism guarantee (Principle IV): grain uses a
    fixed-seed RNG, never derived from wall-clock time or pixel content.
    """
    image = _image()
    params = {"look": "classic_chrome_pro", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_classic_chrome_pro_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _CLASSIC_CHROME_PRO_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _CLASSIC_CHROME_PRO_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_classic_chrome_pro_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "classic_chrome_pro", "intensity": 0.7})
    assert numpy.array_equal(image, snapshot)


def test_classic_chrome_pro_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "classic_chrome_pro", "intensity": 0.6})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# ---------------------------------------------------------------------------
# Generic parametric grade engine -- additional primitives added for
# Velvia Pro / Acros Pro (hue rotation, luminance-dependent grain, custom
# monochrome weights). _apply_tone_curve/_apply_hsl_saturation_by_hue/
# _box_blur/etc. are already covered above; not repeated here.
# ---------------------------------------------------------------------------


def test_apply_hsl_hue_rotation_targets_only_named_hues():
    hue = numpy.array([0.0, 30.0, 120.0, 240.0, 60.0], dtype=numpy.float32)  # red,orange,green,blue,yellow
    out = _apply_hsl_hue_rotation(hue, {"green": -4.0, "blue": -4.0})
    assert out[0] == hue[0]  # red untouched (not in rotations dict)
    assert out[1] == hue[1]  # orange untouched
    assert out[2] == hue[2] - 4.0  # green rotated toward yellow (full weight, zero distance)
    assert out[3] == hue[3] - 4.0  # blue rotated toward cyan
    assert out[4] == hue[4]  # yellow untouched


def test_apply_hsl_hue_rotation_empty_rotations_is_identity():
    hue = numpy.array([10.0, 200.0], dtype=numpy.float32)
    out = _apply_hsl_hue_rotation(hue, {})
    assert numpy.array_equal(out, hue)


def test_apply_grain_shadow_boost_increases_std_in_dark_regions():
    dark_luminance = numpy.full((50, 50), 0.05, dtype=numpy.float32)
    bright_luminance = numpy.full((50, 50), 0.95, dtype=numpy.float32)
    rgb_zero = numpy.zeros((50, 50, 3), dtype=numpy.float32)

    dark_noisy = _apply_grain(rgb_zero.copy(), std=0.010, size=1.0, shadow_boost=0.020, luminance=dark_luminance)
    bright_noisy = _apply_grain(rgb_zero.copy(), std=0.010, size=1.0, shadow_boost=0.020, luminance=bright_luminance)

    assert float(dark_noisy[..., 0].std()) > float(bright_noisy[..., 0].std())


def test_apply_grain_zero_std_and_zero_boost_is_noop():
    rgb = numpy.full((10, 10, 3), 50.0, dtype=numpy.float32)
    out = _apply_grain(rgb, std=0.0, size=1.0, shadow_boost=0.0, luminance=None)
    assert numpy.array_equal(out, rgb)


def test_apply_parametric_grade_monochrome_weights_produces_equal_channels():
    image = _image().astype(numpy.float32)
    grade = _GradeParams(monochrome_weights=(0.30, 0.59, 0.11))
    out = numpy.clip(_apply_parametric_grade(image, grade), 0, 255).round().astype(numpy.uint8)
    assert numpy.array_equal(out[..., 0], out[..., 1])
    assert numpy.array_equal(out[..., 1], out[..., 2])


def test_apply_parametric_grade_monochrome_weights_differ_from_standard_luma():
    """The custom (0.30, 0.59, 0.11) weights are deliberately not identical
    to the standard luma weights (0.299, 0.587, 0.114) -- confirms the custom
    weights are actually used, not silently replaced by _luma().
    """
    image = _image().astype(numpy.float32)
    custom = numpy.clip(
        _apply_parametric_grade(image, _GradeParams(monochrome_weights=(0.30, 0.59, 0.11))), 0, 255
    ).round().astype(numpy.uint8)
    standard = numpy.clip(
        _apply_parametric_grade(image, _GradeParams(monochrome_weights=(0.299, 0.587, 0.114))), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(custom, standard)


# ---------------------------------------------------------------------------
# Velvia Pro -- the concrete calibration built on the engine above, and
# (2026-07-16) the sole surviving Velvia look; the original "Velvia" and its
# own tests were retired alongside it (module docstring).
# ---------------------------------------------------------------------------


def test_velvia_pro_increases_saturation_relative_to_input():
    image = _image()
    out = film_look(image, {"look": "velvia_pro", "intensity": 1.0})
    assert _mean_saturation(out) > _mean_saturation(image)


# Retired 2026-07-16 alongside "Velvia" itself -- comparing against a look
# that now falls back to identity no longer tests anything meaningful, so
# this test was removed.


def test_velvia_pro_green_hue_rotates_toward_yellow():
    green = numpy.zeros((1, 1, 3), dtype=numpy.uint8)
    green[0, 0] = (0, 200, 0)
    out = film_look(green, {"look": "velvia_pro", "intensity": 1.0})
    hue, _, _ = _rgb_to_hsl(out.astype(numpy.float32))
    assert hue[0, 0] < 120.0  # rotated below pure green's 120 deg


def test_velvia_pro_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "velvia_pro", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_velvia_pro_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _VELVIA_PRO_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _VELVIA_PRO_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_velvia_pro_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "velvia_pro", "intensity": 0.7})
    assert numpy.array_equal(image, snapshot)


def test_velvia_pro_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "velvia_pro", "intensity": 0.6})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# ---------------------------------------------------------------------------
# Acros Pro -- the concrete calibration built on the engine above, and
# (2026-07-16) the sole surviving Acros look; the original "Acros" and its
# own tests were retired alongside it (module docstring).
# ---------------------------------------------------------------------------


def test_acros_pro_output_has_equal_channels_at_full_strength():
    image = _image()
    out = film_look(image, {"look": "acros_pro", "intensity": 1.0})
    assert numpy.array_equal(out[..., 0], out[..., 1])
    assert numpy.array_equal(out[..., 1], out[..., 2])


def test_acros_pro_output_has_equal_channels_at_several_fractional_intensities():
    image = _image()
    for intensity in (0.01, 0.25, 0.5, 0.75, 0.99):
        out = film_look(image, {"look": "acros_pro", "intensity": intensity})
        assert numpy.array_equal(out[..., 0], out[..., 1]), f"R != G at intensity={intensity}"
        assert numpy.array_equal(out[..., 1], out[..., 2]), f"G != B at intensity={intensity}"


# Retired 2026-07-16 alongside "Acros" itself -- comparing against a look
# that now falls back to identity no longer tests anything meaningful, so
# this test was removed.


def test_acros_pro_grain_is_stronger_in_shadows_than_highlights():
    dark = numpy.full((60, 60, 3), 20, dtype=numpy.uint8)
    bright = numpy.full((60, 60, 3), 235, dtype=numpy.uint8)
    dark_out = film_look(dark, {"look": "acros_pro", "intensity": 1.0}).astype(numpy.float32)
    bright_out = film_look(bright, {"look": "acros_pro", "intensity": 1.0}).astype(numpy.float32)
    assert float(dark_out[..., 0].std()) > float(bright_out[..., 0].std())


def test_acros_pro_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "acros_pro", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_acros_pro_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "acros_pro", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_acros_pro_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "acros_pro", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_acros_pro_deep_shadows_are_crushed_toward_black():
    dark = numpy.full((30, 30, 3), 12, dtype=numpy.uint8)
    out = film_look(dark, {"look": "acros_pro", "intensity": 1.0})
    assert float(out.astype(numpy.float32).mean()) < 12.0


# ---------------------------------------------------------------------------
# Astia -- soft contrast, brightened skin tones, restrained color. First
# consumer of the `hsl_luminance` field/primitive.
# ---------------------------------------------------------------------------


def test_astia_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "astia", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_astia_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _ASTIA_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _ASTIA_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_astia_orange_hue_is_brightened():
    orange = numpy.zeros((1, 1, 3), dtype=numpy.uint8)
    orange[0, 0] = (200, 130, 60)  # a skin-tone-ish orange
    out = film_look(orange, {"look": "astia", "intensity": 1.0})
    _, _, luminance_before = _rgb_to_hsl(orange.astype(numpy.float32))
    _, _, luminance_after = _rgb_to_hsl(out.astype(numpy.float32))
    # highlights=-15 also pulls bright luminance down, so this only checks the
    # hsl_luminance nudge is exercised through the full pipeline, not a
    # specific direction -- the isolated primitive tests above already prove
    # the primitive itself brightens "orange".
    assert luminance_after[0, 0] != luminance_before[0, 0]


def test_astia_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "astia", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_astia_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "astia", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# ---------------------------------------------------------------------------
# Pro Neg. Std -- neutral, malleable rendering, soft gradients, natural skin
# tones.
# ---------------------------------------------------------------------------


def test_pro_neg_std_decreases_saturation_relative_to_input():
    image = _image()
    out = film_look(image, {"look": "pro_neg_std", "intensity": 1.0})
    assert _mean_saturation(out) < _mean_saturation(image)


def test_pro_neg_std_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "pro_neg_std", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_pro_neg_std_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _PRO_NEG_STD_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _PRO_NEG_STD_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_pro_neg_std_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "pro_neg_std", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_pro_neg_std_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "pro_neg_std", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# ---------------------------------------------------------------------------
# Eterna -- soft cinema-style curve, very progressive highlights, open
# shadows, contained color.
# ---------------------------------------------------------------------------


def test_eterna_decreases_saturation_relative_to_input():
    image = _image()
    out = film_look(image, {"look": "eterna", "intensity": 1.0})
    assert _mean_saturation(out) < _mean_saturation(image)


def test_eterna_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "eterna", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_eterna_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _ETERNA_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _ETERNA_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_eterna_deep_shadows_are_lifted_not_crushed():
    """Eterna's shadows=+25 (opens shadows) is the opposite direction from
    Acros Pro's black_clip-driven crush -- confirms the sign/effect actually
    reproduced is "open shadows", the calibration's own stated intent.
    """
    dark = numpy.full((30, 30, 3), 40, dtype=numpy.uint8)
    out = film_look(dark, {"look": "eterna", "intensity": 1.0})
    assert float(out.astype(numpy.float32).mean()) > 40.0


def test_eterna_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "eterna", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_eterna_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "eterna", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# ---------------------------------------------------------------------------
# Eterna Bleach Bypass -- near-monochrome, cold, metallic, heavily contrasted.
# Not a `monochrome_weights` look (no hard R==G==B guarantee) -- the near-mono
# effect comes from the heavy global_saturation crush (x0.30) instead.
# ---------------------------------------------------------------------------


def test_eterna_bleach_bypass_decreases_saturation_much_more_than_eterna():
    image = _image()
    eterna_out = film_look(image, {"look": "eterna", "intensity": 1.0})
    bleach_out = film_look(image, {"look": "eterna_bleach_bypass", "intensity": 1.0})
    assert _mean_saturation(bleach_out) < _mean_saturation(eterna_out)


def test_eterna_bleach_bypass_increases_contrast_relative_to_input():
    dark = numpy.full((20, 20, 3), 40, dtype=numpy.uint8)
    bright = numpy.full((20, 20, 3), 220, dtype=numpy.uint8)
    dark_out = film_look(dark, {"look": "eterna_bleach_bypass", "intensity": 1.0})
    bright_out = film_look(bright, {"look": "eterna_bleach_bypass", "intensity": 1.0})
    # Contrast=+45 pushes the dark patch darker and the bright patch brighter,
    # widening the gap relative to the raw 40/220 input gap.
    assert float(bright_out.astype(numpy.float32).mean()) - float(dark_out.astype(numpy.float32).mean()) > 180.0


def test_eterna_bleach_bypass_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "eterna_bleach_bypass", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_eterna_bleach_bypass_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _ETERNA_BLEACH_BYPASS_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _ETERNA_BLEACH_BYPASS_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_eterna_bleach_bypass_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "eterna_bleach_bypass", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_eterna_bleach_bypass_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "eterna_bleach_bypass", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# ---------------------------------------------------------------------------
# Pre-existing looks are unaffected by the three new engine fields (2026-07-25)
# -- every _GRADES entry that predates Summer Story/Inky Depths must default
# every new field to its no-op value, or the shared rendering pipeline (which
# now unconditionally resolves Dynamic Range and runs the Color Chrome
# primitives for every look) would silently change their output.
# ---------------------------------------------------------------------------


def test_pre_existing_looks_default_the_three_new_fields_to_their_noop_value():
    for look in _PRE_EXISTING_LOOKS:
        grade = _GRADES[look]
        assert grade.color_chrome_effect == 0.0, look
        assert grade.color_chrome_blue == 0.0, look
        assert grade.dynamic_range == 0.0, look


# ---------------------------------------------------------------------------
# Summer Story -- retired 2026-07-27 (user request, see film.py's module
# docstring). "summer_story" no longer resolves (removed from _LOOKS/
# _LOOK_TRANSFORMS/_GRADES/ADDON_DESCRIPTION.thumbnail_presets), and
# _SUMMER_STORY_GRADE was removed from its source -- these tests would only
# exercise the now-retired look, so they were removed too, the same way
# test_classic_chrome_pro_is_distinct_from_classic_chrome above was for the
# 2026-07-16 retirement.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Inky Depths -- built on Eterna Bleach Bypass: pushed highlights, richer
# shadows, heavily desaturated, sharper, weak+large grain, a cool
# "Underwater"-preset White Balance push, DR200, strong Color Chrome Effect.
# EV Comp./ISO N.R. from the source recipe are deliberately not implemented
# (module docstring).
# ---------------------------------------------------------------------------


def test_inky_depths_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "inky_depths", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_inky_depths_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _INKY_DEPTHS_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _INKY_DEPTHS_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_inky_depths_decreases_saturation_much_more_than_eterna_bleach_bypass():
    """Colour -4 (Fuji scale) on top of Eterna Bleach Bypass's already-heavy
    0.30 global_saturation crush -- must desaturate further, not less.
    """
    image = _image()
    bleach_out = film_look(image, {"look": "eterna_bleach_bypass", "intensity": 1.0})
    inky_out = film_look(image, {"look": "inky_depths", "intensity": 1.0})
    assert _mean_saturation(inky_out) < _mean_saturation(bleach_out)


def test_inky_depths_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "inky_depths", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_inky_depths_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "inky_depths", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# ---------------------------------------------------------------------------
# Classic Negative -- a new base film simulation (2026-07-25, documented
# approximation, see _CLASSIC_NEGATIVE_GRADE's own comment in film.py),
# exposed standalone and reused as the base for 4 of the 5 "Bleach Bypass"
# recipes below.
# ---------------------------------------------------------------------------


def test_classic_negative_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "classic_negative", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_classic_negative_decreases_saturation_relative_to_input():
    image = _image()
    out = film_look(image, {"look": "classic_negative", "intensity": 1.0})
    assert _mean_saturation(out) < _mean_saturation(image)


def test_classic_negative_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _CLASSIC_NEGATIVE_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _CLASSIC_NEGATIVE_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_classic_negative_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "classic_negative", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_classic_negative_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "classic_negative", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_classic_negative_is_distinct_from_classic_chrome_and_eterna_bleach_bypass():
    image = _image()
    classic_negative_out = film_look(image, {"look": "classic_negative", "intensity": 1.0})
    classic_chrome_out = film_look(image, {"look": "classic_chrome_pro", "intensity": 1.0})
    eterna_bleach_bypass_out = film_look(image, {"look": "eterna_bleach_bypass", "intensity": 1.0})
    assert not numpy.array_equal(classic_negative_out, classic_chrome_out)
    assert not numpy.array_equal(classic_negative_out, eterna_bleach_bypass_out)


# ---------------------------------------------------------------------------
# "Bleach Bypass" recipes (2026-07-25) -- Ecowarrior (built on Eterna Bleach
# Bypass) and Loki/Sunset Strip/Rizzle Clicks/Glacier Blue (built on Classic
# Negative). Moved into their own workflow row alongside Eterna Bleach
# Bypass/Inky Depths (config_workflow.json's "bleach_bypass" row, same
# film_look addon) -- no engine change for that move, only the recipes
# themselves are new code. Same per-preset test pattern as every other look.
# ---------------------------------------------------------------------------


def test_ecowarrior_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "ecowarrior", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_ecowarrior_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _ECOWARRIOR_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _ECOWARRIOR_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_ecowarrior_is_distinct_from_its_eterna_bleach_bypass_base():
    image = _image()
    base_out = film_look(image, {"look": "eterna_bleach_bypass", "intensity": 1.0})
    ecowarrior_out = film_look(image, {"look": "ecowarrior", "intensity": 1.0})
    assert not numpy.array_equal(base_out, ecowarrior_out)


def test_ecowarrior_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "ecowarrior", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_ecowarrior_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "ecowarrior", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_loki_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "loki", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_loki_has_no_grain():
    """Grain Effect Off (grain_std=0.0) -- unlike every other new recipe,
    Loki has zero grain, so this asserts a no-visible-grain outcome instead
    of every other preset's "grain has a visible effect" pattern.
    """
    image = _image()
    out = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _LOKI_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _LOKI_GRADE._replace(grain_std=0.0)
    also_out = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert numpy.array_equal(out, also_out)


def test_loki_is_distinct_from_its_classic_negative_base():
    image = _image()
    base_out = film_look(image, {"look": "classic_negative", "intensity": 1.0})
    loki_out = film_look(image, {"look": "loki", "intensity": 1.0})
    assert not numpy.array_equal(base_out, loki_out)


def test_loki_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "loki", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_loki_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "loki", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_sunset_strip_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "sunset_strip", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_sunset_strip_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _SUNSET_STRIP_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _SUNSET_STRIP_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_sunset_strip_is_distinct_from_its_classic_negative_base():
    image = _image()
    base_out = film_look(image, {"look": "classic_negative", "intensity": 1.0})
    sunset_strip_out = film_look(image, {"look": "sunset_strip", "intensity": 1.0})
    assert not numpy.array_equal(base_out, sunset_strip_out)


def test_sunset_strip_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "sunset_strip", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_sunset_strip_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "sunset_strip", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_rizzle_clicks_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "rizzle_clicks", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_rizzle_clicks_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _RIZZLE_CLICKS_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _RIZZLE_CLICKS_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_rizzle_clicks_is_distinct_from_its_classic_negative_base():
    image = _image()
    base_out = film_look(image, {"look": "classic_negative", "intensity": 1.0})
    rizzle_clicks_out = film_look(image, {"look": "rizzle_clicks", "intensity": 1.0})
    assert not numpy.array_equal(base_out, rizzle_clicks_out)


def test_rizzle_clicks_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "rizzle_clicks", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_rizzle_clicks_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "rizzle_clicks", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_glacier_blue_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "glacier_blue", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_glacier_blue_has_no_grain():
    """Grain Effect Off (grain_std=0.0), like Loki -- see test_loki_has_no_grain."""
    image = _image()
    out = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _GLACIER_BLUE_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _GLACIER_BLUE_GRADE._replace(grain_std=0.0)
    also_out = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert numpy.array_equal(out, also_out)


def test_glacier_blue_decreases_saturation_relative_to_its_classic_negative_base():
    """Colour -4 (Fuji scale) on top of Classic Negative's own moderate
    desaturation -- must desaturate further, not less.
    """
    image = _image()
    base_out = film_look(image, {"look": "classic_negative", "intensity": 1.0})
    glacier_blue_out = film_look(image, {"look": "glacier_blue", "intensity": 1.0})
    assert _mean_saturation(glacier_blue_out) < _mean_saturation(base_out)


def test_glacier_blue_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "glacier_blue", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_glacier_blue_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "glacier_blue", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# ---------------------------------------------------------------------------
# "Mono Colour" (WC/MG) primitive (2026-07-26) -- a color-toning pass
# specific to monochrome_weights looks, distinct from White Balance (which
# now also affects this path -- see the bug-fix tests further below). Pure
# unit tests, independent of any specific recipe.
# ---------------------------------------------------------------------------


def test_mono_color_to_temperature_tint_is_noop_at_zero():
    assert _mono_color_to_temperature_tint(0.0, 0.0) == (0.0, 0.0)


def test_mono_color_to_temperature_tint_positive_wc_warms():
    temperature, _tint = _mono_color_to_temperature_tint(1.0, 0.0)
    assert temperature > 0.0


def test_mono_color_to_temperature_tint_negative_wc_cools():
    temperature, _tint = _mono_color_to_temperature_tint(-1.0, 0.0)
    assert temperature < 0.0


def test_mono_color_to_temperature_tint_mg_maps_to_tint_only():
    temperature, tint = _mono_color_to_temperature_tint(0.0, 1.0)
    assert temperature == 0.0
    assert tint != 0.0


def test_mono_color_to_temperature_tint_clips_to_bounds():
    temperature, tint = _mono_color_to_temperature_tint(1000.0, 1000.0)
    assert temperature == 1000.0
    assert tint == 20.0
    temperature, tint = _mono_color_to_temperature_tint(-1000.0, -1000.0)
    assert temperature == -1000.0
    assert tint == -20.0


def test_apply_monochrome_grade_mono_colour_has_a_visible_effect():
    image = _image()
    grade = _ACROS_PRO_GRADE._replace(mono_color_wc=6.0, mono_color_mg=3.0)
    with_mono_colour = _apply_monochrome_grade(image.astype(numpy.float32), grade)
    without_mono_colour = _apply_monochrome_grade(image.astype(numpy.float32), _ACROS_PRO_GRADE)
    assert not numpy.array_equal(with_mono_colour, without_mono_colour)


def test_apply_monochrome_grade_white_balance_bug_fix_has_a_visible_effect():
    """2026-07-26 bug fix: temperature/tint (White Balance) were previously
    silently ignored on the monochrome path -- now applied to the source
    image before the custom-weighted grayscale conversion.
    """
    image = _image()
    grade = _ACROS_PRO_GRADE._replace(temperature=500.0, tint=10.0)
    with_wb = _apply_monochrome_grade(image.astype(numpy.float32), grade)
    without_wb = _apply_monochrome_grade(image.astype(numpy.float32), _ACROS_PRO_GRADE)
    assert not numpy.array_equal(with_wb, without_wb)


def test_apply_monochrome_grade_acros_pro_matches_zeroed_new_fields():
    """Acros Pro's own calibration has temperature=tint=mono_color_wc=
    mono_color_mg=0.0 (every one of this feature's touched fields). Combined
    with test_apply_temperature_tint_zero_is_exact_identity and
    test_mono_color_to_temperature_tint_is_noop_at_zero (both of which prove
    the two new calls this feature adds are exact identities at 0.0), this
    confirms _apply_monochrome_grade has no way to diverge for Acros Pro --
    no regression for the only pre-existing monochrome look. Every
    pre-existing Acros Pro test above (deterministic/equal-channel/grain/
    mutation/shape) also still passes unmodified, which is the real proof.
    """
    image = _image().astype(numpy.float32)
    out = _apply_monochrome_grade(image, _ACROS_PRO_GRADE)
    explicitly_zeroed = _ACROS_PRO_GRADE._replace(
        temperature=0.0, tint=0.0, mono_color_wc=0.0, mono_color_mg=0.0,
    )
    also_out = _apply_monochrome_grade(image, explicitly_zeroed)
    assert numpy.array_equal(out, also_out)


# ---------------------------------------------------------------------------
# "Monochrome" workflow row recipes (2026-07-26) -- Monochrome and Mono
# Moonlight (built on the new, module-internal _MONOCHROME_BASE_GRADE, not
# itself a selectable look), Titanium (Eterna Bleach Bypass), Underglow
# (Classic Negative), Gilt Trip (Acros Pro), Milestone/Quicklime (Classic
# Chrome Pro). Same per-preset test pattern as every other look.
#
# "Monochrome" (the recipe/vignette) itself retired 2026-07-27 (user request,
# see film.py's module docstring) -- "monochrome" no longer resolves, so its
# tests were removed. The row (still named "Monochrome") and
# _MONOCHROME_BASE_GRADE both stay -- Titanium/Mono Moonlight/Milestone/
# Quicklime are unaffected.
# ---------------------------------------------------------------------------


def test_titanium_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "titanium", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_titanium_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _TITANIUM_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _TITANIUM_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_titanium_is_distinct_from_its_eterna_bleach_bypass_base():
    image = _image()
    base_out = film_look(image, {"look": "eterna_bleach_bypass", "intensity": 1.0})
    titanium_out = film_look(image, {"look": "titanium", "intensity": 1.0})
    assert not numpy.array_equal(base_out, titanium_out)


def test_titanium_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "titanium", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_titanium_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "titanium", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# Mono Moonlight retired 2026-08-04 (user request, see film.py's module
# docstring) -- its tests were removed.


# Underglow retired 2026-07-27 (user request, see film.py's module
# docstring) -- its tests were removed.


# Gilt Trip retired 2026-07-27 (user request, see film.py's module
# docstring) -- its tests were removed.


def test_milestone_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "milestone", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_milestone_has_no_grain():
    """Grain Effect Off (grain_std=0.0), like Loki -- see test_loki_has_no_grain."""
    image = _image()
    out = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _MILESTONE_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _MILESTONE_GRADE._replace(grain_std=0.0)
    also_out = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert numpy.array_equal(out, also_out)


def test_milestone_is_distinct_from_its_classic_chrome_base():
    image = _image()
    base_out = film_look(image, {"look": "classic_chrome_pro", "intensity": 1.0})
    milestone_out = film_look(image, {"look": "milestone", "intensity": 1.0})
    assert not numpy.array_equal(base_out, milestone_out)


def test_milestone_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "milestone", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_milestone_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "milestone", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_quicklime_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "quicklime", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_quicklime_has_no_grain():
    """Grain Effect Off (grain_std=0.0), like Loki -- see test_loki_has_no_grain."""
    image = _image()
    out = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), _QUICKLIME_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _QUICKLIME_GRADE._replace(grain_std=0.0)
    also_out = numpy.clip(
        _apply_parametric_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert numpy.array_equal(out, also_out)


def test_quicklime_is_distinct_from_its_classic_chrome_base():
    image = _image()
    base_out = film_look(image, {"look": "classic_chrome_pro", "intensity": 1.0})
    quicklime_out = film_look(image, {"look": "quicklime", "intensity": 1.0})
    assert not numpy.array_equal(base_out, quicklime_out)


def test_quicklime_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "quicklime", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_quicklime_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "quicklime", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# ---------------------------------------------------------------------------
# Pre-existing looks (predating this feature) are unaffected by the two new
# engine fields (2026-07-26) -- every _GRADES entry that predates Monochrome/
# Mono Moonlight/Gilt Trip must default mono_color_wc/mono_color_mg to their
# no-op value, or the shared rendering pipeline would silently change their
# output.
# ---------------------------------------------------------------------------


def test_pre_existing_looks_default_mono_colour_fields_to_their_noop_value():
    for look in _PRE_EXISTING_LOOKS + _NEW_LOOKS:
        grade = _GRADES[look]
        assert grade.mono_color_wc == 0.0, look
        assert grade.mono_color_mg == 0.0, look


# ---------------------------------------------------------------------------
# Acros Yellow/Green Filter (2026-07-26) -- module-internal calibration
# anchors, not standalone selectable looks: only `monochrome_weights` differs
# from Acros Pro, everything else inherited unchanged.
# ---------------------------------------------------------------------------


def test_acros_yellow_filter_weights_differ_from_acros_pro_and_are_not_a_selectable_look():
    assert _ACROS_YELLOW_FILTER_GRADE.monochrome_weights != _ACROS_PRO_GRADE.monochrome_weights
    assert "acros_yellow_filter" not in _GRADES
    assert "Acros Yellow Filter" not in {p.identifier for p in ADDON_DESCRIPTION.thumbnail_presets}


def test_acros_yellow_filter_inherits_every_other_field_from_acros_pro():
    assert _ACROS_YELLOW_FILTER_GRADE._replace(monochrome_weights=_ACROS_PRO_GRADE.monochrome_weights) == _ACROS_PRO_GRADE


def test_acros_green_filter_weights_differ_from_acros_pro_and_yellow_filter():
    assert _ACROS_GREEN_FILTER_GRADE.monochrome_weights != _ACROS_PRO_GRADE.monochrome_weights
    assert _ACROS_GREEN_FILTER_GRADE.monochrome_weights != _ACROS_YELLOW_FILTER_GRADE.monochrome_weights
    assert "acros_green_filter" not in _GRADES
    assert "Acros Green Filter" not in {p.identifier for p in ADDON_DESCRIPTION.thumbnail_presets}


def test_acros_green_filter_inherits_every_other_field_from_acros_pro():
    assert _ACROS_GREEN_FILTER_GRADE._replace(monochrome_weights=_ACROS_PRO_GRADE.monochrome_weights) == _ACROS_PRO_GRADE


# ---------------------------------------------------------------------------
# B&W colored-filter selector (2026-08-04) -- _resolve_filter_weights/
# _FILTER_WEIGHTS_TABLE, the mechanism behind the "Filtre" Zoom overlay
# section and the four "Acros + Couleur" presets below.
# ---------------------------------------------------------------------------


def test_resolve_filter_weights_none_at_filter_color_zero():
    assert _resolve_filter_weights(0.0, 1.0) is None


def test_resolve_filter_weights_yellow_moderate_matches_existing_anchor():
    assert _resolve_filter_weights(1.0, 1.0) == _ACROS_YELLOW_FILTER_GRADE.monochrome_weights


def test_resolve_filter_weights_green_moderate_matches_existing_anchor():
    assert _resolve_filter_weights(3.0, 1.0) == _ACROS_GREEN_FILTER_GRADE.monochrome_weights


def test_resolve_filter_weights_every_row_sums_to_one():
    for color in (1, 2, 3, 4):
        for intensity in (0, 1, 2):
            weights = _FILTER_WEIGHTS_TABLE[color][intensity]
            assert abs(sum(weights) - 1.0) < 1e-9, (color, intensity, weights)


def test_resolve_filter_weights_clips_and_rounds_out_of_range_input():
    assert _resolve_filter_weights(4.6, -1.0) == _FILTER_WEIGHTS_TABLE[4][0]


# ---------------------------------------------------------------------------
# "B&W" workflow row recipes (2026-07-26, later the same day) -- Daido
# Moriyama (a deliberate duplicate of Monochrome, independent constant per
# explicit user request, retired 2026-08-04), Newsprint (Acros Yellow
# Filter), Silvertone 99 (Acros Green Filter) (both retired 2026-08-05, user
# request). Same per-preset test pattern as every other look. "Acros" itself
# moved into this row too (config_workflow.json only, no new grade -- already
# covered by every pre-existing Acros Pro test above).
# ---------------------------------------------------------------------------


# "Monochrome" itself retired 2026-07-27 (user request) -- _MONOCHROME_GRADE
# no longer exists to compare against, so this documentation-only test was
# removed; the historical fact it recorded (a deliberate field-for-field
# duplicate at authoring time) still holds for _DAIDO_MORIYAMA_GRADE's own
# values, just no longer independently checkable against a live sibling
# constant.


# Daido Moriyama retired 2026-08-04 (user request, see film.py's module
# docstring) -- its tests were removed.


# Newsprint/Silvertone 99 retired 2026-08-05 (user request, see film.py's
# module docstring) -- their tests were removed.


# ---------------------------------------------------------------------------
# "Acros + Yellow/Red/Green/Blue" presets (2026-08-04) -- plain Acros Pro plus
# a filter_color/filter_intensity override (see ThumbnailPreset's own
# comment for why this reuses the override mechanism instead of a dedicated
# _GradeParams each). "Acros + Yellow"/"Acros + Green" at their Modéré default
# are bit-identical to the pre-existing direct _ACROS_YELLOW_FILTER_GRADE/
# _ACROS_GREEN_FILTER_GRADE recipes (same underlying weights) -- a useful
# non-regression anchor.
# ---------------------------------------------------------------------------

_ACROS_FILTER_PRESETS = {
    "Acros + Yellow": 1.0,
    "Acros + Red": 2.0,
    "Acros + Green": 3.0,
    "Acros + Blue": 4.0,
}


def test_acros_filter_presets_deterministic_repeat_call_is_byte_identical():
    image = _image()
    for filter_color in _ACROS_FILTER_PRESETS.values():
        params = {"look": "acros_pro", "intensity": 1.0, "filter_color": filter_color, "filter_intensity": 1.0}
        out1 = film_look(image, params)
        out2 = film_look(image, params)
        assert numpy.array_equal(out1, out2), filter_color


def test_acros_filter_presets_output_shape_and_dtype_unchanged():
    image = _image()
    for filter_color in _ACROS_FILTER_PRESETS.values():
        out = film_look(
            image, {"look": "acros_pro", "intensity": 1.0, "filter_color": filter_color, "filter_intensity": 1.0}
        )
        assert out.shape == image.shape, filter_color
        assert out.dtype == numpy.uint8, filter_color


def test_acros_filter_presets_do_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    for filter_color in _ACROS_FILTER_PRESETS.values():
        film_look(
            image, {"look": "acros_pro", "intensity": 0.6, "filter_color": filter_color, "filter_intensity": 1.0}
        )
        assert numpy.array_equal(image, snapshot), filter_color


def test_acros_filter_presets_are_distinct_from_plain_acros_pro():
    image = _image()
    acros_pro_out = film_look(image, {"look": "acros_pro", "intensity": 1.0})
    for identifier, filter_color in _ACROS_FILTER_PRESETS.items():
        out = film_look(
            image, {"look": "acros_pro", "intensity": 1.0, "filter_color": filter_color, "filter_intensity": 1.0}
        )
        assert not numpy.array_equal(acros_pro_out, out), identifier


def test_acros_filter_presets_are_distinct_from_each_other():
    image = _image()
    outputs = {
        identifier: film_look(
            image, {"look": "acros_pro", "intensity": 1.0, "filter_color": filter_color, "filter_intensity": 1.0}
        )
        for identifier, filter_color in _ACROS_FILTER_PRESETS.items()
    }
    names = list(outputs)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            assert not numpy.array_equal(outputs[a], outputs[b]), f"{a} == {b}"


def test_acros_yellow_preset_matches_direct_acros_yellow_filter_grade():
    image = _image()
    via_preset = film_look(
        image, {"look": "acros_pro", "intensity": 1.0, "filter_color": 1.0, "filter_intensity": 1.0}
    )
    direct = numpy.clip(
        _apply_monochrome_grade(image.astype(numpy.float32), _ACROS_YELLOW_FILTER_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    assert numpy.array_equal(via_preset, direct)


def test_acros_green_preset_matches_direct_acros_green_filter_grade():
    image = _image()
    via_preset = film_look(
        image, {"look": "acros_pro", "intensity": 1.0, "filter_color": 3.0, "filter_intensity": 1.0}
    )
    direct = numpy.clip(
        _apply_monochrome_grade(image.astype(numpy.float32), _ACROS_GREEN_FILTER_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    assert numpy.array_equal(via_preset, direct)


# ---------------------------------------------------------------------------
# Zoom overlay "Réglages manuels" sliders (2026-07-22, switched to an
# ABSOLUTE-value model the same day after user feedback -- see film.py's
# _apply_grade_overrides/resolve_zoom_values docstrings). Every existing test
# above already proves the no-override path (no override keys present, e.g. a
# plain {"look": ..., "intensity": ...} thumbnail selection) is byte-identical
# to pre-feature behavior -- these tests cover the override path itself plus
# resolve_zoom_values.
# ---------------------------------------------------------------------------


def test_grade_overrides_absent_returns_the_same_object():
    for look in _ALL_LOOKS:
        base = _GRADES[look]
        assert _apply_grade_overrides(base, {}) is base
        assert _apply_grade_overrides(base, {"look": look, "intensity": 1.0}) is base


def test_grade_overrides_at_the_looks_own_values_is_bit_identical():
    """Explicitly overriding every absolute field to the look's OWN current
    value (i.e. no real change) must reproduce the base grade exactly -- this
    is what keeps ordinary preset rendering (thumbnails, preview, export)
    unaffected once a slider has been touched but left at its seeded value.

    highlights/shadows/black_clip are sourced from `resolve_zoom_values`
    (the Zoom slider's actual seed), not the raw `_GradeParams` field, since
    (2026-07-25) those two can differ for a `dynamic_range != 0` look -- see
    resolve_zoom_values's own DR-composition tests further down for why the
    seed, not the raw field, is the value a real override would ever be."""
    image = _image()
    for look in _ALL_LOOKS:
        grade = _GRADES[look]
        seeded = resolve_zoom_values({"look": look, "intensity": 1.0})
        own_values = {name: getattr(grade, name) for name in (
            "contrast", "global_saturation",
            "temperature", "tint", "clarity", "sharpness", "grain_std",
            "color_chrome_effect", "color_chrome_blue", "dynamic_range",
            "mono_color_wc", "mono_color_mg",
        )}
        own_values["highlights"] = seeded["highlights"]
        own_values["shadows"] = seeded["shadows"]
        own_values["black_clip"] = seeded["black_clip"]
        own_values["hsl_saturation_scale"] = 1.0
        own_values["hsl_luminance_scale"] = 1.0
        own_values["split_tone_scale"] = 1.0
        with_own_values = film_look(image, {"look": look, "intensity": 1.0, **own_values})
        without = film_look(image, {"look": look, "intensity": 1.0})
        assert numpy.array_equal(with_own_values, without)


def test_grade_overrides_absolute_value_replaces_the_looks_own_value():
    grade = _GRADES["astia"]
    overridden = _apply_grade_overrides(grade, {"contrast": 55.0})
    assert overridden.contrast == 55.0
    assert overridden is not grade


def test_grade_overrides_clip_to_field_bounds():
    grade = _GRADES["velvia_pro"]
    overridden = _apply_grade_overrides(grade, {"contrast": 1000.0, "shadows": -1000.0})
    assert overridden.contrast == 100.0
    assert overridden.shadows == -100.0


def test_grade_overrides_absence_of_key_leaves_field_untouched():
    grade = _GRADES["velvia_pro"]
    overridden = _apply_grade_overrides(grade, {"contrast": 55.0})
    # highlights was never mentioned -- must pass through the look's own
    # value exactly, not some neutral/default value.
    assert overridden.highlights == grade.highlights


def test_grade_overrides_hsl_saturation_scale_multiplies_every_named_hue():
    grade = _GRADES["velvia_pro"]
    overridden = _apply_grade_overrides(grade, {"hsl_saturation_scale": 0.5})
    for name, value in grade.hsl_saturation.items():
        assert overridden.hsl_saturation[name] == value * 0.5


def test_grade_overrides_split_tone_scale_scales_both_shadow_and_highlight_strength():
    grade = _GRADES["classic_chrome_pro"]
    overridden = _apply_grade_overrides(grade, {"split_tone_scale": 2.0})
    assert overridden.split_tone_shadow_strength == min(grade.split_tone_shadow_strength * 2.0, 20.0)
    assert overridden.split_tone_highlight_strength == min(grade.split_tone_highlight_strength * 2.0, 20.0)
    # Hue is untouched by split_tone_scale, only strength.
    assert overridden.split_tone_shadow_hue == grade.split_tone_shadow_hue
    assert overridden.split_tone_highlight_hue == grade.split_tone_highlight_hue


def test_grade_overrides_do_not_touch_monochrome_weights_or_grain_size():
    grade = _GRADES["acros_pro"]
    overridden = _apply_grade_overrides(grade, {"contrast": 55.0})
    assert overridden.monochrome_weights == grade.monochrome_weights
    assert overridden.grain_size == grade.grain_size
    assert overridden.grain_std_shadow_boost == grade.grain_std_shadow_boost


def test_grade_overrides_filter_color_zero_is_noop():
    grade = _GRADES["acros_pro"]
    assert _apply_grade_overrides(grade, {"filter_color": 0.0}) is grade


def test_grade_overrides_filter_color_sets_monochrome_weights_on_a_color_look():
    grade = _GRADES["velvia_pro"]
    assert grade.monochrome_weights is None
    overridden = _apply_grade_overrides(grade, {"filter_color": 2.0, "filter_intensity": 1.0})
    assert overridden.monochrome_weights == _FILTER_WEIGHTS_TABLE[2][1]


def test_grade_overrides_filter_intensity_defaults_to_moderate():
    grade = _GRADES["acros_pro"]
    overridden = _apply_grade_overrides(grade, {"filter_color": 1.0})
    assert overridden.monochrome_weights == _ACROS_YELLOW_FILTER_GRADE.monochrome_weights


def test_grade_overrides_filter_intensity_alone_without_filter_color_is_noop():
    grade = _GRADES["acros_pro"]
    assert _apply_grade_overrides(grade, {"filter_intensity": 2.0}) is grade


def test_film_look_filter_override_forces_monochrome_dispatch_on_a_color_look():
    image = _image()
    out = film_look(image, {"look": "velvia_pro", "intensity": 1.0, "filter_color": 3.0, "filter_intensity": 1.0})
    assert numpy.array_equal(out[..., 0], out[..., 1])
    assert numpy.array_equal(out[..., 1], out[..., 2])


def test_film_look_applies_overrides_and_produces_a_visibly_different_result():
    image = _image()
    plain = film_look(image, {"look": "velvia_pro", "intensity": 1.0})
    boosted = film_look(image, {"look": "velvia_pro", "intensity": 1.0, "contrast": 90.0})
    assert not numpy.array_equal(plain, boosted)
    assert boosted.shape == image.shape
    assert boosted.dtype == numpy.uint8


def test_film_look_overrides_do_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "eterna", "intensity": 1.0, "grain_std": 0.03, "clarity": -80.0})
    assert numpy.array_equal(image, snapshot)


def test_film_look_overrides_ignored_for_unrecognized_look():
    image = _image()
    out = film_look(image, {"look": "sepia", "intensity": 1.0, "contrast": 90.0})
    assert numpy.array_equal(out, image)


# ---------------------------------------------------------------------------
# Neutral (missing `look`) + Zoom overrides -- bug fix 2026-07-23: dragging a
# manual slider on the Film row's "Neutral" vignette used to have no effect
# at all, because `film_look` discarded every param as soon as it saw
# `look not in _GRADES` -- true for `None` (Neutral) as much as for a real
# unrecognized name. Neutral now routes through the same parametric engine,
# starting from an all-defaults grade, but ONLY once an override is present.
# ---------------------------------------------------------------------------


def test_film_look_neutral_with_override_visibly_changes_the_image():
    image = _image()
    out = film_look(image, {"contrast": 90.0})
    assert not numpy.array_equal(out, image)
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_film_look_neutral_without_override_stays_bit_identical():
    image = _image()
    # `intensity` alone is not a grade-affecting key -- against an
    # all-defaults grade it would blend toward an identical output anyway,
    # but it must not even trigger the parametric engine.
    out = film_look(image, {"intensity": 0.5})
    assert numpy.array_equal(out, image)


def test_film_look_neutral_default_intensity_is_full_effect():
    image = _image()
    # No "intensity" key at all (the real shape of step.parameters.values
    # right after a slider edit on a freshly-selected Neutral vignette) must
    # still apply the override at full strength, not silently do nothing.
    with_default_intensity = film_look(image, {"contrast": 90.0})
    with_explicit_full_intensity = film_look(image, {"contrast": 90.0, "intensity": 1.0})
    assert numpy.array_equal(with_default_intensity, with_explicit_full_intensity)
    assert not numpy.array_equal(with_default_intensity, image)


def test_film_look_acros_pro_stays_equal_channel_with_overrides():
    image = _image()
    out = film_look(
        image, {"look": "acros_pro", "intensity": 1.0, "contrast": 60.0, "grain_std": 0.03}
    )
    assert numpy.array_equal(out[..., 0], out[..., 1])
    assert numpy.array_equal(out[..., 1], out[..., 2])


# ---------------------------------------------------------------------------
# Kodak T-MAX / Kodak T-MAX 3200 / Kodak Tri-X (2026-08-05) -- three more
# "B&W" row presets. Kodak T-MAX builds on the module-internal Monochrome
# base (_MONOCHROME_BASE_GRADE, not itself a selectable look -- same
# "is_distinct_from_its_base" pattern as the retired "Monochrome" look used);
# Kodak T-MAX 3200 and Kodak Tri-X build on Acros Pro. All three also
# exercise the film_look equal-channel-base generalization from
# `look == "acros_pro"` to `grade.monochrome_weights is not None` (module
# docstring) via their own fractional-intensity equal-channel tests below.
# ---------------------------------------------------------------------------


# Retired 2026-08-05 (still later the same day, user request, see the module
# docstring) -- "kodak_tmax" is no longer importable, so its tests were
# removed too.


def test_kodak_tmax_3200_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "kodak_tmax_3200", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_kodak_tmax_3200_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_monochrome_grade(image.astype(numpy.float32), _KODAK_TMAX_3200_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _KODAK_TMAX_3200_GRADE._replace(grain_std=0.0, grain_std_shadow_boost=0.0)
    without_grain = numpy.clip(
        _apply_monochrome_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_kodak_tmax_3200_is_distinct_from_its_acros_pro_base():
    image = _image()
    base_out = film_look(image, {"look": "acros_pro", "intensity": 1.0})
    kodak_tmax_3200_out = film_look(image, {"look": "kodak_tmax_3200", "intensity": 1.0})
    assert not numpy.array_equal(base_out, kodak_tmax_3200_out)


def test_kodak_tmax_3200_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "kodak_tmax_3200", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_kodak_tmax_3200_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "kodak_tmax_3200", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# No "output_has_equal_channels_at_several_fractional_intensities" test for
# Kodak T-MAX 3200, unlike its two siblings above/below -- its non-zero
# mono_color_wc/mono_color_mg (Mono Colour toning) deliberately introduces a
# color cast on the already-gray image (_apply_monochrome_grade's own
# mono_temperature/mono_tint step), so R == G == B does NOT hold even at full
# intensity, by design (same reason the retired "Monochrome" look's own
# equal-channel test zeroed mono_color_wc/mg first -- see this file's git
# history). The equal-channel-base generalization (module docstring, film.py)
# is still exercised end to end by Kodak T-MAX/Tri-X's own fractional-
# intensity tests above/below, which share the exact same film_look code
# path.


def test_kodak_trix_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "kodak_trix", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_kodak_trix_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_monochrome_grade(image.astype(numpy.float32), _KODAK_TRIX_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _KODAK_TRIX_GRADE._replace(grain_std=0.0, grain_std_shadow_boost=0.0)
    without_grain = numpy.clip(
        _apply_monochrome_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_kodak_trix_is_distinct_from_its_acros_pro_base():
    image = _image()
    base_out = film_look(image, {"look": "acros_pro", "intensity": 1.0})
    kodak_trix_out = film_look(image, {"look": "kodak_trix", "intensity": 1.0})
    assert not numpy.array_equal(base_out, kodak_trix_out)


def test_kodak_trix_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "kodak_trix", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_kodak_trix_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "kodak_trix", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_kodak_trix_output_has_equal_channels_at_several_fractional_intensities():
    image = _image()
    for intensity in (0.01, 0.25, 0.5, 0.75, 0.99):
        out = film_look(image, {"look": "kodak_trix", "intensity": intensity})
        assert numpy.array_equal(out[..., 0], out[..., 1]), f"R != G at intensity={intensity}"
        assert numpy.array_equal(out[..., 1], out[..., 2]), f"G != B at intensity={intensity}"


def test_kodak_trix_clarity_is_clipped_to_engine_maximum():
    # Fuji-scale delta (base 18.0 + 4*25=118) exceeds the engine's [-100,100]
    # clarity range -- see the module docstring/grade comment.
    assert _KODAK_TRIX_GRADE.clarity == 100.0


def test_kodak_trix_color_chrome_effect_is_declared_but_has_no_visible_effect():
    # Documented no-op (module docstring): _apply_monochrome_grade never
    # calls _apply_color_chrome_effect, so this field renders inert here
    # despite being declared for fidelity to the source recipe.
    image = _image()
    with_strong = numpy.clip(
        _apply_monochrome_grade(image.astype(numpy.float32), _KODAK_TRIX_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    off_grade = _KODAK_TRIX_GRADE._replace(color_chrome_effect=0.0)
    with_off = numpy.clip(
        _apply_monochrome_grade(image.astype(numpy.float32), off_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert numpy.array_equal(with_strong, with_off)


# ---------------------------------------------------------------------------
# Agfa APX / Ilford Delta / Ilford FP4 / Ilford HP5 / Ilford XP2 (2026-08-05,
# later still) -- five more "B&W" row presets. Agfa APX and Ilford XP2 build
# on Acros Pro; Ilford Delta/FP4/HP5 build on the module-internal Monochrome
# base (not itself a selectable look -- same "is_distinct_from_its_base"
# pattern as Kodak T-MAX above).
# ---------------------------------------------------------------------------


# Retired 2026-08-05 (still later the same day, user request, see the module
# docstring) -- "agfa_apx" is no longer importable, so its tests were
# removed too.


# Retired 2026-08-05 (still later the same day, user request, see the module
# docstring) -- "ilford_delta" is no longer importable, so its tests were
# removed too.


def test_ilford_fp4_deterministic_repeat_call_is_byte_identical():
    image = _image()
    params = {"look": "ilford_fp4", "intensity": 1.0}
    out1 = film_look(image, params)
    out2 = film_look(image, params)
    assert numpy.array_equal(out1, out2)


def test_ilford_fp4_grain_has_a_visible_effect():
    image = _image()
    with_grain = numpy.clip(
        _apply_monochrome_grade(image.astype(numpy.float32), _ILFORD_FP4_GRADE), 0, 255
    ).round().astype(numpy.uint8)
    no_grain_grade = _ILFORD_FP4_GRADE._replace(grain_std=0.0)
    without_grain = numpy.clip(
        _apply_monochrome_grade(image.astype(numpy.float32), no_grain_grade), 0, 255
    ).round().astype(numpy.uint8)
    assert not numpy.array_equal(with_grain, without_grain)


def test_ilford_fp4_is_distinct_from_its_monochrome_base():
    image = _image()
    base_out = _apply_parametric_grade(image.astype(numpy.float32), _MONOCHROME_BASE_GRADE)
    ilford_fp4_out = film_look(image, {"look": "ilford_fp4", "intensity": 1.0})
    assert not numpy.array_equal(
        numpy.clip(base_out, 0, 255).round().astype(numpy.uint8), ilford_fp4_out
    )


def test_ilford_fp4_does_not_mutate_input_in_place():
    image = _image()
    snapshot = image.copy()
    film_look(image, {"look": "ilford_fp4", "intensity": 0.6})
    assert numpy.array_equal(image, snapshot)


def test_ilford_fp4_output_shape_and_dtype_unchanged():
    image = _image()
    out = film_look(image, {"look": "ilford_fp4", "intensity": 0.5})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


# Retired 2026-08-05 (still later the same day, user request, see the module
# docstring) -- "ilford_hp5" is no longer importable, so its tests were
# removed too.


# Retired 2026-08-05 (still later the same day, user request, see the module
# docstring) -- "ilford_xp2" is no longer importable, so its tests were
# removed too.


# ---------------------------------------------------------------------------
# resolve_zoom_values (2026-07-22): the actual fix for the reported bug --
# Zoom sliders must seed with the value in effect for the selected look, not
# a generic neutral default.
# ---------------------------------------------------------------------------


def test_resolve_zoom_values_seeds_from_the_looks_own_calibration():
    values = resolve_zoom_values({"look": "velvia_pro", "intensity": 1.0})
    grade = _VELVIA_PRO_GRADE
    assert values["contrast"] == grade.contrast
    assert values["highlights"] == grade.highlights
    assert values["shadows"] == grade.shadows
    assert values["black_clip"] == grade.black_clip
    assert values["global_saturation"] == grade.global_saturation
    assert values["temperature"] == grade.temperature
    assert values["tint"] == grade.tint
    assert values["clarity"] == grade.clarity
    assert values["sharpness"] == grade.sharpness
    assert values["grain_std"] == grade.grain_std
    assert values["hsl_saturation_scale"] == 1.0
    assert values["hsl_luminance_scale"] == 1.0
    assert values["split_tone_scale"] == 1.0
    assert values["intensity"] == 1.0


def test_resolve_zoom_values_differs_per_look():
    velvia = resolve_zoom_values({"look": "velvia_pro", "intensity": 1.0})
    eterna = resolve_zoom_values({"look": "eterna", "intensity": 1.0})
    assert velvia["contrast"] != eterna["contrast"]


def test_resolve_zoom_values_an_explicit_override_wins_over_the_looks_calibration():
    values = resolve_zoom_values({"look": "velvia_pro", "intensity": 1.0, "contrast": 55.0})
    assert values["contrast"] == 55.0
    # Everything else still reflects the look's own calibration.
    assert values["highlights"] == _VELVIA_PRO_GRADE.highlights


def test_resolve_zoom_values_seeds_filter_fields_from_preset_parameters():
    values = resolve_zoom_values(
        {"look": "acros_pro", "intensity": 1.0, "filter_color": 1.0, "filter_intensity": 1.0}
    )
    assert values["filter_color"] == 1.0
    assert values["filter_intensity"] == 1.0


def test_resolve_zoom_values_filter_fields_default_when_absent():
    values = resolve_zoom_values({"look": "acros_pro", "intensity": 1.0})
    assert values["filter_color"] == 0.0
    assert values["filter_intensity"] == 1.0


def test_resolve_zoom_values_unrecognized_look_only_returns_intensity():
    values = resolve_zoom_values({"look": "sepia", "intensity": 0.6})
    assert values == {"intensity": 0.6}


def test_resolve_zoom_values_missing_look_only_returns_intensity():
    values = resolve_zoom_values({})
    assert values == {"intensity": 1.0}


# ---------------------------------------------------------------------------
# resolve_zoom_values + Dynamic Range (2026-07-25): DR200 composes an
# additional delta onto highlights/shadows/black_clip at RENDER time (see
# _resolve_dynamic_range) -- the Zoom slider's seed value must reflect that
# composed value, not the look's raw stored field, or the slider would show a
# number that doesn't match what's actually on screen.
# ---------------------------------------------------------------------------


def test_resolve_zoom_values_seeds_highlights_shadows_black_clip_with_the_dr_composed_value():
    # Was seeded from "summer_story" (DR200) -- retired 2026-07-27 (user
    # request); "inky_depths" is also DR200, and _resolve_dynamic_range's
    # per-level deltas are fixed regardless of the base look, so the
    # substitution changes nothing about what this test actually checks.
    values = resolve_zoom_values({"look": "inky_depths", "intensity": 1.0})
    assert values["highlights"] == _INKY_DEPTHS_GRADE.highlights - 15.0
    assert values["shadows"] == _INKY_DEPTHS_GRADE.shadows + 10.0
    assert values["black_clip"] == _INKY_DEPTHS_GRADE.black_clip - 0.008
    # dynamic_range/color_chrome_effect/color_chrome_blue are themselves
    # ordinary _ABSOLUTE_FIELD_BOUNDS entries -- seeded at their own raw value.
    assert values["dynamic_range"] == 1.0
    assert values["color_chrome_effect"] == 2.0  # Inky Depths' own value (Strong)
    assert values["color_chrome_blue"] == 0.0


def test_resolve_zoom_values_dr_seed_matches_what_film_look_actually_renders():
    """The critical seed/render-agreement property: an explicit override at
    the seeded highlights value must be a no-op relative to not overriding at
    all -- i.e. the seed IS the effective value film_look renders with.
    """
    # Was "summer_story" -- retired 2026-07-27 (user request); "inky_depths"
    # is also DR200, see test_resolve_zoom_values_seeds_highlights_shadows_black_clip_with_the_dr_composed_value.
    image = _image()
    seeded = resolve_zoom_values({"look": "inky_depths", "intensity": 1.0})
    via_explicit_override = film_look(
        image, {"look": "inky_depths", "intensity": 1.0, "highlights": seeded["highlights"]}
    )
    without_override = film_look(image, {"look": "inky_depths", "intensity": 1.0})
    assert numpy.array_equal(via_explicit_override, without_override)


def test_resolve_zoom_values_dr100_look_is_unaffected_by_dr_composition():
    values = resolve_zoom_values({"look": "eterna", "intensity": 1.0})
    assert values["highlights"] == _ETERNA_GRADE.highlights
    assert values["shadows"] == _ETERNA_GRADE.shadows
    assert values["black_clip"] == _ETERNA_GRADE.black_clip
