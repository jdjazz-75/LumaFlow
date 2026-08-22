# LumaFlow v1.0 (2026-08-07)
# Teste le moteur de gradation paramétrique de l'addon Light (light_adjustments) : bit-identité
# neutre, signature directionnelle des 4 presets, repli défensif par champ, masque polygonal
# sujet/fond (composition, feather, inversion, boîte englobante optimisée), et bloom/protection des
# bords du preset Soft.

"""Pure-function tests for the Light addon's v2 parametric grading engine (feature 047) -- no Qt,
no pipeline engine. Covers User Story 1 (the 4 elaborate presets, whole-image) and the shared
per-key defensive-fallback/determinism/resolve_zoom_values-completeness guarantees every prior
addon in this codebase establishes (Principle IV).
"""
from __future__ import annotations

import numpy

from lumaflow.addons.builtin.light import (
    ADDON_DESCRIPTION,
    _FIELD_BOUNDS,
    _GRADES,
    _MaskSpec,
    _NEUTRAL_GRADE,
    _REGION_COMPOSITION,
    _apply_region_grade,
    _compose_region,
    _mask_bounding_box,
    _polygon_mask,
    _read_mask,
    _read_region_deltas,
    light_adjustments,
    resolve_zoom_values,
)

_PRESET_LOOKS = ("balance", "low_key", "high_key", "dramatique", "soft")


def _flat_image(val: int = 128, width: int = 40, height: int = 40) -> numpy.ndarray:
    arr = numpy.zeros((height, width, 3), dtype=numpy.uint8)
    arr[...] = val
    return arr


def _variance_fixture(height: int = 80, width: int = 80) -> numpy.ndarray:
    """A radially-shaped, photo-like fixture (bright center ~200, dark edges ~60, plus per-channel
    noise for real tonal AND colour variance) -- deliberately not uniform random noise (which
    collapses variance under any clipping contrast operation the same way a real photo would not)
    and not a plain linear gradient (whose corners interact unpredictably with the elliptical
    vignette primitive, per manual verification during calibration). Used by every directional-
    signature/extreme-value test below, whose oracle requires "une image de test avec variance
    tonale réelle".
    """
    y = numpy.linspace(-1.0, 1.0, height)[:, None]
    x = numpy.linspace(-1.0, 1.0, width)[None, :]
    radius = numpy.sqrt(x ** 2 + y ** 2)
    base = 200.0 - 140.0 * numpy.clip(radius, 0.0, 1.0)
    rng = numpy.random.default_rng(42)
    noise = rng.normal(0.0, 10.0, size=(height, width))
    luminance = numpy.clip(base + noise, 0.0, 255.0)
    red = luminance
    green = numpy.clip(luminance * 0.92 + 8.0, 0.0, 255.0)
    blue = numpy.clip(luminance * 1.08 - 8.0, 0.0, 255.0)
    return numpy.stack([red, green, blue], axis=-1).astype(numpy.uint8)


def _high_frequency_std(image: numpy.ndarray) -> float:
    """Luma minus a blurred copy of itself -- the fine-detail content Soft is expected to reduce
    ("Soft : écart-type plus faible sur les hautes fréquences"), independent of the
    overall tonal std-dev (which Dramatique's own oracle targets)."""
    from lumaflow.addons.builtin.light import _box_blur, _luma

    luma = _luma(image.astype(numpy.float32))
    blurred = _box_blur(luma, 3)
    return float((luma - blurred).std())


# --- Bit-identity (SC-001, FR-014) ---


def test_empty_params_returns_bit_identical_image():
    image = _variance_fixture()
    out = light_adjustments(image, {})
    assert numpy.array_equal(out, image)


def test_unrecognized_look_with_no_other_keys_returns_bit_identical_image():
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "not-a-real-look"})
    assert numpy.array_equal(out, image)


def test_explicit_all_neutral_overrides_return_bit_identical_image():
    image = _variance_fixture()
    neutral_overrides = {field_name: getattr(_NEUTRAL_GRADE, field_name) for field_name in _FIELD_BOUNDS}
    out = light_adjustments(image, {**neutral_overrides, "intensity": 1.0})
    assert numpy.array_equal(out, image)


def test_all_malformed_overrides_on_a_look_return_bit_identical_image():
    # Every declared base-grade key present but garbage -- each must fall back to the LOOK's own
    # neutral (here: Neutre has none, so every key falls back to _NEUTRAL_GRADE's own default),
    # net result still bit-identical.
    image = _variance_fixture()
    garbage_overrides = {field_name: "not-a-number" for field_name in _FIELD_BOUNDS}
    out = light_adjustments(image, {**garbage_overrides, "intensity": "also-not-a-number"})
    assert numpy.array_equal(out, image)


def test_intensity_zero_returns_bit_identical_image_even_with_a_real_look():
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "low_key", "intensity": 0.0})
    assert numpy.array_equal(out, image)


# --- Directional signature per preset (SC-002) ---


def test_low_key_is_significantly_darker_than_neutral():
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "low_key", "intensity": 1.0})
    assert float(out.mean()) < float(image.mean()) - 30.0


def test_high_key_is_significantly_brighter_than_neutral():
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "high_key", "intensity": 1.0})
    assert float(out.mean()) > float(image.mean()) + 30.0


def test_dramatique_has_higher_overall_contrast_than_neutral():
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "dramatique", "intensity": 1.0})
    assert float(out.std()) > float(image.std())


def test_soft_reduces_high_frequency_detail_relative_to_neutral():
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "soft", "intensity": 1.0})
    assert _high_frequency_std(out) < _high_frequency_std(image)


def test_all_four_presets_produce_mutually_distinct_results():
    image = _variance_fixture()
    outputs = {
        look: light_adjustments(image, {"look": look, "intensity": 1.0})
        for look in ("low_key", "high_key", "dramatique", "soft")
    }
    keys = list(outputs)
    for i, first in enumerate(keys):
        for second in keys[i + 1 :]:
            assert not numpy.array_equal(outputs[first], outputs[second]), (first, second)
        assert not numpy.array_equal(outputs[first], image)


def test_balance_still_produces_a_visible_uplift():
    # Re-expressed via the `look` model on the new -100..100 scale (Decision 10/11) -- external
    # behavior is "a mild exposure lift with highlight recovery", not byte-identical to F-043's own
    # Balance output (the scale itself changed, Decision 11).
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "balance", "intensity": 1.0})
    assert not numpy.array_equal(out, image)
    assert float(out.mean()) > float(image.mean())


# --- Extreme values stay non-degenerate (SC-006, FR-015) ---


def test_every_field_pushed_individually_to_its_extreme_stays_non_degenerate():
    image = _variance_fixture()
    for field_name, (minimum, maximum) in _FIELD_BOUNDS.items():
        for extreme in (minimum, maximum):
            out = light_adjustments(image, {"look": "low_key", "intensity": 1.0, field_name: extreme})
            assert float(out.std()) > 1.0, (field_name, extreme)
            assert len(numpy.unique(out)) > 1, (field_name, extreme)


# --- Per-key defensive fallback (FR-019) ---


def test_malformed_single_field_falls_back_alone_others_still_apply():
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "dramatique", "intensity": 1.0, "contrast": "not-a-number"})
    only_without_contrast_override = light_adjustments(image, {"look": "dramatique", "intensity": 1.0})
    assert numpy.array_equal(out, only_without_contrast_override)


def test_out_of_range_single_field_falls_back_alone_others_still_apply():
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "dramatique", "intensity": 1.0, "saturation": 999.0})
    only_without_saturation_override = light_adjustments(image, {"look": "dramatique", "intensity": 1.0})
    assert numpy.array_equal(out, only_without_saturation_override)


def test_missing_field_falls_back_to_looks_own_calibrated_value():
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "low_key", "intensity": 1.0, "shadows": _GRADES["low_key"].shadows})
    baseline = light_adjustments(image, {"look": "low_key", "intensity": 1.0})
    assert numpy.array_equal(out, baseline)


def test_valid_override_changes_only_that_field():
    image = _variance_fixture()
    baseline = light_adjustments(image, {"look": "dramatique", "intensity": 1.0})
    overridden = light_adjustments(image, {"look": "dramatique", "intensity": 1.0, "vignette": 0.0})
    assert not numpy.array_equal(baseline, overridden)


def test_cyclic_hue_field_wraps_rather_than_rejecting_out_of_range():
    image = _variance_fixture()
    wrapped = light_adjustments(
        image, {"look": "low_key", "intensity": 1.0, "split_shadow_hue": 570.0}  # 570 % 360 == 210
    )
    equivalent = light_adjustments(
        image, {"look": "low_key", "intensity": 1.0, "split_shadow_hue": 210.0}
    )
    assert numpy.array_equal(wrapped, equivalent)


# --- Determinism (Principle IV) ---


def test_deterministic_repeat_call_is_byte_identical():
    image = _variance_fixture()
    params = {"look": "dramatique", "intensity": 1.0}
    out1 = light_adjustments(image, params)
    out2 = light_adjustments(image, params)
    assert numpy.array_equal(out1, out2)


def test_output_shape_and_dtype_match_input():
    image = _variance_fixture()
    out = light_adjustments(image, {"look": "soft", "intensity": 1.0})
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_does_not_mutate_input_in_place():
    image = _variance_fixture()
    snapshot = image.copy()
    light_adjustments(image, {"look": "dramatique", "intensity": 1.0})
    assert numpy.array_equal(image, snapshot)


# --- resolve_zoom_values completeness (the direct F-043 regression guard) ---


def test_resolve_zoom_values_covers_every_declared_identifier():
    declared = {p.identifier for p in ADDON_DESCRIPTION.parameter_descriptions}
    values = resolve_zoom_values({"look": "dramatique", "intensity": 1.0})
    assert declared <= values.keys()


def test_resolve_zoom_values_reflects_the_selected_looks_real_calibration():
    values = resolve_zoom_values({"look": "low_key", "intensity": 1.0})
    assert values["exposure"] == _GRADES["low_key"].exposure
    assert values["contrast"] == _GRADES["low_key"].contrast


def test_resolve_zoom_values_reflects_an_override_on_top_of_a_look():
    values = resolve_zoom_values({"look": "low_key", "intensity": 1.0, "exposure": -50.0})
    assert values["exposure"] == -50.0
    assert values["contrast"] == _GRADES["low_key"].contrast


def test_resolve_zoom_values_defaults_to_neutral_grade_when_no_look_selected():
    values = resolve_zoom_values({})
    for field_name in _FIELD_BOUNDS:
        assert values[field_name] == getattr(_NEUTRAL_GRADE, field_name)


def test_resolve_zoom_values_falls_back_per_key_on_malformed_value():
    values = resolve_zoom_values({"look": "low_key", "intensity": 1.0, "contrast": "not-a-number"})
    assert values["contrast"] == _GRADES["low_key"].contrast
    assert values["exposure"] == _GRADES["low_key"].exposure


# --- ADDON_DESCRIPTION shape ---


def test_addon_description_shape():
    assert ADDON_DESCRIPTION.identifier == "light_adjustments"
    assert ADDON_DESCRIPTION.category == "light"
    identifiers = [p.identifier for p in ADDON_DESCRIPTION.thumbnail_presets]
    assert identifiers == ["neutral", "Balance", "Low Key", "High Key", "Dramatique", "Soft"]
    neutral = ADDON_DESCRIPTION.thumbnail_presets[0]
    assert neutral.neutral is True
    assert neutral.preset_parameters is None
    for preset, look in zip(ADDON_DESCRIPTION.thumbnail_presets[1:], _PRESET_LOOKS):
        assert preset.preset_parameters == {"look": look, "intensity": 1.0}
    declared_identifiers = {p.identifier for p in ADDON_DESCRIPTION.parameter_descriptions}
    region_identifiers = {
        f"{prefix}_{field_name}" for prefix in ("subject", "background") for field_name in _REGION_COMPOSITION
    }
    mask_identifiers = {"mask_point_count", "mask_feather", "mask_invert"} | {
        f"mask_point_{i:02d}_{axis}" for i in range(32) for axis in ("x", "y")
    }
    assert declared_identifiers == {"intensity"} | set(_FIELD_BOUNDS) | region_identifiers | mask_identifiers
    assert len(declared_identifiers) == 137
    assert all(p.zoom_only for p in ADDON_DESCRIPTION.parameter_descriptions)
    assert ADDON_DESCRIPTION.overlay_descriptions == ()
    assert ADDON_DESCRIPTION.resolve_zoom_values is resolve_zoom_values
    assert ADDON_DESCRIPTION.processing_function is light_adjustments


def test_every_parameter_description_default_is_within_its_own_bounds():
    for description in ADDON_DESCRIPTION.parameter_descriptions:
        assert description.constraints.minimum <= description.default <= description.constraints.maximum


def test_flat_image_stays_flat_under_global_only_presets_with_grain_and_vignette_suppressed():
    # No mask/region logic exists yet (User Story 3) -- with the two spatially-varying stages
    # (grain: random per-pixel noise; vignette: radial position-dependent multiplier) suppressed, a
    # flat image graded globally must still have every pixel equal to every other pixel: every
    # other stage in the pipeline is pointwise (same input value everywhere -> same output value
    # everywhere), so no spatially-varying artifact should leak in from a feature not yet built.
    image = _flat_image(val=140)
    for look in _PRESET_LOOKS:
        out = light_adjustments(image, {"look": look, "intensity": 1.0, "grain": 0.0, "vignette": 0.0})
        # Per-channel spatial flatness -- R/G/B may legitimately differ FROM EACH OTHER (a colour
        # cast from temperature/tint/split-tone is expected), but each channel on its own must be
        # spatially constant (every pixel of that channel identical to every other).
        for channel_index in range(3):
            assert len(numpy.unique(out[..., channel_index])) == 1, (look, channel_index)


# --- User Story 3: subject/background region split ---

_RECTANGLE_PARAMS = {
    "mask_point_count": 4.0,
    "mask_point_00_x": 0.25, "mask_point_00_y": 0.25,
    "mask_point_01_x": 0.75, "mask_point_01_y": 0.25,
    "mask_point_02_x": 0.75, "mask_point_02_y": 0.75,
    "mask_point_03_x": 0.25, "mask_point_03_y": 0.75,
    "mask_feather": 0.5,
}


def test_mask_below_three_vertices_resolves_to_none():
    assert _read_mask({"mask_point_count": 2.0, "mask_point_00_x": 0.1, "mask_point_00_y": 0.1}) is None
    assert _read_mask({}) is None


def test_mask_absent_matches_the_no_mask_single_region_output():
    image = _variance_fixture()
    params_no_mask = {"look": "low_key", "intensity": 1.0, "subject_exposure": 40.0}
    with_no_mask = light_adjustments(image, params_no_mask)
    plain = light_adjustments(image, {"look": "low_key", "intensity": 1.0, "background_exposure": 0.0})
    assert numpy.array_equal(with_no_mask, plain)


def test_polygon_mask_is_one_inside_zero_outside_with_a_sharp_feather():
    shape = (40, 40, 3)
    mask = _polygon_mask(shape, ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)), feather_pct=0.0, invert=False)
    assert mask.shape == (40, 40)
    assert mask[20, 20] == 1.0  # dead center, inside
    assert mask[1, 1] == 0.0  # corner, outside
    assert mask.min() >= 0.0 and mask.max() <= 1.0


def test_polygon_mask_invert_flips_inside_and_outside():
    shape = (40, 40, 3)
    points = ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75))
    normal = _polygon_mask(shape, points, feather_pct=0.0, invert=False)
    inverted = _polygon_mask(shape, points, feather_pct=0.0, invert=True)
    assert numpy.allclose(inverted, 1.0 - normal)


def test_polygon_mask_feather_produces_a_smooth_ramp_at_the_boundary():
    shape = (80, 80, 3)
    points = ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75))
    mask = _polygon_mask(shape, points, feather_pct=10.0, invert=False)
    # A horizontal slice through the vertical left edge (x ~ 0.25*80=20) must be monotonically
    # non-decreasing as it crosses from outside to inside -- a smooth ramp, not a hard step.
    row = mask[40, 5:35]
    diffs = numpy.diff(row)
    assert numpy.all(diffs >= -1e-6)
    assert 0.0 < row.min() or row[0] < row[-1]


def test_degenerate_polygons_never_raise():
    image = _variance_fixture()
    degenerate_shapes = {
        "near_zero_area": {
            "mask_point_count": 3.0,
            "mask_point_00_x": 0.50, "mask_point_00_y": 0.50,
            "mask_point_01_x": 0.501, "mask_point_01_y": 0.50,
            "mask_point_02_x": 0.50, "mask_point_02_y": 0.501,
        },
        "collinear": {
            "mask_point_count": 3.0,
            "mask_point_00_x": 0.1, "mask_point_00_y": 0.5,
            "mask_point_01_x": 0.5, "mask_point_01_y": 0.5,
            "mask_point_02_x": 0.9, "mask_point_02_y": 0.5,
        },
        "self_intersecting": {
            "mask_point_count": 4.0,
            "mask_point_00_x": 0.2, "mask_point_00_y": 0.2,
            "mask_point_01_x": 0.8, "mask_point_01_y": 0.8,
            "mask_point_02_x": 0.8, "mask_point_02_y": 0.2,
            "mask_point_03_x": 0.2, "mask_point_03_y": 0.8,
        },
    }
    for name, mask_params in degenerate_shapes.items():
        params = {"look": "low_key", "intensity": 1.0, "subject_exposure": 30.0, "background_exposure": -30.0, **mask_params}
        out = light_adjustments(image, params)
        assert out.shape == image.shape, name
        assert out.dtype == numpy.uint8, name


def test_mask_boundary_composition_is_exact_at_pure_inside_and_outside():
    # A pixel deep inside the mask (alpha == 1.0, sharp feather) must equal what a whole-image
    # render with the SUBJECT grade alone would produce there; a pixel far outside (alpha == 0.0)
    # must equal the BACKGROUND grade's whole-image render.
    image = _variance_fixture()
    params = {"look": "low_key", "intensity": 1.0, "subject_exposure": 50.0, "background_exposure": -50.0, **_RECTANGLE_PARAMS}
    out = light_adjustments(image, params)

    from lumaflow.addons.builtin.light import _apply_grain, _apply_vignette

    base = _GRADES["low_key"]
    subject_deltas = _read_region_deltas(params, "subject")
    background_deltas = _read_region_deltas(params, "background")
    subject_grade = _compose_region(base, subject_deltas)
    background_grade = _compose_region(base, background_deltas)
    source = image.astype(numpy.float32)

    def _whole_image_render(grade):
        graded = _apply_region_grade(source, grade)
        graded = _apply_vignette(graded, base.vignette)  # global tail, matches light_adjustments
        graded = _apply_grain(graded, base.grain, base.grain_size)
        return numpy.clip(graded, 0, 255).round().astype(numpy.uint8)

    subject_only = _whole_image_render(subject_grade)
    background_only = _whole_image_render(background_grade)

    # Deep inside the rectangle (mask_feather=0.5%, well clear of the 25%-inset edges).
    assert numpy.array_equal(out[40, 40], subject_only[40, 40])
    # Far outside the rectangle (corner).
    assert numpy.array_equal(out[2, 2], background_only[2, 2])


def test_equal_subject_and_background_deltas_take_the_single_pass_path():
    image = _variance_fixture()
    params_equal = {
        "look": "low_key", "intensity": 1.0,
        "subject_exposure": 20.0, "background_exposure": 20.0,
        **_RECTANGLE_PARAMS,
    }
    out_equal = light_adjustments(image, params_equal)
    single_pass = light_adjustments(image, {"look": "low_key", "intensity": 1.0, "background_exposure": 20.0})
    assert numpy.array_equal(out_equal, single_pass)


def test_region_delta_per_key_fallback():
    image = _variance_fixture()
    out = light_adjustments(
        image, {"look": "dramatique", "intensity": 1.0, "subject_exposure": "not-a-number", **_RECTANGLE_PARAMS}
    )
    baseline = light_adjustments(image, {"look": "dramatique", "intensity": 1.0, **_RECTANGLE_PARAMS})
    assert numpy.array_equal(out, baseline)


def test_mask_vertex_per_key_fallback_to_default_rectangle_point():
    # A corrupted single vertex coordinate falls back to that vertex's own default alone -- the
    # rest of the shape (and the render) is unaffected, matching FR-019.
    corrupted = dict(_RECTANGLE_PARAMS)
    corrupted["mask_point_01_x"] = "not-a-number"
    mask = _read_mask(corrupted)
    clean = _read_mask(_RECTANGLE_PARAMS)
    assert mask is not None and clean is not None
    assert mask.points[1] == clean.points[1] == (0.75, 0.25)


def test_resolve_zoom_values_includes_region_and_mask_fields_with_defaults():
    values = resolve_zoom_values({})
    for field_name in _REGION_COMPOSITION:
        expected_default = 0.0 if _REGION_COMPOSITION[field_name] == "additive" else 1.0
        assert values[f"subject_{field_name}"] == expected_default
        assert values[f"background_{field_name}"] == expected_default
    assert values["mask_point_count"] == 4.0  # the default rectangle's own vertex count
    assert values["mask_feather"] == 2.0
    assert values["mask_invert"] == 0.0


# --- User Story 5: Soft's bloom + protected soft-detail ---


def _bloom_and_edge_fixture(height: int = 100, width: int = 100) -> numpy.ndarray:
    """A dim background (luma 60) with a bright circular hotspot (luma up to ~255, well above
    _SOFT_GRADE's bloom_threshold=0.72) in one quadrant, plus a hard vertical edge (a +120 step)
    elsewhere -- lets bloom (spreads/lifts the hotspot) and edge protection (the step must stay
    identifiable) be measured independently."""
    base = numpy.full((height, width), 60.0)
    y = numpy.linspace(-1.0, 1.0, height)[:, None]
    x = numpy.linspace(-1.0, 1.0, width)[None, :]
    hotspot_radius = numpy.sqrt((x - (-0.5)) ** 2 + (y - (-0.5)) ** 2)
    base = base + 200.0 * numpy.clip(1.0 - hotspot_radius * 2.0, 0.0, 1.0)
    base = numpy.where(x > 0.3, base + 120.0, base)
    base = numpy.clip(base, 0.0, 255.0)
    return numpy.stack([base, base, base], axis=-1).astype(numpy.uint8)


def test_soft_bloom_raises_the_bright_regions_mean_value():
    image = _bloom_and_edge_fixture()
    out = light_adjustments(image, {"look": "soft", "intensity": 1.0})
    bright_mask = image[..., 0] > 200
    assert bright_mask.any()
    assert float(out[bright_mask].mean()) > float(image[bright_mask].mean())


def test_soft_edge_protection_keeps_the_sharp_edge_gradient_comparably_high():
    from lumaflow.addons.builtin.light import _luma

    image = _bloom_and_edge_fixture()
    out = light_adjustments(image, {"look": "soft", "intensity": 1.0})

    luma_in = _luma(image.astype(numpy.float32))
    luma_out = _luma(out.astype(numpy.float32))
    edge_col = int((0.3 + 1.0) / 2.0 * image.shape[1])
    gy_in, gx_in = numpy.gradient(luma_in)
    gy_out, gx_out = numpy.gradient(luma_out)
    magnitude_in = numpy.sqrt(gx_in ** 2 + gy_in ** 2)[:, edge_col - 1 : edge_col + 2]
    magnitude_out = numpy.sqrt(gx_out ** 2 + gy_out ** 2)[:, edge_col - 1 : edge_col + 2]
    # "Comparably high" (FR-013): the edge is not washed out -- it retains at least half its
    # original gradient magnitude, unlike a flat/plain region which would collapse toward zero
    # under the same soft-detail blend.
    assert float(magnitude_out.mean()) > float(magnitude_in.mean()) * 0.5


def test_bloom_and_soft_detail_have_a_visible_effect_when_enabled():
    # Soft with bloom_amount/soft_detail_amount forced to 0 (tonal/colour/texture only, matching
    # this preset's own pre-User-Story-5 behavior) must differ from the full calibrated Soft
    # render -- proof bloom/soft-detail are actually wired into the pipeline, not silently inert.
    image = _bloom_and_edge_fixture()
    without_halo_or_softening = light_adjustments(
        image, {"look": "soft", "intensity": 1.0, "bloom_amount": 0.0, "soft_detail_amount": 0.0}
    )
    full_soft = light_adjustments(image, {"look": "soft", "intensity": 1.0})
    assert without_halo_or_softening.shape == image.shape
    assert not numpy.array_equal(without_halo_or_softening, full_soft)


# --- Perf remediation (T047): bounding-box-limited subject render ---


def test_mask_bounding_box_covers_the_polygon_plus_feather_and_safety_margin():
    shape = (200, 200, 3)
    points = ((0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6))
    x0, x1, y0, y1 = _mask_bounding_box(points, feather_pct=2.0, shape=shape)
    # The raw polygon spans 0.4..0.6 (80..120px on a 200px axis) -- the padded box must fully
    # contain it, with room to spare for the feather ramp + safety margin.
    assert x0 < 80 and x1 > 120
    assert y0 < 80 and y1 > 120
    assert 0 <= x0 < x1 <= shape[1]
    assert 0 <= y0 < y1 <= shape[0]


def test_bounding_box_optimized_composite_matches_full_image_composite_at_interior_points():
    # The cropped subject-side render (perf optimization) must be pixel-identical to what a
    # full-image subject render would produce, everywhere comfortably inside the crop -- only the
    # crop's OWN blur-boundary effects (irrelevant here, deep interior points) could differ.
    image = _variance_fixture()
    params = {
        "look": "dramatique", "intensity": 1.0,
        "subject_exposure": 45.0, "background_exposure": -45.0,
        **_RECTANGLE_PARAMS,
    }
    out = light_adjustments(image, params)

    base = _GRADES["dramatique"]
    subject_deltas = _read_region_deltas(params, "subject")
    subject_grade = _compose_region(base, subject_deltas)
    from lumaflow.addons.builtin.light import _apply_grain, _apply_vignette

    full_subject = _apply_region_grade(image.astype(numpy.float32), subject_grade)
    full_subject = _apply_vignette(full_subject, base.vignette)
    full_subject = _apply_grain(full_subject, base.grain, base.grain_size)
    full_subject = numpy.clip(full_subject, 0, 255).round().astype(numpy.uint8)

    # Deep inside the rectangle (mask_feather=0.5%, far from both the polygon's own edge and the
    # padded crop's edge).
    assert numpy.array_equal(out[40, 40], full_subject[40, 40])


def test_inverted_mask_applies_subject_grade_outside_the_bounding_box():
    # Regression test (bug found 2026-07-28): the bounding-box perf optimization above must crop
    # whichever region is small -- when the mask is inverted, that's the BACKGROUND (now confined
    # to the polygon interior), not the subject. The original version always cropped the subject
    # render (correct only for the non-inverted case), which silently dropped the subject grade
    # everywhere outside the polygon's own small bounding box even though alpha there is 1.0 (fully
    # subject) once inverted -- observed as "Inverser" having almost no visible effect.
    image = _variance_fixture()
    params = {
        "look": "low_key", "intensity": 1.0,
        "subject_exposure": 50.0, "background_exposure": -50.0,
        "mask_invert": 1.0,
        **_RECTANGLE_PARAMS,
    }
    out = light_adjustments(image, params)

    base = _GRADES["low_key"]
    subject_deltas = _read_region_deltas(params, "subject")
    subject_grade = _compose_region(base, subject_deltas)
    source = image.astype(numpy.float32)

    from lumaflow.addons.builtin.light import _apply_grain, _apply_vignette

    def _whole_image_render(grade):
        graded = _apply_region_grade(source, grade)
        graded = _apply_vignette(graded, base.vignette)
        graded = _apply_grain(graded, base.grain, base.grain_size)
        return numpy.clip(graded, 0, 255).round().astype(numpy.uint8)

    subject_only = _whole_image_render(subject_grade)

    # Far outside the rectangle (image corner) -- inverted, this is deep INSIDE the subject region,
    # well past the polygon's own feather-padded bounding box: exactly where the bug dropped the
    # subject grade entirely.
    assert numpy.array_equal(out[2, 2], subject_only[2, 2])
