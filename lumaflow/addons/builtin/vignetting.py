# LumaFlow v1.0 (2026-08-07)
# Addon Vignetage : ellipse ou bande lineaire editable (centre, rayons/offsets,
# rotation, plume) avec intensite/progressivite regles par curseurs Zoom uniquement.
"""Vignetting addon (Vignetage) -- Neutral plus two named preset shapes (Round Central, Linear
Top+Bottom), each an interactively editable ellipse/line-band boundary (center, size/offsets,
rotation), plus Intensity/Progressivity/Feather Width Zoom-only sliders (feature 044, extended by
the "dynamic aids" pass with interactive shape editing -- see the user's own product brief for the
ellipse vertex/co-vertex handles, movable center, Geometry-style rotation dial, and a Masque-Sujet-
style feather halo).

No Qt, no pipeline engine, no persistence module import (same convention as every module under
lumaflow/addons/).

Architecture notes (dynamic-aids pass):

- "shape"/"intensity"/"progressivity" remain a coupled triple (unchanged from the original F-044
  Decision 2): an unrecognized/missing `shape` returns the image unchanged outright; a valid
  `shape` with a missing/non-numeric/out-of-range `intensity` or `progressivity` ALSO returns the
  image unchanged -- an all-or-nothing fallback to Neutral for the whole step.
- The 8 NEW geometry/feather fields (`center_x/y`, `radius_x/y`, `top_offset`/`bottom_offset`,
  `rotation_angle`, `feather_width`) use a DIFFERENT, independent per-key fallback convention
  (clamp for spatial fields, reset-to-default for `rotation_angle`/`feather_width`, mirroring
  geometry.py's corner-vs-angle split and light.py's `mask_feather`) -- a malformed geometry field
  never collapses the whole vignette to Neutral, only that one field falls back on its own. These
  two different fallback philosophies coexist deliberately in this module: one governs whether the
  effect applies AT ALL (shape/intensity/progressivity), the other governs WHERE/how wide it is.
- The boundary test (ellipse or line-band) is 100% analytic NumPy -- no PIL needed, unlike
  light.py's polygon mask, since an ellipse and a band both have a closed-form inequality. The
  pixel grid is rotated (a plain cos/sin coordinate rotation, not an image warp) into the shape's
  own local frame before testing.
- Feathering reuses light.py's exact `_polygon_mask` technique (copied here per this codebase's
  cross-addon-duplication convention, since addon modules are loaded without sys.modules
  registration): convert `feather_width` (a percentage of the image's own smaller dimension) to an
  absolute pixel radius, then apply `_box_blur` TWICE at half that radius each -- a cheap
  Gaussian/triangular-falloff approximation with no scipy dependency. The resulting smooth alpha
  (0 = inside the safe zone, 1 = fully outside) feeds into `t = 1 - alpha`, then the EXISTING
  `t_shaped = t ** gamma(progressivity)` / `mask = 1 - intensity*t_shaped` pipeline, unchanged --
  Progressivity still reshapes the transition's curve on top of the new geometric/feather width.
- The old fixed, image-centered `_round_central_distance`/`_linear_top_bottom_distance` and their
  `_ROUND_D0`/`_ROUND_D_MAX`/`_LINEAR_D0`/`_LINEAR_D_MAX` constants are gone -- the ellipse/band's
  position, size, and rotation are now user-editable instead of fixed. The new fields' defaults
  (`radius_x=radius_y=0.85`, `top_offset=bottom_offset=0.6`) deliberately echo the OLD safe-zone
  footprint for a visual family resemblance with the already-shipped presets, not a pixel-exact
  equivalence (accepted precedent: light.py's own v1->v2 rescale, Decision 11).
- The static `gradient_lines` guide overlay is removed: it would otherwise show a stale, fixed
  y=0.2/0.8 hint once `top_offset`/`bottom_offset` are user-editable and no longer match it.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission
from lumaflow.addons.parameters import NumericSliderConstraints, ParameterDescription

_SHAPES = frozenset({"round_central", "linear_top_bottom"})


def _read_float(params: dict[str, Any], key: str, *, minimum: float, maximum: float) -> Optional[float]:
    """Reads one field defensively -- missing, non-numeric, or out-of-range all return None (the
    caller's own signal that this whole step falls back to Neutral, Decision 2)."""
    if key not in params:
        return None
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value < minimum or value > maximum:
        return None
    return value


def _gamma(progressivity: float) -> float:
    return 0.3 + 2.7 * (1.0 - progressivity)


def _box_blur(channel: numpy.ndarray, radius: int) -> numpy.ndarray:
    """Deterministic separable box blur via prefix sums -- no scipy dependency. radius <= 0 is a
    no-op. Copied verbatim from light.py/color_splash.py's own primitive (cross-addon duplication
    convention, see module docstring)."""
    if radius <= 0:
        return channel
    size = 2 * radius + 1

    def _blur_axis(data: numpy.ndarray, axis: int) -> numpy.ndarray:
        pad_width = [(0, 0), (0, 0)]
        pad_width[axis] = (radius, radius)
        padded = numpy.pad(data, pad_width, mode="edge")
        cumsum = numpy.cumsum(padded, axis=axis)
        zero_pad_width = [(0, 0), (0, 0)]
        zero_pad_width[axis] = (1, 0)
        cumsum = numpy.pad(cumsum, zero_pad_width)
        n = cumsum.shape[axis]
        upper_index = [slice(None), slice(None)]
        upper_index[axis] = slice(size, n)
        lower_index = [slice(None), slice(None)]
        lower_index[axis] = slice(0, n - size)
        upper = cumsum[tuple(upper_index)]
        lower = cumsum[tuple(lower_index)]
        return (upper - lower) / size

    return _blur_axis(_blur_axis(channel, axis=0), axis=1)


# ---------------------------------------------------------------------------
# Geometry/feather fields (dynamic-aids pass) -- independent per-key fallback, deliberately
# distinct from shape/intensity/progressivity's coupled all-or-nothing convention above.
# ---------------------------------------------------------------------------

_CENTER_DEFAULT = 0.5
_CENTER_MINIMUM, _CENTER_MAXIMUM = -0.5, 1.5

_RADIUS_DEFAULT = 0.85
_RADIUS_MINIMUM, _RADIUS_MAXIMUM = 0.05, 2.0
# Defense-in-depth guard against a near-zero radius denominator (NaN/Inf) -- a second, independent
# safety net beyond the parameter-level clamp above, mirroring light.py's _compose_region's own
# "clip the RESULT again" convention.
_RADIUS_EPSILON = 1e-3

_OFFSET_DEFAULT = 0.6
_OFFSET_MINIMUM, _OFFSET_MAXIMUM = 0.05, 1.5

_ROTATION_DEFAULT = 0.0
_ROTATION_MINIMUM, _ROTATION_MAXIMUM = -180.0, 180.0

_FEATHER_DEFAULT = 12.0
_FEATHER_MINIMUM, _FEATHER_MAXIMUM = 0.0, 40.0


def _read_clamped(params: dict[str, Any], key: str, default: float, *, minimum: float, maximum: float) -> float:
    """Missing/non-numeric -> `default`; numeric but out-of-range -> clamped to [minimum,maximum]
    (geometry.py's `_resolve_corners` convention -- a spatial coordinate degrades smoothly)."""
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return min(max(float(value), minimum), maximum)


def _read_or_default(params: dict[str, Any], key: str, default: float, *, minimum: float, maximum: float) -> float:
    """Missing, non-numeric, OR out-of-range -> `default` (geometry.py's `_resolve_angle` / light.
    py's `mask_feather` convention -- an angle/width has no meaningful partial-clamp reading)."""
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    if value < minimum or value > maximum:
        return default
    return value


def _resolve_geometry(params: dict[str, Any]) -> dict[str, float]:
    """Resolves all 8 geometry/feather fields independently -- always returns a complete dict of
    real, in-range values (own declared defaults where a field is missing/malformed), regardless
    of whether `shape`/`intensity`/`progressivity` themselves are valid."""
    return {
        "center_x": _read_clamped(params, "center_x", _CENTER_DEFAULT, minimum=_CENTER_MINIMUM, maximum=_CENTER_MAXIMUM),
        "center_y": _read_clamped(params, "center_y", _CENTER_DEFAULT, minimum=_CENTER_MINIMUM, maximum=_CENTER_MAXIMUM),
        "radius_x": _read_clamped(params, "radius_x", _RADIUS_DEFAULT, minimum=_RADIUS_MINIMUM, maximum=_RADIUS_MAXIMUM),
        "radius_y": _read_clamped(params, "radius_y", _RADIUS_DEFAULT, minimum=_RADIUS_MINIMUM, maximum=_RADIUS_MAXIMUM),
        "top_offset": _read_clamped(params, "top_offset", _OFFSET_DEFAULT, minimum=_OFFSET_MINIMUM, maximum=_OFFSET_MAXIMUM),
        "bottom_offset": _read_clamped(params, "bottom_offset", _OFFSET_DEFAULT, minimum=_OFFSET_MINIMUM, maximum=_OFFSET_MAXIMUM),
        "rotation_angle": _read_or_default(params, "rotation_angle", _ROTATION_DEFAULT, minimum=_ROTATION_MINIMUM, maximum=_ROTATION_MAXIMUM),
        "feather_width": _read_or_default(params, "feather_width", _FEATHER_DEFAULT, minimum=_FEATHER_MINIMUM, maximum=_FEATHER_MAXIMUM),
    }


def _rotated_offsets(
    height: int, width: int, center_x: float, center_y: float, rotation_angle: float
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Each pixel's offset from `(center_x, center_y)`, in the same per-axis [-1,1]-normalized
    space the original fixed-shape engine used (preserves the image's own aspect correction: a
    radius/offset of 1.0 reaches half the image's own width/height), rotated by `-rotation_angle`
    into the shape's own local frame (`rx` along the shape's own horizontal axis, `ry` along its
    own vertical/normal axis). A plain coordinate rotation -- no image resampling involved.

    `dx`/`dy` are each independently normalized to their OWN axis's half-dimension, so for a
    non-square image (virtually every real photo) they are NOT the same physical unit -- rotating
    that anisotropic pair directly (as an earlier version of this function did) shears the shape
    instead of rotating it rigidly, making an ellipse visibly change proportions as rotation_angle
    changes (found via a manual repro: any non-square image, radius_x != radius_y, rotate the
    ellipse). The fix rescales by the image's own aspect ratio before/after the rotation terms so
    the rotation itself happens in an isotropic (aspect-consistent) unit, while the per-axis
    normalization is still applied along the image's OWN x/y axes -- exactly reproducing the old
    formula at rotation_angle=0 (cos=1, sin=0 regardless of aspect) or for a square image
    (aspect=1)."""
    y = numpy.linspace(0.0, 1.0, height, dtype=numpy.float32)[:, numpy.newaxis]
    x = numpy.linspace(0.0, 1.0, width, dtype=numpy.float32)[numpy.newaxis, :]
    dx, dy = numpy.broadcast_arrays((x - center_x) * 2.0, (y - center_y) * 2.0)
    angle = numpy.radians(-rotation_angle)
    cos_a, sin_a = numpy.cos(angle), numpy.sin(angle)
    aspect = width / height
    rx = dx * cos_a - (dy / aspect) * sin_a
    ry = dx * aspect * sin_a + dy * cos_a
    return rx.astype(numpy.float32), ry.astype(numpy.float32)


def _ellipse_inside(rx: numpy.ndarray, ry: numpy.ndarray, radius_x: float, radius_y: float) -> numpy.ndarray:
    safe_radius_x = max(radius_x, _RADIUS_EPSILON)
    safe_radius_y = max(radius_y, _RADIUS_EPSILON)
    return ((rx / safe_radius_x) ** 2 + (ry / safe_radius_y) ** 2) <= 1.0


def _line_band_inside(ry: numpy.ndarray, top_offset: float, bottom_offset: float) -> numpy.ndarray:
    # Image y=0 is the TOP, y=1 is the BOTTOM -- ry is negative above the center line (toward the
    # top) and positive below it (toward the bottom), so `top_offset` bounds the negative side and
    # `bottom_offset` bounds the positive side.
    return (ry >= -top_offset) & (ry <= bottom_offset)


def _feather_alpha(inside: numpy.ndarray, feather_width: float, height: int, width: int) -> numpy.ndarray:
    """Converts the hard 0/1 "inside the safe zone" boolean mask into a smooth alpha via the SAME
    feather_pct -> pixel-radius -> two-pass `_box_blur` technique as light.py's `_polygon_mask`
    (Masque Sujet) -- `feather_width` is a percentage of the image's own smaller dimension."""
    alpha = inside.astype(numpy.float32)
    radius = max(0, int(round(feather_width / 100.0 * min(height, width))))
    if radius > 0:
        half = max(1, radius // 2)
        alpha = _box_blur(_box_blur(alpha, half), half)
    # A box blur of values already within [0,1] cannot mathematically leave that range, but the
    # cumsum-based implementation can overshoot by a tiny floating-point epsilon -- clip defensively
    # so `t = 1 - alpha` never goes fractionally negative (a fractional power of a negative number,
    # via `_gamma`, would otherwise produce NaN pixels -- see t_shaped in `vignette`).
    return numpy.clip(alpha, 0.0, 1.0)


def vignette(image: numpy.ndarray, params: dict[str, Any]) -> numpy.ndarray:
    """Vignetting processing_function. Never raises; does not mutate `image`. `shape` not one of
    the two recognized values, or `intensity`/`progressivity` missing/non-numeric/out-of-range
    with an otherwise-valid `shape`, returns `image` unchanged (all-or-nothing coupled-triple
    fallback, Decision 2) -- independent of whether any geometry/feather field is itself valid."""
    shape = params.get("shape")
    if shape not in _SHAPES:
        return image

    intensity = _read_float(params, "intensity", minimum=0.0, maximum=1.0)
    progressivity = _read_float(params, "progressivity", minimum=0.0, maximum=1.0)
    if intensity is None or progressivity is None:
        return image
    if intensity == 0.0:
        return image

    geometry = _resolve_geometry(params)
    height, width = image.shape[0], image.shape[1]
    rx, ry = _rotated_offsets(
        height, width, geometry["center_x"], geometry["center_y"], geometry["rotation_angle"]
    )
    if shape == "round_central":
        inside = _ellipse_inside(rx, ry, geometry["radius_x"], geometry["radius_y"])
    else:
        inside = _line_band_inside(ry, geometry["top_offset"], geometry["bottom_offset"])

    alpha = _feather_alpha(inside, geometry["feather_width"], height, width)
    t = 1.0 - alpha
    t_shaped = t ** _gamma(progressivity)
    mask = 1.0 - intensity * t_shaped

    result = image.astype(numpy.float32) * mask[..., numpy.newaxis]
    return numpy.clip(result, 0.0, 255.0).round().astype(numpy.uint8)


def resolve_zoom_values(params: dict[str, Any]) -> dict[str, float]:
    """Seeds the Zoom sliders with every value actually in effect (F-040 Decision 10). The 8
    geometry/feather fields always resolve via `_resolve_geometry` regardless of `shape`'s
    validity. `intensity`/`progressivity` keep their own special-case:

    `zoom_pure_default_values`'s "Réinitialiser" probe strips every key down to a synthetic
    `{"look": ..., "intensity": 1.0}` -- a convention shaped around Film/Light/Monochrome's own
    "look-calibrated-at-full-intensity" reset target. This addon has no "look" concept, and its
    own "intensity" means something else entirely (raw darkening strength, not a look/original
    blend), so that probe would otherwise wrongly seed Reset at full-strength darkening. It's
    recognized by the absence of "shape" (real effective params always carry one when a preset is
    active; Neutral's real params lack one too, but coincide with the same 0.0/0.0 answer either
    way) and answered with this addon's own true neutral (0.0/0.0), not the injected 1.0.
    """
    geometry = _resolve_geometry(params)
    if "shape" not in params:
        return {"intensity": 0.0, "progressivity": 0.0, **geometry}
    intensity = _read_float(params, "intensity", minimum=0.0, maximum=1.0)
    progressivity = _read_float(params, "progressivity", minimum=0.0, maximum=1.0)
    return {
        "intensity": intensity if intensity is not None else 0.0,
        "progressivity": progressivity if progressivity is not None else 0.0,
        **geometry,
    }


def _geometry_parameter_descriptions() -> tuple[ParameterDescription, ...]:
    return (
        ParameterDescription(
            identifier="center_x", label="Center X", kind="numeric_slider", default=_CENTER_DEFAULT,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=_CENTER_MINIMUM, maximum=_CENTER_MAXIMUM, step=0.001),
        ),
        ParameterDescription(
            identifier="center_y", label="Center Y", kind="numeric_slider", default=_CENTER_DEFAULT,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=_CENTER_MINIMUM, maximum=_CENTER_MAXIMUM, step=0.001),
        ),
        ParameterDescription(
            identifier="radius_x", label="Radius X", kind="numeric_slider", default=_RADIUS_DEFAULT,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=_RADIUS_MINIMUM, maximum=_RADIUS_MAXIMUM, step=0.01),
        ),
        ParameterDescription(
            identifier="radius_y", label="Radius Y", kind="numeric_slider", default=_RADIUS_DEFAULT,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=_RADIUS_MINIMUM, maximum=_RADIUS_MAXIMUM, step=0.01),
        ),
        ParameterDescription(
            identifier="top_offset", label="Top Offset", kind="numeric_slider", default=_OFFSET_DEFAULT,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=_OFFSET_MINIMUM, maximum=_OFFSET_MAXIMUM, step=0.01),
        ),
        ParameterDescription(
            identifier="bottom_offset", label="Bottom Offset", kind="numeric_slider", default=_OFFSET_DEFAULT,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=_OFFSET_MINIMUM, maximum=_OFFSET_MAXIMUM, step=0.01),
        ),
        ParameterDescription(
            identifier="rotation_angle", label="Rotation", kind="numeric_slider", default=_ROTATION_DEFAULT,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=_ROTATION_MINIMUM, maximum=_ROTATION_MAXIMUM, step=0.1),
        ),
        ParameterDescription(
            identifier="feather_width", label="Feather Width", kind="numeric_slider", default=_FEATHER_DEFAULT,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=_FEATHER_MINIMUM, maximum=_FEATHER_MAXIMUM, step=0.5),
        ),
    )


ADDON_DESCRIPTION = AddonSubmission(
    identifier="vignetting",
    label="Vignetage",
    category="vignette",
    thumbnail_presets=(
        ThumbnailPreset(identifier="neutral", label="Neutre", neutral=True),
        ThumbnailPreset(
            identifier="Round Central", label="Round Central",
            preset_parameters={"shape": "round_central", "intensity": 0.35, "progressivity": 0.6},
        ),
        ThumbnailPreset(
            identifier="Linear Top+Bottom", label="Linear Top+Bottom",
            preset_parameters={"shape": "linear_top_bottom", "intensity": 0.3, "progressivity": 0.6},
        ),
    ),
    processing_function=vignette,
    resolve_zoom_values=resolve_zoom_values,
    parameter_descriptions=(
        ParameterDescription(
            identifier="intensity", label="Intensity", kind="numeric_slider", default=0.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.01),
        ),
        ParameterDescription(
            identifier="progressivity", label="Progressivity", kind="numeric_slider", default=0.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.01),
        ),
        *_geometry_parameter_descriptions(),
    ),
)
