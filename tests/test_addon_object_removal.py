# LumaFlow v1.0 (2026-09-23)
# Teste la fonction pure de l'addon Suppression d'objets (object_removal) : lecture défensive des
# zones/réglages, contrat neutre/non-mutation, forme de la description, complétude de
# resolve_zoom_values, et repli sur valeurs malformées -- pas le moteur lui-même (voir
# tests/test_inpainting_engine.py pour ça).

"""Pure-function tests for the Object Removal addon's remove_objects processing_function
(feature 100) -- no Qt, no engine internals.
"""
from __future__ import annotations

import numpy
import pytest

from lumaflow.addons.builtin.object_removal import (
    ADDON_DESCRIPTION,
    _MAX_MASK_VERTICES,
    _MAX_ZONES,
    _read_float,
    _read_zone,
    _read_zones,
    remove_objects,
    resolve_zoom_values,
)


def _image(height: int = 40, width: int = 50, seed: int = 0) -> numpy.ndarray:
    rng = numpy.random.default_rng(seed)
    return rng.integers(0, 255, size=(height, width, 3), dtype=numpy.uint8)


def _square(cx: float, cy: float, half: float) -> dict[str, float]:
    points = [(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)]
    values: dict[str, float] = {"zone_0_mask_point_count": 4.0}
    for i, (x, y) in enumerate(points):
        values[f"zone_0_mask_point_{i:02d}_x"] = x
        values[f"zone_0_mask_point_{i:02d}_y"] = y
    return values


# ---------------------------------------------------------------------------
# _read_float
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_read_float_rejects_non_finite_values(bad):
    assert _read_float({"x": bad}, "x", 7.0) == 7.0


def test_read_float_rejects_booleans_and_strings():
    assert _read_float({"x": True}, "x", 3.0) == 3.0
    assert _read_float({"x": "oops"}, "x", 3.0) == 3.0


def test_read_float_clamps_to_bounds():
    assert _read_float({"x": 999.0}, "x", 0.0, minimum=0.0, maximum=10.0) == 10.0
    assert _read_float({"x": -5.0}, "x", 0.0, minimum=0.0, maximum=10.0) == 0.0


def test_read_float_missing_key_falls_back_to_default():
    assert _read_float({}, "x", 4.5) == 4.5


# ---------------------------------------------------------------------------
# _read_zone / _read_zones
# ---------------------------------------------------------------------------


def test_read_zone_below_three_vertices_is_none():
    assert _read_zone({"zone_0_mask_point_count": 2.0}, 0) is None
    assert _read_zone({}, 0) is None


def test_read_zone_reads_declared_vertices():
    zone = _read_zone(_square(0.5, 0.5, 0.1), 0)
    assert zone is not None
    assert len(zone.points) == 4


def test_read_zones_ignores_a_fifth_zone_key():
    params = _square(0.5, 0.5, 0.1)
    params["zone_4_mask_point_count"] = 4.0  # index 4 is out of range (0.._MAX_ZONES-1 == 0..3)
    for i in range(4):
        params[f"zone_4_mask_point_{i:02d}_x"] = 0.5
        params[f"zone_4_mask_point_{i:02d}_y"] = 0.5
    zones = _read_zones(params)
    assert len(zones) == 1  # only zone_0, zone_4 was never read


def test_read_zones_collects_multiple_zones():
    params = {**_square(0.2, 0.2, 0.05)}
    zone2 = _square(0.8, 0.8, 0.05)
    params.update({k.replace("zone_0", "zone_1"): v for k, v in zone2.items()})
    zones = _read_zones(params)
    assert len(zones) == 2


# ---------------------------------------------------------------------------
# remove_objects -- the processing_function contract
# ---------------------------------------------------------------------------


def test_remove_objects_no_zones_returns_the_same_object():
    image = _image()
    assert remove_objects(image, {}) is image


def test_remove_objects_fewer_than_three_vertices_is_a_no_op():
    image = _image()
    params = {"zone_0_mask_point_count": 2.0, "zone_0_mask_point_00_x": 0.5, "zone_0_mask_point_00_y": 0.5}
    assert remove_objects(image, params) is image


def test_remove_objects_variant_dilation_feather_alone_do_not_change_a_zoneless_image():
    image = _image()
    params = {"dilation": 2.0, "feather": 1.5, "variant": 7.0}
    assert remove_objects(image, params) is image


def test_remove_objects_never_mutates_the_input():
    image = _image(80, 100)
    before = image.copy()
    remove_objects(image, _square(0.5, 0.5, 0.15))
    assert numpy.array_equal(image, before)


def test_remove_objects_with_a_zone_changes_the_output():
    image = _image(80, 100)
    out = remove_objects(image, _square(0.5, 0.5, 0.15))
    assert not numpy.array_equal(out, image)
    assert out.shape == image.shape
    assert out.dtype == numpy.uint8


def test_remove_objects_out_of_range_dilation_feather_variant_are_clamped_not_fatal():
    image = _image(60, 80)
    params = {**_square(0.5, 0.5, 0.1), "dilation": -50.0, "feather": 9999.0, "variant": -1.0}
    out = remove_objects(image, params)  # must not raise
    assert out.shape == image.shape


def test_remove_objects_nan_and_bool_zone_values_do_not_crash():
    image = _image(50, 60)
    params = {
        "zone_0_mask_point_count": 4.0,
        "zone_0_mask_point_00_x": float("nan"),
        "zone_0_mask_point_00_y": True,
        "zone_0_mask_point_01_x": 0.6,
        "zone_0_mask_point_01_y": 0.4,
        "zone_0_mask_point_02_x": 0.6,
        "zone_0_mask_point_02_y": 0.6,
        "zone_0_mask_point_03_x": 0.4,
        "zone_0_mask_point_03_y": 0.6,
    }
    out = remove_objects(image, params)  # must not raise -- bad vertex falls back to its own default
    assert out.shape == image.shape


def test_remove_objects_whole_image_zone_does_not_crash():
    image = _image(50, 60)
    params = {
        "zone_0_mask_point_count": 4.0,
        "zone_0_mask_point_00_x": 0.0, "zone_0_mask_point_00_y": 0.0,
        "zone_0_mask_point_01_x": 1.0, "zone_0_mask_point_01_y": 0.0,
        "zone_0_mask_point_02_x": 1.0, "zone_0_mask_point_02_y": 1.0,
        "zone_0_mask_point_03_x": 0.0, "zone_0_mask_point_03_y": 1.0,
    }
    out = remove_objects(image, params)
    assert out.shape == image.shape
    assert numpy.all(numpy.isfinite(out.astype(numpy.float32)))


def test_remove_objects_is_deterministic_and_variant_changes_result():
    image = _image(80, 100)
    params = _square(0.5, 0.5, 0.15)
    a = remove_objects(image, {**params, "variant": 0.0})
    a2 = remove_objects(image, {**params, "variant": 0.0})
    b = remove_objects(image, {**params, "variant": 1.0})
    assert numpy.array_equal(a, a2)
    assert not numpy.array_equal(a, b)


# ---------------------------------------------------------------------------
# resolve_zoom_values
# ---------------------------------------------------------------------------


def test_resolve_zoom_values_is_complete_and_matches_declared_identifiers():
    declared = {p.identifier for p in ADDON_DESCRIPTION.parameter_descriptions}
    resolved = resolve_zoom_values({})
    assert set(resolved.keys()) == declared


def test_resolve_zoom_values_pure_default_probe_yields_zero_zones():
    """`auxiliary_zoom_pure_default_values` (session.py) probes every addon's resolve_zoom_values
    with `{"look": None, "intensity": 1.0}` -- neither key means anything to this addon, so the
    probe must fall straight through to the declared defaults (0 zones), the Réinitialiser target."""
    resolved = resolve_zoom_values({"look": None, "intensity": 1.0})
    assert resolved["zone_0_mask_point_count"] == 0.0
    assert resolved["dilation"] == 0.5
    assert resolved["feather"] == 0.3
    assert resolved["variant"] == 0.0


def test_resolve_zoom_values_reflects_an_override():
    resolved = resolve_zoom_values({"dilation": 2.5, "zone_0_mask_point_count": 4.0})
    assert resolved["dilation"] == 2.5
    assert resolved["zone_0_mask_point_count"] == 4.0


def test_resolve_zoom_values_clamps_bad_values():
    resolved = resolve_zoom_values({"dilation": float("nan"), "variant": True})
    assert resolved["dilation"] == 0.5
    assert resolved["variant"] == 0.0


# ---------------------------------------------------------------------------
# ADDON_DESCRIPTION shape
# ---------------------------------------------------------------------------


def test_addon_description_shape():
    assert ADDON_DESCRIPTION.identifier == "object_removal"
    assert ADDON_DESCRIPTION.category == "object_removal"
    assert [p.identifier for p in ADDON_DESCRIPTION.thumbnail_presets] == ["neutral"]
    assert ADDON_DESCRIPTION.thumbnail_presets[0].neutral is True
    # 3 globals + 8 zones x 65 (1 count + 32 vertices x 2 axes)
    assert len(ADDON_DESCRIPTION.parameter_descriptions) == 3 + _MAX_ZONES * (1 + _MAX_MASK_VERTICES * 2)


def test_zone_parameters_are_transient():
    zone_params = [p for p in ADDON_DESCRIPTION.parameter_descriptions if p.identifier.startswith("zone_")]
    assert zone_params  # sanity: there are some
    assert all(p.transient for p in zone_params)


def test_global_parameters_are_not_transient():
    globals_ = [p for p in ADDON_DESCRIPTION.parameter_descriptions if p.identifier in ("dilation", "feather", "variant")]
    assert len(globals_) == 3
    assert all(not p.transient for p in globals_)


def test_no_intensity_or_look_parameter_declared():
    identifiers = {p.identifier for p in ADDON_DESCRIPTION.parameter_descriptions}
    assert "intensity" not in identifiers
    assert "look" not in identifiers


@pytest.mark.perf
@pytest.mark.model
def test_remove_objects_perf_1600x1200_5_percent_hole():
    """Real LaMa inference (not the default stub -- see conftest.py), generous ceiling (noise floor
    ~40% on this machine, see perf-measurement-noise-floor) -- this is a smoke ceiling, not the
    authoritative SC-004 measurement (that lives in benchmarks/bench_object_removal.py, run
    manually). Excluded from a default `pytest` run (`model` marker); run with `pytest -m model`."""
    import time

    height, width = 1200, 1600
    image = _image(height, width, seed=99)
    half = int(((0.05 * height * width) / numpy.pi) ** 0.5)
    cy, cx = height // 2, width // 2
    params = _square(cx / width, cy / height, (half + 4) / width)
    start = time.perf_counter()
    remove_objects(image, params)
    elapsed = time.perf_counter() - start
    assert elapsed < 20.0
