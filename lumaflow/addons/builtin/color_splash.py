# LumaFlow v1.0 (2026-08-07)
# Addon Color Splash : desature l'image sauf jusqu'a 3 intervalles de teinte
# actifs simultanement (presets Rouge/Orange/Jaune/Vert/Bleu/Violet).
"""Color Splash addon v1 -- Neutral + 6 named hue presets (Rouge/Orange/Jaune/Vert/Bleu/
Violet), desaturating the whole image except up to 3 simultaneous, independently
adjustable color ranges (feature 046).

No Qt, no pipeline engine, no persistence module import (same convention as every module
under lumaflow/addons/). Loaded via `importlib.util.spec_from_file_location` WITHOUT being
registered in `sys.modules` (see lumaflow/addons/builtin/film.py's module docstring for the
`@dataclass` vs `NamedTuple` gotcha this implies) -- internal structures here use
`typing.NamedTuple`, never `@dataclass`.

Engine design: reuses film.py's cosine-window
hue-masking formula (`_apply_hsl_saturation_by_hue`), duplicated here rather than imported
(addon modules are self-contained, no cross-addon imports) and generalized with a
*configurable* half-width ("feather") instead of film.py's fixed 40 degrees. Up to 3 ranges
combine via `numpy.maximum` (union, not sum) so overlapping ranges never oversaturate.

Application zones (2026-08-24): each range additionally carries its OWN spatial zone -- a
freeform polygon restricting where that range's colorization applies, everything outside
falling back to the desaturated "background" treatment. The polygon model, its flat scalar
wire encoding and its rasterizer are the ones already validated by light.py's subject mask,
recopied here (never imported -- see the loader note above). Zones are `transient=True`: they
are edited in Zoom like any other parameter but never written into a saved recipe, so a
reloaded preset always applies to the whole image.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import numpy
from PIL import Image as PILImage, ImageDraw

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission
from lumaflow.addons.parameters import HueRangeConstraints, NumericSliderConstraints, ParameterDescription

_RANGE_COUNT = 3

# Per-range application zone (see the module docstring): flattened to fixed-capacity scalar keys
# rather than a new ParameterDescription.kind, because the Zoom wire is float-scalar-only end to
# end -- identical convention to light.py's own mask, just prefixed by `range_{N}_` since there
# are three independent zones here instead of one. `..._mask_point_count < 3` resolves to NO zone,
# i.e. the range applies to the whole image (the default, and the pre-zones behavior).
_MAX_MASK_VERTICES = 32
# What the frontend seeds a freshly opened zone editor with: the full frame. Combined with a 0%
# default feather (below), such a polygon is exactly equivalent to no zone at all -- opening the
# editor therefore never changes the render on its own. A non-zero default feather would instead
# fade the colorization along the photo's own borders.
_FULL_FRAME_POINTS: tuple[tuple[float, float], ...] = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))

# Generic declared defaults for every atomic parameter this addon reads -- used both by
# `_read_range`/`_read_mask`/`_resolve_globals` (per-field defensive fallback) and by
# `resolve_zoom_values` (Zoom overlay slider seeding). Single source of truth so the two never
# drift apart.
_GENERIC_DEFAULTS: dict[str, float] = {"background_desaturation": 100.0, "saturation_threshold": 15.0}
for _i in range(1, _RANGE_COUNT + 1):
    _GENERIC_DEFAULTS[f"range_{_i}_enabled"] = 0.0
    _GENERIC_DEFAULTS[f"range_{_i}_hue_center"] = 0.0
    _GENERIC_DEFAULTS[f"range_{_i}_feather"] = 30.0
    _GENERIC_DEFAULTS[f"range_{_i}_saturation_boost"] = 100.0
    # Unlike light.py -- whose resolver seeds 4 so a fresh Zoom session shows its default
    # rectangle -- the vertex count defaults to 0 on BOTH paths here: "no zone" is the resting
    # state this addon must return to on Réinitialiser and on every recipe reload.
    _GENERIC_DEFAULTS[f"range_{_i}_mask_point_count"] = 0.0
    _GENERIC_DEFAULTS[f"range_{_i}_mask_feather"] = 0.0
    _GENERIC_DEFAULTS[f"range_{_i}_mask_invert"] = 0.0
    for _vertex in range(_MAX_MASK_VERTICES):
        _x, _y = _FULL_FRAME_POINTS[_vertex] if _vertex < len(_FULL_FRAME_POINTS) else (0.5, 0.5)
        _GENERIC_DEFAULTS[f"range_{_i}_mask_point_{_vertex:02d}_x"] = _x
        _GENERIC_DEFAULTS[f"range_{_i}_mask_point_{_vertex:02d}_y"] = _y


def _rgb_to_hsl(rgb: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    """rgb: float32 (H, W, 3) in 0..255. Returns (h in 0..360, s in 0..1, l in 0..1). Own copy
    of film.py's utility -- addon modules don't import each other."""
    normalized = rgb / 255.0
    r, g, b = normalized[..., 0], normalized[..., 1], normalized[..., 2]
    maxc = numpy.maximum(numpy.maximum(r, g), b)
    minc = numpy.minimum(numpy.minimum(r, g), b)
    luminance = (maxc + minc) / 2.0
    delta = maxc - minc
    saturation = numpy.where(
        delta < 1e-6, 0.0, delta / (1.0 - numpy.abs(2.0 * luminance - 1.0) + 1e-6)
    )
    delta_safe = numpy.where(delta < 1e-6, 1.0, delta)
    hue = 4.0 + (r - g) / delta_safe
    hue = numpy.where(maxc == g, 2.0 + (b - r) / delta_safe, hue)
    hue = numpy.where(maxc == r, ((g - b) / delta_safe) % 6.0, hue)
    hue = numpy.where(delta < 1e-6, 0.0, hue * 60.0)
    return hue % 360.0, numpy.clip(saturation, 0.0, 1.0), luminance


def _hsl_to_rgb(hue: numpy.ndarray, saturation: numpy.ndarray, luminance: numpy.ndarray) -> numpy.ndarray:
    """Inverse of _rgb_to_hsl -- returns float32 (H, W, 3) in 0..255."""
    hue = hue % 360.0
    chroma = (1.0 - numpy.abs(2.0 * luminance - 1.0)) * saturation
    h_prime = hue / 60.0
    x = chroma * (1.0 - numpy.abs(h_prime % 2.0 - 1.0))
    zeros = numpy.zeros_like(hue)
    conditions = [
        (h_prime >= 0.0) & (h_prime < 1.0),
        (h_prime >= 1.0) & (h_prime < 2.0),
        (h_prime >= 2.0) & (h_prime < 3.0),
        (h_prime >= 3.0) & (h_prime < 4.0),
        (h_prime >= 4.0) & (h_prime < 5.0),
        (h_prime >= 5.0) & (h_prime < 6.0),
    ]
    r1 = numpy.select(conditions, [chroma, x, zeros, zeros, x, chroma], default=zeros)
    g1 = numpy.select(conditions, [x, chroma, chroma, x, zeros, zeros], default=zeros)
    b1 = numpy.select(conditions, [zeros, zeros, x, chroma, chroma, x], default=zeros)
    m = luminance - chroma / 2.0
    return numpy.stack([r1 + m, g1 + m, b1 + m], axis=-1) * 255.0


def _hue_window_weight(hue: numpy.ndarray, center: float, feather: float) -> numpy.ndarray:
    """Cosine-weighted window: 1.0 at `center`, falling smoothly to 0.0
    at `feather` degrees away, 0.0 beyond. Same formula as film.py's
    `_apply_hsl_saturation_by_hue`, but `feather` is a per-call argument here instead of a fixed
    40.0 -- this is what makes the transition width a user-facing "adoucissement" control (FR-006)
    rather than a baked-in constant.
    """
    angular_distance = numpy.abs(((hue - center + 180.0) % 360.0) - 180.0)
    return numpy.where(
        angular_distance <= feather,
        0.5 * (1.0 + numpy.cos(angular_distance / feather * numpy.pi)),
        0.0,
    )


class _RangeParams(NamedTuple):
    enabled: bool
    hue_center: float
    feather: float
    saturation_boost: float


def _read_float(
    params: dict[str, Any], key: str, default: float, *, minimum: float | None = None,
    maximum: float | None = None, wrap: bool = False,
) -> float:
    """Reads one atomic parameter defensively -- a missing, non-numeric, or boolean value falls
    back to its OWN default rather than discarding the whole step (FR-017, same convention as
    framing.py's `_resolve_box`). `wrap=True` normalizes a cyclic value (hue) modulo 360 instead
    of clamping -- there is no such thing as an out-of-range hue.
    """
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        value = default
    value = float(value)
    if wrap:
        return value % 360.0
    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _read_range(params: dict[str, Any], index: int) -> _RangeParams:
    prefix = f"range_{index}"
    enabled_value = _read_float(params, f"{prefix}_enabled", _GENERIC_DEFAULTS[f"{prefix}_enabled"])
    return _RangeParams(
        enabled=enabled_value >= 0.5,
        hue_center=_read_float(
            params, f"{prefix}_hue_center", _GENERIC_DEFAULTS[f"{prefix}_hue_center"], wrap=True
        ),
        feather=_read_float(
            params, f"{prefix}_feather", _GENERIC_DEFAULTS[f"{prefix}_feather"], minimum=5.0, maximum=90.0
        ),
        saturation_boost=_read_float(
            params, f"{prefix}_saturation_boost", _GENERIC_DEFAULTS[f"{prefix}_saturation_boost"],
            minimum=0.0, maximum=200.0,
        ),
    )


# ---------------------------------------------------------------------------
# Per-range application zone. Recopied from light.py's subject mask (_read_bool/_read_mask/
# _box_blur/_polygon_mask) rather than imported -- addon modules are loaded via
# `spec_from_file_location` without sys.modules registration, so a cross-addon import breaks.
# light.py's `_mask_bounding_box` is deliberately NOT recopied: it only pays off for Light's
# two-full-grades composite, whereas the cost here is a single HSL pass already done over the
# whole image.
# ---------------------------------------------------------------------------


class _MaskSpec(NamedTuple):
    points: tuple[tuple[float, float], ...]
    feather_pct: float
    invert: bool


def _read_bool(params: dict[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, None)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value) >= 0.5


def _read_mask(params: dict[str, Any], prefix: str) -> _MaskSpec | None:
    """Resolves one range's zone polygon from its flat scalar keys -- `count < 3` (missing,
    malformed, or explicitly below 3) returns `None`, meaning the range applies to the whole image
    (the degenerate-polygon case: a near-zero-vertex "shape" is treated as no zone at all, never an
    error). Same per-key defensive fallback as everything else here (FR-017): a single corrupted
    vertex reverts to its own full-frame corner without invalidating the rest of the polygon."""
    count = int(_read_float(
        params, f"{prefix}mask_point_count", _GENERIC_DEFAULTS[f"{prefix}mask_point_count"],
        minimum=0.0, maximum=float(_MAX_MASK_VERTICES),
    ))
    if count < 3:
        return None
    points = []
    for i in range(count):
        points.append((
            _read_float(
                params, f"{prefix}mask_point_{i:02d}_x", _GENERIC_DEFAULTS[f"{prefix}mask_point_{i:02d}_x"],
                minimum=0.0, maximum=1.0,
            ),
            _read_float(
                params, f"{prefix}mask_point_{i:02d}_y", _GENERIC_DEFAULTS[f"{prefix}mask_point_{i:02d}_y"],
                minimum=0.0, maximum=1.0,
            ),
        ))
    return _MaskSpec(
        points=tuple(points),
        feather_pct=_read_float(
            params, f"{prefix}mask_feather", _GENERIC_DEFAULTS[f"{prefix}mask_feather"], minimum=0.0, maximum=20.0
        ),
        invert=_read_bool(params, f"{prefix}mask_invert", False),
    )


def _box_blur(channel: numpy.ndarray, radius: int) -> numpy.ndarray:
    """Deterministic separable box blur via prefix sums -- no scipy dependency. radius <= 0 is a
    no-op. Own copy of light.py's utility."""
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
        return (cumsum[tuple(upper_index)] - cumsum[tuple(lower_index)]) / size

    return _blur_axis(_blur_axis(channel, axis=0), axis=1)


def _polygon_mask(
    shape: tuple[int, ...], points: tuple[tuple[float, float], ...], feather_pct: float, invert: bool
) -> numpy.ndarray:
    """Rasterizes the polygon via PIL.ImageDraw (handles arbitrary, including self-intersecting,
    polygons via scanline fill with no crash risk), then feathers the hard edge via two
    `_box_blur` passes at half the feather radius each (triangular ~= gaussian falloff). Recomputed
    from the actual array `shape` on every call -- never cached across resolutions, so a zone is
    geometrically identical for the reduced-resolution preview and the full-resolution render.
    The final clip guards the known box-blur overshoot (two passes over a strictly 0..1 input can
    return 1 + epsilon)."""
    height, width = shape[0], shape[1]
    canvas = PILImage.new("L", (width, height), 0)
    ImageDraw.Draw(canvas).polygon([(x * width, y * height) for x, y in points], fill=255)
    mask = numpy.asarray(canvas, dtype=numpy.float32) / 255.0
    radius = max(0, int(round(feather_pct / 100.0 * min(height, width))))
    if radius > 0:
        half = max(1, radius // 2)
        mask = _box_blur(_box_blur(mask, half), half)
    return numpy.clip(1.0 - mask if invert else mask, 0.0, 1.0)


def color_splash(image: numpy.ndarray, params: dict[str, Any]) -> numpy.ndarray:
    """Color Splash addon transform. Returns `image` unchanged,
    bit-identical (SC-001), in two cases: no recognized key at all in `params` (Neutral -- no
    preset_parameters, or a Zoom session with every override cleared), OR every range ends up
    disabled once each field is read defensively (FR-017 -- this is what makes a corrupted/
    malformed recipe, where `range_N_enabled` is missing or unreadable, degrade to Neutre rather
    than to "every pixel desaturated": `background_desaturation` alone has no effect without at
    least one active range, by design, not merely as a side effect of the blend formula below).
    Never raises; does not mutate `image`.
    """
    if not any(key in params for key in _GENERIC_DEFAULTS):
        return image

    ranges = [_read_range(params, index) for index in range(1, _RANGE_COUNT + 1)]
    if not any(r.enabled for r in ranges):
        return image

    background_desaturation = _read_float(
        params, "background_desaturation", _GENERIC_DEFAULTS["background_desaturation"],
        minimum=0.0, maximum=100.0,
    )
    saturation_threshold = _read_float(
        params, "saturation_threshold", _GENERIC_DEFAULTS["saturation_threshold"], minimum=0.0, maximum=100.0,
    )

    source = image.astype(numpy.float32)
    hue, saturation, luminance = _rgb_to_hsl(source)

    combined_weight = numpy.zeros_like(saturation)
    boost_numerator = numpy.zeros_like(saturation)
    for index, range_params in enumerate(ranges, start=1):
        if not range_params.enabled:
            continue
        weight = _hue_window_weight(hue, range_params.hue_center, range_params.feather)
        # The range's own application zone, if one is drawn: multiplying its hue weight by the
        # polygon's alpha confines that range spatially BEFORE the union/boost blend below, so a
        # pixel outside every active range's zone ends up with combined_weight == 0 and takes the
        # `background_saturation` branch -- i.e. it goes black and white, exactly like a pixel
        # whose hue matches no range at all. No zone (the default) costs nothing: `_read_mask`
        # returns None without rasterizing anything.
        mask = _read_mask(params, f"range_{index}_")
        if mask is not None:
            weight = weight * _polygon_mask(image.shape, mask.points, mask.feather_pct, mask.invert)
        combined_weight = numpy.maximum(combined_weight, weight)
        # Per-range boosts are blended by their own local weight (not just the first/strongest
        # range's boost) so an overlap zone between two active ranges with different boosts
        # reads as a smooth mix, not a hard flip from one range's setting to the other's.
        boost_numerator = boost_numerator + weight * range_params.saturation_boost

    # A pixel whose hue falls in an active range but whose ORIGINAL saturation is below the
    # threshold is never eligible (FR-008 edge case: a near-gray pixel must not "jump" into
    # color) -- a hard gate on the combined mask, not a soft blend.
    gate = saturation >= (saturation_threshold / 100.0)
    gated_weight = numpy.where(gate, combined_weight, 0.0)

    effective_boost = numpy.where(combined_weight > 1e-6, boost_numerator / numpy.maximum(combined_weight, 1e-6), 100.0)
    kept_saturation = saturation * (effective_boost / 100.0)
    background_saturation = saturation * (1.0 - background_desaturation / 100.0)
    final_saturation = numpy.clip(
        gated_weight * kept_saturation + (1.0 - gated_weight) * background_saturation, 0.0, 1.0
    )

    result = _hsl_to_rgb(hue, final_saturation, luminance)
    return numpy.clip(result, 0, 255).round().astype(numpy.uint8)


def resolve_zoom_values(params: dict[str, Any]) -> dict[str, float]:
    """Given a step's current parameter values, returns the EFFECTIVE value of every zoom
    parameter this addon declares -- an override present in `params` wins, otherwise the generic
    declared default. Simpler than film.py's resolver: there is no separate per-look calibration
    table to fall back to here -- a preset's own `preset_parameters` already IS the override,
    written directly into the step's parameters by `_resolve_preset_parameter_values`
    (lumaflow/api/session.py). Used by the Zoom
    overlay (via AddonDescriptor.resolve_zoom_values) to seed the ring/sliders with what's
    actually in effect instead of a generic default.

    Completeness (an entry for every identifier in ADDON_DESCRIPTION.parameter_descriptions,
    including the 3x67 zone parameters) is what seeds the zone editor with the polygon actually in
    effect -- it holds by construction here, since `_GENERIC_DEFAULTS` is the very same dict the
    descriptions read their own defaults from.
    """
    values: dict[str, float] = {}
    for key, default in _GENERIC_DEFAULTS.items():
        value = params.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            value = default
        values[key] = float(value)
    return values


def _mask_parameter_descriptions(index: int) -> tuple[ParameterDescription, ...]:
    """One range's 67 zone parameters, generated rather than written out by hand (same precedent as
    light.py's `_mask_parameter_descriptions`). All `transient=True`: the zone is a session-local,
    image-specific tracing that must never travel in a saved recipe (see
    ZoomParameterDeclaration.transient). All are hidden from the "Réglages manuels" slider list by
    ZoomOverlay.tsx's `isMaskParameter` filter -- they are edited through the polygon overlay, not
    as 67 raw sliders."""
    prefix = f"range_{index}_"
    descriptions = [
        ParameterDescription(
            identifier=f"{prefix}mask_point_count", label=f"Zone {index} — nombre de sommets",
            kind="numeric_slider", default=_GENERIC_DEFAULTS[f"{prefix}mask_point_count"],
            zoom_only=True, transient=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=float(_MAX_MASK_VERTICES), step=1.0),
        ),
        ParameterDescription(
            identifier=f"{prefix}mask_feather", label=f"Zone {index} — adoucissement du contour",
            kind="numeric_slider", default=_GENERIC_DEFAULTS[f"{prefix}mask_feather"],
            zoom_only=True, transient=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=20.0, step=0.5),
        ),
        ParameterDescription(
            identifier=f"{prefix}mask_invert", label=f"Zone {index} — inverser le contour",
            kind="numeric_slider", default=_GENERIC_DEFAULTS[f"{prefix}mask_invert"],
            zoom_only=True, transient=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=1.0),
        ),
    ]
    for vertex in range(_MAX_MASK_VERTICES):
        for axis in ("x", "y"):
            identifier = f"{prefix}mask_point_{vertex:02d}_{axis}"
            descriptions.append(ParameterDescription(
                identifier=identifier, label=f"Zone {index} — sommet {vertex} ({axis})",
                kind="numeric_slider", default=_GENERIC_DEFAULTS[identifier],
                zoom_only=True, transient=True,
                constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.001),
            ))
    return tuple(descriptions)


def _range_parameter_descriptions(index: int) -> tuple[ParameterDescription, ...]:
    prefix = f"range_{index}"
    return (
        ParameterDescription(
            identifier=prefix, label=f"Intervalle {index}", kind="hue_range", default=0.0, zoom_only=True,
            constraints=HueRangeConstraints(
                hue_minimum=0.0, hue_maximum=360.0, hue_default=0.0,
                feather_minimum=5.0, feather_maximum=90.0, feather_default=30.0,
            ),
        ),
        ParameterDescription(
            identifier=f"{prefix}_enabled", label=f"Intervalle {index} actif", kind="numeric_slider",
            default=0.0, zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=1.0),
        ),
        ParameterDescription(
            identifier=f"{prefix}_saturation_boost", label=f"Intensité couleur {index}", kind="numeric_slider",
            default=100.0, zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=200.0, step=1.0),
        ),
        *_mask_parameter_descriptions(index),
    )


ADDON_DESCRIPTION = AddonSubmission(
    identifier="color_splash",
    label="Color Splash",
    category="color_splash",
    # Identifier IS the displayed caption for a non-neutral preset (frontend convention:
    # RowSpec.vignette_labels are raw config identifiers, rendered as-is by
    # web/src/lib/filmstrip.ts's vignetteDisplayText -- it does not read ThumbnailPreset.label at
    # all). French identifiers here, matching film.py's "Classic Chrome"/"Velvia"/etc. convention
    # of identifier==label, rather than English identifiers with a separate French label that
    # would silently never reach the screen.
    thumbnail_presets=(
        ThumbnailPreset(identifier="neutral", label="Neutre", neutral=True),
        ThumbnailPreset(
            identifier="Rouge", label="Rouge",
            preset_parameters={"range_1_enabled": 1.0, "range_1_hue_center": 0.0},
        ),
        ThumbnailPreset(
            identifier="Orange", label="Orange",
            preset_parameters={"range_1_enabled": 1.0, "range_1_hue_center": 30.0},
        ),
        ThumbnailPreset(
            identifier="Jaune", label="Jaune",
            preset_parameters={"range_1_enabled": 1.0, "range_1_hue_center": 60.0},
        ),
        ThumbnailPreset(
            identifier="Vert", label="Vert",
            preset_parameters={"range_1_enabled": 1.0, "range_1_hue_center": 120.0},
        ),
        ThumbnailPreset(
            identifier="Bleu", label="Bleu",
            preset_parameters={"range_1_enabled": 1.0, "range_1_hue_center": 240.0},
        ),
        ThumbnailPreset(
            identifier="Violet", label="Violet",
            preset_parameters={"range_1_enabled": 1.0, "range_1_hue_center": 285.0},
        ),
        # "Brun" was removed post-launch: sharing "Orange"'s hue center and differing only by a
        # raised saturation_threshold produced results visually
        # indistinguishable from "Orange" in practice -- confirmed by the user, not merely a
        # theoretical concern. Not replaced; the raised-threshold approach is not revisited here.
    ),
    processing_function=color_splash,
    parameter_descriptions=(
        *_range_parameter_descriptions(1),
        *_range_parameter_descriptions(2),
        *_range_parameter_descriptions(3),
        ParameterDescription(
            identifier="background_desaturation", label="Désaturation du fond", kind="numeric_slider",
            default=100.0, zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="saturation_threshold", label="Seuil de saturation", kind="numeric_slider",
            default=15.0, zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=100.0, step=1.0),
        ),
    ),
    resolve_zoom_values=resolve_zoom_values,
)
