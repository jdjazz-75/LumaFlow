# LumaFlow v1.0 (2026-08-07)
# Addon Monochrome Tone : duotone/colorisation par teinte unique appliquee
# uniformement sur la luminance (6 presets Rouge/Sepia/Jaune/Vert/Bleu/Violet).
"""Monochrome Tone addon (feature 2026-07-27) -- a dedicated duotone/colorize
addon for the "Monochrome" workflow row, replacing the earlier `film_look`
recipes (Monochrome/Underglow/Gilt Trip, retired the same day per film.py's
module docstring) which the user found unsatisfying.

Unlike Color Splash (which preserves selected ORIGINAL hues and desaturates
the rest), this addon removes all original color first, then colorizes the
resulting monochrome luminance with a SINGLE hue+saturation applied
uniformly across the whole tonal range ("teinte s'applique ici à toute
l'image" -- the user's own spec).

Addon modules never import each other (loaded via
`importlib.util.spec_from_file_location`, `lumaflow/addons/loader.py`,
without registration in `sys.modules` -- `color_splash.py` follows the same
rule, duplicating its own `_rgb_to_hsl`/`_hsl_to_rgb` rather than importing
`film.py`'s). This module therefore carries its own copies of the handful of
`film.py` pixel-math primitives it reuses (tone curve, temperature/tint,
clarity/sharpness, grain, black clip, HSL round-trip) -- same formulas,
duplicated code, per that established convention.

Two rendering primitives needed writing from scratch (confirmed absent
anywhere in the codebase by a full-repo search): the single-hue duotone
colorize itself -- though it needed NO new formula, since `_hsl_to_rgb(hue,
saturation, luminance)` already accepts a luminance channel directly, so
broadcasting a constant hue+saturation over the grayscale luminance IS an
exact duotone -- and `_apply_vignette` (radial edge darkening/lightening,
used only by Sépia Chaud).

Three technical points in the user's original spec needed a resolved
decision, documented here rather than left ambiguous:

1. The user's own 5 reference gradient-map tables (hex colors at 5 luminance
   stops) were decoded to HSL and verified NOT to correspond to a constant
   hue+saturation -- hue drifts up to ~37 degrees across the ramp (e.g. Vert
   Cactus: 100 degrees in shadows to 63 degrees in highlights), saturation
   varies substantially by zone. A literal 5-point gradient-map engine would
   reproduce those swatches exactly but needs an entirely new LUT primitive
   and creates an awkward dual representation with the live Zoom sliders.
   The user explicitly chose the simpler single-hue duotone (this module),
   matching the spec's own explicit "Formule d'application"
   (`resultat = (1-force)*G + force*C(G)`) -- the 5-point alternative is kept
   on record in project memory (`monochrome-tone-gradient-map-alternative.md`)
   for a possible future iteration.
2. "Saturation des couleurs originales" (`original_saturation`, x0..x2,
   neutral x1): implemented as an HSL-saturation pre-scale toward the
   source's own per-pixel Lightness, applied BEFORE the Rec.709 luminance
   extraction (see `_apply_original_saturation`). At x1 (neutral) this is an
   exact identity, so the luminance is exactly the recommended
   `0.2126R+0.7152G+0.0722B` on unmodified pixels. At x0 (the value every one
   of the 5 shipped presets uses), the source is fully desaturated toward its
   own HSL Lightness first, so the resulting luminance equals that Lightness
   -- a standard alternative luma formula, visually very close to Rec.709 for
   the vast majority of photos. A Rec.709-weighted pre-scale toward Rec.709
   luma itself would have been a mathematical no-op for ANY factor (a
   weighted sum of a value lerped toward itself under the same weights
   returns that same value) -- this is why the pre-scale target is HSL
   Lightness, a genuinely different basis, rather than luma again.
3. A few ranges in the spec had no single recommended value, only an
   acceptable band (grain for Ambre/Bleu Nuit/Vert Cactus; contrast/shadows/
   temperature for Jaune Léger) -- each is filled in at the midpoint of the
   given band, commented inline at its calibration.

Revised 2026-07-27 (later the same day): once the Zoom's `ColorWheel` control
existed (a precise 2D hue+saturation picker, `web/src/components/
ColorWheel.tsx`), the user replaced this addon's entire thumbnail set with 6
new colors specified as plain hex codes (Rouge/Sepia/Jaune/Vert/Bleu/Violet),
one level less prescriptive than the original 5-preset spec (no per-preset
force/contrast/grain/etc. given this time, only a target color). The 5
original presets (Ambre/Bleu Nuit/Vert Cactus/Jaune Léger/Sépia Chaud) are
retired. `hue`/`tint_saturation` for each new preset are decoded directly
from the supplied hex via the standard RGB->HLS formula (`colorsys.rgb_to_hls`
-- same algorithm as `web/src/lib/color.ts`'s `hexToHsl`); every supplied hex
happened to sit at exactly 50% lightness, matching `ColorWheel.tsx`'s own
`REFERENCE_LIGHTNESS` constant, suggesting the colors were chosen through that
same tool. The other 9 grade fields (force/contrast/shadows/highlights/
black_point/grain/temperature_shift/tint_magenta/clarity/sharpness/vignette)
have no color-derived value, so all 6 new presets share one flat, moderate
template (documented at its calibration below) rather than guessing distinct
values per preset -- adjustable later via each preset's own Zoom sliders.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import numpy

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission
from lumaflow.addons.parameters import NumericSliderConstraints, ParameterDescription

_TONES = frozenset({"rouge", "sepia", "jaune", "vert", "bleu", "violet"})


def _clip(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


# ---------------------------------------------------------------------------
# Primitives copied from lumaflow/addons/builtin/film.py (same formulas,
# duplicated per this file's own module docstring -- addon modules never
# import each other).
# ---------------------------------------------------------------------------

_GRAIN_SEED = 20260727  # fixed constant, own value distinct from film.py's --
                         # only needs to be deterministic per-image-shape, not
                         # shared across addons.


def _luma(image: numpy.ndarray) -> numpy.ndarray:
    return (
        image[..., 0] * 0.299 + image[..., 1] * 0.587 + image[..., 2] * 0.114
    )


def _rgb_to_hsl(rgb: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    """rgb: float32 (H, W, 3) in 0..255. Returns (h in 0..360, s in 0..1, l in 0..1)."""
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


def _zone_weights(luminance: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray]:
    shadow_weight = numpy.clip((0.5 - luminance) / 0.5, 0.0, 1.0)
    highlight_weight = numpy.clip((luminance - 0.5) / 0.5, 0.0, 1.0)
    return shadow_weight, highlight_weight


def _apply_tone_curve(
    luminance: numpy.ndarray, contrast: float, highlights: float, shadows: float
) -> numpy.ndarray:
    shadow_weight, highlight_weight = _zone_weights(luminance)
    result = luminance + shadow_weight * (shadows / 100.0) * 0.25
    result = result + highlight_weight * (highlights / 100.0) * 0.25
    result = result + (result - 0.5) * (contrast / 100.0) * 0.3
    return numpy.clip(result, 0.0, 1.0)


def _apply_temperature_tint(rgb: numpy.ndarray, temperature: float, tint: float) -> numpy.ndarray:
    result = rgb.copy()
    result[..., 0] *= 1.0 + (temperature / 1000.0) * 0.10
    result[..., 2] *= 1.0 - (temperature / 1000.0) * 0.10
    result[..., 1] *= 1.0 - (tint / 20.0) * 0.05
    return result


def _box_blur(channel: numpy.ndarray, radius: int) -> numpy.ndarray:
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


def _apply_clarity_sharpness(rgb: numpy.ndarray, clarity: float, sharpness: float) -> numpy.ndarray:
    result = rgb
    if clarity != 0.0:
        luma = _luma(result)
        height, width = luma.shape
        radius = max(1, int(round(min(height, width) * 0.02)))
        blurred = _box_blur(luma, radius)
        detail = (luma - blurred) * (clarity / 100.0) * 0.8
        result = result + detail[..., numpy.newaxis]
    if sharpness != 0.0:
        radius = 1
        for channel_index in range(3):
            channel = result[..., channel_index]
            blurred = _box_blur(channel, radius)
            result[..., channel_index] = channel + (channel - blurred) * (sharpness / 100.0) * 0.8
    return result


def _apply_grain(rgb: numpy.ndarray, std: float, size: float) -> numpy.ndarray:
    if std <= 0.0:
        return rgb
    height, width = rgb.shape[0], rgb.shape[1]
    rng = numpy.random.default_rng(_GRAIN_SEED)
    noise = rng.normal(0.0, std * 255.0, size=(height, width)).astype(numpy.float32)
    blur_radius = max(0, int(round(size / 2.0)))
    if blur_radius > 0:
        noise = _box_blur(noise, blur_radius)
    return rgb + noise[..., numpy.newaxis]


def _apply_black_clip(rgb: numpy.ndarray, amount: float) -> numpy.ndarray:
    if amount <= 0.0:
        return rgb
    normalized = numpy.clip(rgb / 255.0, 0.0, 1.0)
    remapped = numpy.clip((normalized - amount) / (1.0 - amount), 0.0, 1.0)
    return remapped * 255.0


def _apply_vignette(rgb: numpy.ndarray, amount: float) -> numpy.ndarray:
    """Radial edge darkening/lightening -- no vignette pixel-math exists
    anywhere else in the codebase (confirmed by a full-repo search), so this
    is a new, self-contained, minimal primitive.
    `amount` -100..100, 0 = no-op: negative darkens the corners, positive
    lightens them. The falloff mask is an elliptical normalized distance from
    center (0 at the center, ~1 at the corners).
    """
    if amount == 0.0:
        return rgb
    height, width = rgb.shape[0], rgb.shape[1]
    y = numpy.linspace(-1.0, 1.0, height, dtype=numpy.float32)[:, numpy.newaxis]
    x = numpy.linspace(-1.0, 1.0, width, dtype=numpy.float32)[numpy.newaxis, :]
    radius = numpy.clip(numpy.sqrt(x ** 2 + y ** 2) / numpy.sqrt(2.0), 0.0, 1.0)
    factor = 1.0 + (amount / 100.0) * radius
    return rgb * factor[..., numpy.newaxis]


# ---------------------------------------------------------------------------
# This addon's own calibration model + pipeline.
# ---------------------------------------------------------------------------


class _ToneParams(NamedTuple):
    """One row of this addon's own parameter scale -- every field's default
    is its neutral value. A plain `typing.NamedTuple`, not `@dataclass`, for
    the same reason as film.py's `_GradeParams` (see that module's docstring)
    -- addon modules are loaded without `sys.modules` registration, which
    breaks `@dataclass`.
    """

    original_saturation: float = 1.0   # x0..x2 (HSL-saturation pre-scale, see module docstring)
    hue: float = 0.0                   # 0..360 deg
    tint_saturation: float = 0.0       # 0..100 (%)
    force: float = 0.0                 # 0..100 (%) -- (1-force)*gray + force*colorized
    contrast: float = 0.0              # -100..100
    shadows: float = 0.0               # -100..100
    highlights: float = 0.0            # -100..100
    black_point: float = 0.0           # 0..0.10
    grain: float = 0.0                 # 0..0.05
    grain_size: float = 1.0            # px (internal-only, not exposed as a slider --
                                        # same convention as film.py's own grain_size)
    temperature_shift: float = 0.0     # -1000..1000 K (approximation, not Planckian)
    tint_magenta: float = 0.0          # -20..20 (green-magenta)
    clarity: float = 0.0               # -100..100
    sharpness: float = 0.0             # -100..100
    vignette: float = 0.0              # -100..100


_NEUTRAL_TONE = _ToneParams()


def _apply_original_saturation(rgb: numpy.ndarray, factor: float) -> numpy.ndarray:
    if factor == 1.0:
        return rgb
    hue, saturation, lightness = _rgb_to_hsl(rgb)
    scaled_saturation = numpy.clip(saturation * factor, 0.0, 1.0)
    return _hsl_to_rgb(hue, scaled_saturation, lightness)


def _apply_tone(image: numpy.ndarray, tone: "_ToneParams") -> numpy.ndarray:
    """The addon's common procedure, in the order the user's spec lays out:
    remove original color -> convert to luminance -> adjust contrast/shadows/
    highlights -> colorize (single hue+saturation, uniformly across the whole
    image, unlike Color Splash's selective preservation) -> blend back toward
    plain grayscale by `force` -> fine post-cast nudge (temperature/tint,
    reusing the exact White-Balance-style primitive film.py already has) ->
    clarity/sharpness/grain/vignette -> black point (last, same ordering
    film.py's own `_apply_monochrome_grade`/`_apply_parametric_grade` use).
    """
    source = _apply_original_saturation(image, tone.original_saturation)
    gray01 = numpy.clip(
        (source[..., 0] * 0.2126 + source[..., 1] * 0.7152 + source[..., 2] * 0.0722) / 255.0,
        0.0,
        1.0,
    )
    gray01 = _apply_tone_curve(gray01, tone.contrast, tone.highlights, tone.shadows)
    gray_rgb = numpy.repeat((gray01 * 255.0)[..., numpy.newaxis], 3, axis=-1)

    hue_field = numpy.full_like(gray01, tone.hue)
    saturation_field = numpy.full_like(gray01, tone.tint_saturation / 100.0)
    colorized = _hsl_to_rgb(hue_field, saturation_field, gray01)

    force = tone.force / 100.0
    result = gray_rgb * (1.0 - force) + colorized * force

    result = _apply_temperature_tint(result, tone.temperature_shift, tone.tint_magenta)
    result = _apply_clarity_sharpness(result, tone.clarity, tone.sharpness)
    result = _apply_grain(result, tone.grain, tone.grain_size)
    result = _apply_vignette(result, tone.vignette)
    result = _apply_black_clip(result, tone.black_point)
    return result


# ---------------------------------------------------------------------------
# The 6 current recipes (2026-07-27, hex-derived revision -- see module
# docstring). `hue`/`tint_saturation` decoded from each supplied hex via
# colorsys.rgb_to_hls; every other field shares one flat, moderate template
# (`original_saturation=0.0` full desaturation, `force=70`, mild S-curve,
# a light default grain) since no per-preset grade was supplied this time.
# ---------------------------------------------------------------------------

_TONE_TEMPLATE = dict(
    original_saturation=0.0,
    force=70.0,
    contrast=8.0,
    shadows=-10.0,
    highlights=-5.0,
    grain=0.010,
)

_ROUGE_TONE = _ToneParams(hue=2.7, tint_saturation=34.9, **_TONE_TEMPLATE)      # #AC5753
_SEPIA_TONE = _ToneParams(hue=42.4, tint_saturation=20.0, **_TONE_TEMPLATE)     # #998A66
_JAUNE_TONE = _ToneParams(hue=55.2, tint_saturation=24.7, **_TONE_TEMPLATE)     # #9F9A60
_VERT_TONE = _ToneParams(hue=108.2, tint_saturation=20.0, **_TONE_TEMPLATE)     # #709966
_BLEU_TONE = _ToneParams(hue=222.9, tint_saturation=57.6, **_TONE_TEMPLATE)     # #3660C9
_VIOLET_TONE = _ToneParams(hue=274.6, tint_saturation=27.8, **_TONE_TEMPLATE)   # #855CA3


def _rouge(image: numpy.ndarray) -> numpy.ndarray:
    return _apply_tone(image, _ROUGE_TONE)


def _sepia(image: numpy.ndarray) -> numpy.ndarray:
    return _apply_tone(image, _SEPIA_TONE)


def _jaune(image: numpy.ndarray) -> numpy.ndarray:
    return _apply_tone(image, _JAUNE_TONE)


def _vert(image: numpy.ndarray) -> numpy.ndarray:
    return _apply_tone(image, _VERT_TONE)


def _bleu(image: numpy.ndarray) -> numpy.ndarray:
    return _apply_tone(image, _BLEU_TONE)


def _violet(image: numpy.ndarray) -> numpy.ndarray:
    return _apply_tone(image, _VIOLET_TONE)


_TONE_TRANSFORMS = {
    "rouge": _rouge,
    "sepia": _sepia,
    "jaune": _jaune,
    "vert": _vert,
    "bleu": _bleu,
    "violet": _violet,
}

_TONE_GRADES: dict[str, "_ToneParams"] = {
    "rouge": _ROUGE_TONE,
    "sepia": _SEPIA_TONE,
    "jaune": _JAUNE_TONE,
    "vert": _VERT_TONE,
    "bleu": _BLEU_TONE,
    "violet": _VIOLET_TONE,
}


# ---------------------------------------------------------------------------
# Zoom overlay (manual sliders) -- same override-wins-else-calibrated pattern
# as film.py's resolve_zoom_values/_apply_grade_overrides.
# ---------------------------------------------------------------------------

_TONE_FIELD_BOUNDS: dict[str, tuple[float, float]] = {
    "original_saturation": (0.0, 2.0),
    "hue": (0.0, 360.0),
    "tint_saturation": (0.0, 100.0),
    "force": (0.0, 100.0),
    "contrast": (-100.0, 100.0),
    "shadows": (-100.0, 100.0),
    "highlights": (-100.0, 100.0),
    "black_point": (0.0, 0.10),
    "grain": (0.0, 0.05),
    "temperature_shift": (-1000.0, 1000.0),
    "tint_magenta": (-20.0, 20.0),
    "clarity": (-100.0, 100.0),
    "sharpness": (-100.0, 100.0),
    "vignette": (-100.0, 100.0),
}

_ZOOM_OVERRIDE_KEYS = frozenset(_TONE_FIELD_BOUNDS)


def _override_numeric(params: dict[str, Any], identifier: str, default: float) -> float:
    value = params.get(identifier, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _apply_tone_overrides(base: "_ToneParams", params: dict[str, Any]) -> "_ToneParams":
    """`hue` wraps (mod 360, matching Color Splash's own `_read_float(...,
    wrap=True)` convention for cyclic hue parameters) rather than clipping;
    every other field is an absolute override, clipped to its natural bounds.
    Returns `base` itself (same object) when nothing is overridden.
    """
    overrides: dict[str, float] = {}
    for field_name, (minimum, maximum) in _TONE_FIELD_BOUNDS.items():
        if field_name not in params:
            continue
        if field_name == "hue":
            overrides["hue"] = _override_numeric(params, "hue", base.hue) % 360.0
        else:
            overrides[field_name] = _clip(
                _override_numeric(params, field_name, getattr(base, field_name)), minimum, maximum
            )
    if not overrides:
        return base
    return base._replace(**overrides)


def resolve_zoom_values(params: dict[str, Any]) -> dict[str, float]:
    """Given a step's current parameter values (e.g. {"preset": "ambre",
    "intensity": 1.0}, optionally plus already-confirmed overrides), returns
    the effective value of every zoom parameter this addon declares -- an
    override present in `params` wins, else the selected preset's own
    calibrated value. An unrecognized/absent `preset` (e.g. "neutral") has no
    calibration to seed from, so only `intensity` is returned.
    """
    intensity = params.get("intensity", 1.0)
    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
        intensity = 1.0
    values: dict[str, float] = {"intensity": float(intensity)}

    tone = _TONE_GRADES.get(params.get("preset"))
    if tone is None:
        return values

    resolved = _apply_tone_overrides(tone, params)
    for field_name in _TONE_FIELD_BOUNDS:
        values[field_name] = float(getattr(resolved, field_name))
    return values


def monochrome_tone(image: numpy.ndarray, params: dict[str, Any]) -> numpy.ndarray:
    """Monochrome Tone addon transform. An unrecognized ``preset`` or
    malformed/out-of-range ``intensity`` fall back to identity. A MISSING
    ``preset`` (Neutral) still honors Zoom-only manual overrides on top of an
    otherwise untouched image via `_NEUTRAL_TONE`, same convention as
    film.py's `film_look` (2026-07-23 fix) -- ordinary Neutral rendering (no
    overrides present) stays a zero-cost passthrough. Never raises; does not
    mutate ``image``.
    """
    preset = params.get("preset")
    if preset is None:
        if not any(key in params for key in _ZOOM_OVERRIDE_KEYS):
            return image
        tone_base = _NEUTRAL_TONE
        intensity = params.get("intensity", 1.0)
    elif preset in _TONE_GRADES:
        tone_base = _TONE_GRADES[preset]
        intensity = params.get("intensity")
    else:
        return image

    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
        return image
    t = float(intensity)
    if t < 0.0 or t > 1.0:
        return image
    if t == 0.0:
        return image

    source = image.astype(numpy.float32)
    tone = _apply_tone_overrides(tone_base, params)
    output = _apply_tone(source, tone)
    if t == 1.0:
        return numpy.clip(output, 0, 255).round().astype(numpy.uint8)
    blended = source * (1.0 - t) + output * t
    return numpy.clip(blended, 0, 255).round().astype(numpy.uint8)


ADDON_DESCRIPTION = AddonSubmission(
    identifier="monochrome_tone",
    label="Monochrome Tone",
    category="monochrome_tone",
    thumbnail_presets=(
        ThumbnailPreset(identifier="neutral", label="Neutre", neutral=True),
        ThumbnailPreset(identifier="Rouge", label="Rouge", preset_parameters={"preset": "rouge", "intensity": 1.0}),
        ThumbnailPreset(identifier="Sepia", label="Sepia", preset_parameters={"preset": "sepia", "intensity": 1.0}),
        ThumbnailPreset(identifier="Jaune", label="Jaune", preset_parameters={"preset": "jaune", "intensity": 1.0}),
        ThumbnailPreset(identifier="Vert", label="Vert", preset_parameters={"preset": "vert", "intensity": 1.0}),
        ThumbnailPreset(identifier="Bleu", label="Bleu", preset_parameters={"preset": "bleu", "intensity": 1.0}),
        ThumbnailPreset(identifier="Violet", label="Violet", preset_parameters={"preset": "violet", "intensity": 1.0}),
    ),
    processing_function=monochrome_tone,
    parameter_descriptions=(
        ParameterDescription(
            identifier="original_saturation", label="Saturation originale", kind="numeric_slider",
            default=1.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=0.01),
        ),
        ParameterDescription(
            identifier="hue", label="Teinte de colorisation", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=360.0, step=1.0),
        ),
        ParameterDescription(
            identifier="tint_saturation", label="Saturation de la teinte", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="force", label="Force de colorisation", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="contrast", label="Contraste", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="shadows", label="Ombres", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="highlights", label="Hautes lumières", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="black_point", label="Point noir", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=0.10, step=0.005),
        ),
        ParameterDescription(
            identifier="grain", label="Grain", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=0.05, step=0.001),
        ),
        ParameterDescription(
            identifier="temperature_shift", label="Température apparente", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-1000.0, maximum=1000.0, step=10.0),
        ),
        ParameterDescription(
            identifier="tint_magenta", label="Teinte vert-magenta", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-20.0, maximum=20.0, step=0.5),
        ),
        # Clarté/Netteté/Vignettage: déclarés pour chaque preset mais actuellement
        # inertes (0) pour les six -- même convention "declare always, inert
        # per-look" que film.py, réglables plus tard via Zoom.
        ParameterDescription(
            identifier="clarity", label="Clarté", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="sharpness", label="Netteté", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="vignette", label="Vignettage", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
    ),
    overlay_descriptions=(),
    resolve_zoom_values=resolve_zoom_values,
)
