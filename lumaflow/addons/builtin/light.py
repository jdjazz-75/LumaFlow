# LumaFlow v1.0 (2026-08-07)
# Addon Lumiere : moteur de gradation parametrique (~31 champs) avec presets Low Key/
# High Key/Dramatique/Soft, split sujet/fond via masque polygonal, halo et douceur protegee.
"""Light addon (Lumière) v2 -- elaborate one-click presets (Low Key, High Key, Dramatique, Soft)
on top of F-043's Neutre/Balance, all sharing a single parametric grading engine, plus a
subject/background split (feature 047).

No Qt, no pipeline engine, no persistence module import (same convention as every module under
lumaflow/addons/).

Architecture notes (load-bearing decisions only):

- Every primitive below (`_rgb_to_hsl`/`_hsl_to_rgb`/`_box_blur`/`_apply_black_clip`/
  `_apply_global_saturation`/`_apply_hsl_saturation_by_hue`/`_apply_hsl_luminance_by_hue`/
  `_apply_temperature_tint`/`_apply_grain`/`_apply_vignette`) is copied, not imported, from
  `film.py`/`color_splash.py`/`monochrome_tone.py` -- addon modules are loaded via
  `importlib.util.spec_from_file_location` without being registered in `sys.modules`, so
  cross-addon imports break; every addon in this codebase duplicates instead (Decision 1).
- The tone curve is a 4-zone parametric model (blacks/shadows/highlights/whites + a movable
  contrast pivot), generalizing F-043's own 2-zone shadows/highlights model rather than a literal
  point-curve interpolation -- FR-003 requires every value stay individually adjustable, which a
  single fixed curve cannot satisfy (Decision 2).
- `black_point` (crush, F-042's `_apply_black_clip` verbatim) and `black_floor` (lift, new: `out =
  f + (1-f)*x`) are two independent controls, not a signed pair (Decision 3).
- `dehaze` is its own small standalone stage (a minor clarity nudge + a small black-point-relative
  crush/lift + a small saturation nudge), never folded into `clarity`/`contrast`/`black_point`
  (Decision 4) -- deliberately NOT a physically accurate dark-channel-prior dehaze.
- `exposure`/`shadows`/`highlights` (F-043's 3 original sliders, previously `[-2,2]`/`[-1,1]`) are
  unified onto the same `-100..100` scale as every new field (Decision 11, user decision) -- an
  already-saved v1 recipe stays in-range (does not fail to load) but silently becomes a near-no-op
  on those 3 fields.
- Presets are selected via a `look` key + an internal calibration table (mirrors `film.py`'s own
  pattern), not a `preset_parameters` dict holding the full ~31-field calibration verbatim
  (Decision 10) -- a saved recipe holds only `{"look": "low_key", "intensity": 1.0}` plus whatever
  the user actually overrode, and automatically picks up any future recalibration.
- Every one of the ~31 base-grade fields resolves independently via `_read_float` -- a missing,
  non-numeric, or out-of-range value on any ONE key falls back to that key's own currently-resolved
  (look-calibrated) value alone, with no effect on any other key (per-key fallback, matching F-043's
  established convention, applied at ~10x the field count).
"""

from __future__ import annotations

from typing import Any, NamedTuple

import numpy
from PIL import Image as PILImage, ImageDraw

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission
from lumaflow.addons.parameters import NumericSliderConstraints, ParameterDescription

# ---------------------------------------------------------------------------
# Primitives copied from film.py / color_splash.py / monochrome_tone.py (Decision 1). Kept
# byte-for-byte identical to their source where possible, so a given numeric value reads on the
# same perceptual scale across addons.
# ---------------------------------------------------------------------------


def _luma(image: numpy.ndarray) -> numpy.ndarray:
    return image[..., 0] * 0.299 + image[..., 1] * 0.587 + image[..., 2] * 0.114


def _clip(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _rgb_to_hsl(rgb: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    """rgb: float32 (H, W, 3) in 0..255. Returns (h in 0..360, s in 0..1, l in 0..1)."""
    normalized = rgb / 255.0
    r, g, b = normalized[..., 0], normalized[..., 1], normalized[..., 2]
    # PERF-ZOOM-RENDER-PLAN.md étape 3: numpy.max(normalized, axis=-1) was tried here (fewer
    # allocations, bit-identical) but measured 3-5x SLOWER than the nested maximum/minimum below --
    # reducing along a small, strided last axis (size 3) has worse per-element overhead than two
    # elementwise passes over contiguous-enough (H, W) views, on this numpy/machine. Reverted after
    # measurement; kept as the cautionary example this plan's own "mesurer, ne pas supposer"
    # discipline calls for -- do not reintroduce without re-benchmarking.
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


def _box_blur(channel: numpy.ndarray, radius: int) -> numpy.ndarray:
    """Deterministic separable box blur via prefix sums -- no scipy dependency. radius <= 0 is a
    no-op."""
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


def _apply_black_clip(rgb: numpy.ndarray, amount: float) -> numpy.ndarray:
    """Raises the black point -- crushes near-black values toward pure black more aggressively as
    `amount` increases. No-op at 0."""
    if amount <= 0.0:
        return rgb
    normalized = numpy.clip(rgb / 255.0, 0.0, 1.0)
    remapped = numpy.clip((normalized - amount) / (1.0 - amount), 0.0, 1.0)
    return remapped * 255.0


def _apply_black_floor(rgb: numpy.ndarray, amount: float) -> numpy.ndarray:
    """Lifts pure black to `amount` -- the faded/matte-black look (Decision 3, the opposite of
    `_apply_black_clip`: raises the floor rather than crushing toward it). No-op at 0."""
    if amount <= 0.0:
        return rgb
    normalized = numpy.clip(rgb / 255.0, 0.0, 1.0)
    lifted = amount + (1.0 - amount) * normalized
    return lifted * 255.0


def _apply_global_saturation(saturation: numpy.ndarray, factor: float) -> numpy.ndarray:
    return numpy.clip(saturation * factor, 0.0, 1.0)


_HUE_CENTERS = {
    "red": 0.0,
    "orange": 30.0,
    "yellow": 60.0,
    "green": 120.0,
    "cyan": 180.0,
    "blue": 240.0,
    "magenta": 300.0,
}


def _hue_window_weight(hue: numpy.ndarray, center: float, feather: float) -> numpy.ndarray:
    """Cosine-weighted window: 1.0 at `center`, falling smoothly to 0.0 at `feather` degrees away,
    0.0 beyond -- color_splash.py's configurable-feather version (Decision 1), used with a fixed
    40deg feather everywhere below to match film.py's own per-hue windows exactly."""
    angular_distance = numpy.abs(((hue - center + 180.0) % 360.0) - 180.0)
    return numpy.where(
        angular_distance <= feather,
        0.5 * (1.0 + numpy.cos(angular_distance / feather * numpy.pi)),
        0.0,
    )


def _apply_hsl_saturation_by_hue(
    hue: numpy.ndarray, saturation: numpy.ndarray, deltas: dict[str, float]
) -> numpy.ndarray:
    """For each named hue in `deltas` (-50..50 %), scales saturation within a cosine-weighted
    40deg-half-width window centered on that hue's standard angle."""
    result = saturation
    for name, delta_pct in deltas.items():
        center = _HUE_CENTERS.get(name)
        if center is None:
            continue
        weight = _hue_window_weight(hue, center, 40.0)
        result = numpy.clip(result * (1.0 + weight * (delta_pct / 100.0)), 0.0, 1.0)
    return result


def _apply_hsl_luminance_by_hue(
    hue: numpy.ndarray, luminance: numpy.ndarray, deltas: dict[str, float]
) -> numpy.ndarray:
    """For each named hue in `deltas` (-30..30), shifts luminance within the same cosine-weighted
    window used by saturation -- a subtle per-hue lightness nudge, not a second tone curve."""
    result = luminance
    for name, delta in deltas.items():
        center = _HUE_CENTERS.get(name)
        if center is None:
            continue
        weight = _hue_window_weight(hue, center, 40.0)
        result = numpy.clip(result + weight * (delta / 30.0) * 0.15, 0.0, 1.0)
    return result


def _apply_temperature_tint(rgb: numpy.ndarray, temperature: float, tint: float) -> numpy.ndarray:
    """Simplified per-channel white-balance approximation -- NOT a physically accurate
    Planckian-locus computation. Negative temperature cools the image; negative tint shifts toward
    green."""
    result = rgb.copy()
    result[..., 0] *= 1.0 + (temperature / 1000.0) * 0.10
    result[..., 2] *= 1.0 - (temperature / 1000.0) * 0.10
    result[..., 1] *= 1.0 - (tint / 20.0) * 0.05
    return result


def _zone_weights_2(luminance: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Shadow/highlight weights from 0..1 luminance -- 1 at the extreme, 0 at or past mid-gray
    (0.5), linear falloff. Used by split-toning only (the tone CURVE itself uses the 4-zone model
    below, Decision 2)."""
    shadow_weight = numpy.clip((0.5 - luminance) / 0.5, 0.0, 1.0)
    highlight_weight = numpy.clip((luminance - 0.5) / 0.5, 0.0, 1.0)
    return shadow_weight, highlight_weight


def _apply_split_tone(
    rgb: numpy.ndarray,
    luminance: numpy.ndarray,
    shadow_hue: float,
    shadow_strength: float,
    highlight_hue: float,
    highlight_strength: float,
) -> numpy.ndarray:
    """Blends a target hue's color into the shadow/highlight zones -- film.py's `_apply_split_tone`
    generalized to take scalar hue/strength arguments directly rather than a whole grade object
    (Light's field names, `split_shadow_*`/`split_highlight_*`, differ from film.py's
    `split_tone_shadow_*`/`split_tone_highlight_*`)."""
    result = rgb
    shadow_weight, highlight_weight = _zone_weights_2(luminance)
    if shadow_strength > 0.0:
        tiny_hue = numpy.array([[shadow_hue]], dtype=luminance.dtype)
        target = _hsl_to_rgb(tiny_hue, numpy.ones_like(tiny_hue), numpy.full_like(tiny_hue, 0.5))[0, 0]
        blend = (shadow_weight * (shadow_strength / 100.0))[..., numpy.newaxis]
        result = result * (1.0 - blend) + target * blend
    if highlight_strength > 0.0:
        tiny_hue = numpy.array([[highlight_hue]], dtype=luminance.dtype)
        target = _hsl_to_rgb(tiny_hue, numpy.ones_like(tiny_hue), numpy.full_like(tiny_hue, 0.5))[0, 0]
        blend = (highlight_weight * (highlight_strength / 100.0))[..., numpy.newaxis]
        result = result * (1.0 - blend) + target * blend
    return result


_GRAIN_SEED = 20260727  # fixed constant -- never derived from clock/content, so the same image
                         # shape always gets the same grain (determinism, Principle IV).


def _apply_grain(rgb: numpy.ndarray, std: float, size: float) -> numpy.ndarray:
    """Deterministic film grain -- a fixed-seed RNG depending only on the image's own shape."""
    if std <= 0.0:
        return rgb
    height, width = rgb.shape[0], rgb.shape[1]
    rng = numpy.random.default_rng(_GRAIN_SEED)
    noise = rng.normal(0.0, std * 255.0, size=(height, width)).astype(numpy.float32)
    blur_radius = max(0, int(round(size / 2.0)))
    if blur_radius > 0:
        noise = _box_blur(noise, blur_radius)
    return rgb + noise[..., numpy.newaxis]


def _apply_vignette(rgb: numpy.ndarray, amount: float) -> numpy.ndarray:
    """Radial edge darkening/lightening (monochrome_tone.py's primitive, Decision 1). `amount`
    -100..100, 0 = no-op: negative darkens the corners, positive lightens them."""
    if amount == 0.0:
        return rgb
    height, width = rgb.shape[0], rgb.shape[1]
    y = numpy.linspace(-1.0, 1.0, height, dtype=numpy.float32)[:, numpy.newaxis]
    x = numpy.linspace(-1.0, 1.0, width, dtype=numpy.float32)[numpy.newaxis, :]
    radius = numpy.clip(numpy.sqrt(x ** 2 + y ** 2) / numpy.sqrt(2.0), 0.0, 1.0)
    factor = 1.0 + (amount / 100.0) * radius
    return rgb * factor[..., numpy.newaxis]


# ---------------------------------------------------------------------------
# New engine primitives for this feature (Decisions 2-4).
# ---------------------------------------------------------------------------

_ZONE_CENTERS = {"blacks": 0.00, "shadows": 0.28, "highlights": 0.72, "whites": 1.00}
_ZONE_HALF_WIDTHS = {"blacks": 0.30, "shadows": 0.28, "highlights": 0.28, "whites": 0.30}


def _tone_window(luminance: numpy.ndarray, center: float, half_width: float) -> numpy.ndarray:
    """Cosine window in the LUMINANCE domain (same idiom as `_hue_window_weight`, applied to
    luminance instead of hue) -- the 4-zone tone model's building block (Decision 2)."""
    distance = numpy.abs(luminance - center)
    return numpy.where(distance <= half_width, 0.5 * (1.0 + numpy.cos(distance / half_width * numpy.pi)), 0.0)


def _apply_tone_curve_4(
    luminance: numpy.ndarray,
    contrast: float,
    pivot: float,
    blacks: float,
    shadows: float,
    highlights: float,
    whites: float,
) -> numpy.ndarray:
    """4-zone parametric tone curve + contrast around a movable pivot (Decision 2). Coefficients
    (0.25 per zone, 0.3 for contrast) match film.py's own `_apply_tone_curve` exactly, so a given
    numeric value reads on the same perceptual scale in both addons."""
    result = luminance
    result = result + _tone_window(luminance, _ZONE_CENTERS["blacks"], _ZONE_HALF_WIDTHS["blacks"]) * (blacks / 100.0) * 0.25
    result = result + _tone_window(luminance, _ZONE_CENTERS["shadows"], _ZONE_HALF_WIDTHS["shadows"]) * (shadows / 100.0) * 0.25
    result = result + _tone_window(luminance, _ZONE_CENTERS["highlights"], _ZONE_HALF_WIDTHS["highlights"]) * (highlights / 100.0) * 0.25
    result = result + _tone_window(luminance, _ZONE_CENTERS["whites"], _ZONE_HALF_WIDTHS["whites"]) * (whites / 100.0) * 0.25
    result = result + (result - pivot) * (contrast / 100.0) * 0.3
    return numpy.clip(result, 0.0, 1.0)


def _apply_dehaze(rgb: numpy.ndarray, amount: float) -> numpy.ndarray:
    """A small, documented proxy (Decision 4): a minor clarity-like local-contrast nudge, a small
    black-point-relative crush (positive amount) or lift (negative amount), and a small saturation
    nudge -- scaled by `amount` (-100..100). Never writes back into `clarity`/`contrast`/
    `black_point` -- those sliders always read their own field, independent of `dehaze`."""
    if amount == 0.0:
        return rgb
    t = amount / 100.0
    luma = _luma(rgb)
    height, width = luma.shape
    radius = max(1, int(round(min(height, width) * 0.02)))
    blurred = _box_blur(luma, radius)
    detail = (luma - blurred) * t * 0.15
    result = rgb + detail[..., numpy.newaxis]
    if t > 0.0:
        crush = _clip(t * 0.03, 0.0, 0.10)
        normalized = numpy.clip(result / 255.0, 0.0, 1.0)
        result = numpy.clip((normalized - crush) / (1.0 - crush), 0.0, 1.0) * 255.0
    else:
        lift = _clip(-t * 0.03, 0.0, 0.10)
        normalized = numpy.clip(result / 255.0, 0.0, 1.0)
        result = (lift + (1.0 - lift) * normalized) * 255.0
    hue, saturation, luminance = _rgb_to_hsl(result)
    saturation = numpy.clip(saturation * (1.0 + t * 0.1), 0.0, 1.0)
    return _hsl_to_rgb(hue, saturation, luminance)


def _apply_detail_bands(rgb: numpy.ndarray, clarity: float, texture: float, sharpness: float) -> numpy.ndarray:
    """Three unsharp-mask bands: clarity (wide radius, midtone/local contrast, ~2% of the minimum
    dimension -- film.py's own clarity radius), texture (mid radius, ~0.5%, new to this addon), and
    sharpness (1px, fine detail -- film.py's own sharpness radius). Starts from an explicit
    `.copy()` (T010's guard): film.py's own `_apply_clarity_sharpness` writes per-channel IN PLACE
    into whatever array it was handed, which is only safe there because its caller always passes an
    already-fresh array -- copying here removes that hidden precondition entirely."""
    result = rgb.copy()
    height, width = result.shape[0], result.shape[1]
    min_dim = min(height, width)
    if clarity != 0.0:
        luma = _luma(result)
        radius = max(1, int(round(min_dim * 0.02)))
        blurred = _box_blur(luma, radius)
        detail = (luma - blurred) * (clarity / 100.0) * 0.8
        result = result + detail[..., numpy.newaxis]
    if texture != 0.0:
        luma = _luma(result)
        radius = max(1, int(round(min_dim * 0.005)))
        blurred = _box_blur(luma, radius)
        detail = (luma - blurred) * (texture / 100.0) * 0.6
        result = result + detail[..., numpy.newaxis]
    if sharpness != 0.0:
        radius = 1
        for channel_index in range(3):
            channel = result[..., channel_index]
            blurred = _box_blur(channel, radius)
            result[..., channel_index] = channel + (channel - blurred) * (sharpness / 100.0) * 0.8
    return result


# ---------------------------------------------------------------------------
# Halo (bloom) and protected soft-detail (User Story 5, Soft's own finishing effects). Both are
# global-tail operators (Decision 9) -- wired into light_adjustments after the region composite.
# ---------------------------------------------------------------------------


def _relative_gate(values: numpy.ndarray, low_percentile: float, high_percentile: float) -> numpy.ndarray:
    """Normalizes `values` to 0..1 between its OWN low/high percentile, rather than fixed absolute
    bounds -- film.py's own primitive (Decision 1), copied verbatim: percentiles of the array
    actually being processed keep the gate meaningful regardless of how much a preset's own
    calibration has already compressed the range."""
    low = float(numpy.percentile(values, low_percentile))
    high = float(numpy.percentile(values, high_percentile))
    if high - low < 1e-6:
        return numpy.zeros_like(values)
    return numpy.clip((values - low) / (high - low), 0.0, 1.0)


def _apply_bloom(rgb: numpy.ndarray, threshold: float, amount: float, radius_pct: float, warmth: float) -> numpy.ndarray:
    """Soft-knee luminance-threshold weight (squared ramp -- no hard edge) selects the bright glow
    source; a wide per-channel box blur spreads it; `_apply_temperature_tint` warms/cools the glow
    itself; a screen blend composites it back, scaled by `amount`. No-op at `amount <= 0`."""
    if amount <= 0.0:
        return rgb
    luma = _luma(rgb) / 255.0
    knee_width = 0.2
    weight = numpy.clip((luma - threshold) / knee_width, 0.0, 1.0) ** 2
    glow_source = rgb * weight[..., numpy.newaxis]
    width = rgb.shape[1]
    radius = max(1, int(round(radius_pct / 100.0 * width)))
    glow = numpy.stack([_box_blur(glow_source[..., c], radius) for c in range(3)], axis=-1)
    glow = _apply_temperature_tint(glow, warmth, 0.0)
    glow = numpy.clip(glow, 0.0, 255.0)
    screen = 255.0 - (255.0 - rgb) * (255.0 - glow) / 255.0
    t = _clip(amount / 100.0, 0.0, 1.0)
    return rgb * (1.0 - t) + screen * t


def _edge_protection_mask(rgb: numpy.ndarray, radius_px: float) -> numpy.ndarray:
    """Gradient magnitude on luma (numpy.gradient), normalized through `_relative_gate` (so it
    adapts to each image's own contrast rather than a fixed absolute gradient threshold), then
    smoothed by `_box_blur` -- 1.0 where a strong edge sits, ~0.0 on flat regions."""
    luma = _luma(rgb)
    gy, gx = numpy.gradient(luma)
    magnitude = numpy.sqrt(gx ** 2 + gy ** 2)
    gated = _relative_gate(magnitude, 50.0, 95.0)
    radius = max(0, int(round(radius_px)))
    if radius > 0:
        gated = _box_blur(gated, radius)
    return gated


def _apply_soft_detail(rgb: numpy.ndarray, amount: float, radius_px: float, edge_protection: float) -> numpy.ndarray:
    """Per-channel box blur blended in proportion to `amount * (1 - edge_protection_mask *
    edge_protection)` -- flat regions blend fully toward the blur, strong-edge regions are
    increasingly protected as `edge_protection` rises, so sharp edges (eyes, object borders) stay
    identifiable while flat/smooth areas soften (FR-013, SC-009). No-op at `amount <= 0`."""
    if amount <= 0.0:
        return rgb
    edge_mask = _edge_protection_mask(rgb, radius_px)
    protect = _clip(edge_protection / 100.0, 0.0, 1.0)
    blend = _clip(amount / 100.0, 0.0, 1.0) * (1.0 - edge_mask * protect)
    radius = max(1, int(round(radius_px)))
    blurred = numpy.stack([_box_blur(rgb[..., c], radius) for c in range(3)], axis=-1)
    return rgb * (1.0 - blend[..., numpy.newaxis]) + blurred * blend[..., numpy.newaxis]


# ---------------------------------------------------------------------------
# _LightGrade -- the base grade (data-model.md), plain typing.NamedTuple for the same reason
# film.py's _GradeParams is one (addon modules are loaded without sys.modules registration;
# @dataclass's _process_class looks itself up there and raises on this Python version).
# ---------------------------------------------------------------------------


class _LightGrade(NamedTuple):
    # Tone (-100..100 unless noted, Decision 11)
    exposure: float = 0.0
    contrast: float = 0.0
    contrast_pivot: float = 0.5          # 0.2..0.8
    blacks: float = 0.0
    shadows: float = 0.0
    highlights: float = 0.0
    whites: float = 0.0
    black_point: float = 0.0             # 0..0.10 (crush)
    black_floor: float = 0.0             # 0..0.10 (lift)
    # Colour
    saturation: float = 1.0              # x0..x2
    temperature: float = 0.0             # -1000..1000 K (approximation)
    tint: float = 0.0                    # -20..20
    split_shadow_hue: float = 220.0      # 0..360 -- irrelevant while strength is 0
    split_shadow_strength: float = 0.0   # 0..20 (%)
    split_highlight_hue: float = 45.0    # 0..360
    split_highlight_strength: float = 0.0
    hsl_saturation_scale: float = 1.0    # 0..2 -- scales `hsl_saturation` below
    hsl_luminance_scale: float = 1.0     # 0..2 -- scales `hsl_luminance` below
    # Texture (-100..100)
    clarity: float = 0.0
    texture: float = 0.0
    sharpness: float = 0.0
    dehaze: float = 0.0
    # Halo (bloom) -- User Story 5, wired into light_adjustments's global tail.
    bloom_threshold: float = 0.8         # 0..1
    bloom_amount: float = 0.0            # 0..50 (%)
    bloom_radius: float = 2.0            # 0..5 (% of width)
    bloom_warmth: float = 0.0            # -500..500 K
    # Douceur (protected soft-detail) -- also User Story 5, wired alongside Halo.
    soft_detail_amount: float = 0.0      # 0..50 (%)
    soft_detail_radius: float = 3.0      # 0..8 px
    edge_protection: float = 70.0        # 0..100 (%)
    # Finition
    vignette: float = 0.0                # -100..100, signed: - darkens corners / + lightens
    grain: float = 0.0                   # 0..0.05
    # Internal-only, never a slider (same convention as film.py/monochrome_tone.py) -- per-hue
    # dicts scaled by hsl_saturation_scale/hsl_luminance_scale at apply time, and the grain blur
    # radius (px).
    hsl_saturation: dict[str, float] = {}
    hsl_luminance: dict[str, float] = {}
    grain_size: float = 1.0


# The 31 base-grade fields exposed as Zoom sliders, with their (minimum, maximum) bounds -- the
# single source of truth `_apply_grade_overrides`/`resolve_zoom_values`/`ADDON_DESCRIPTION` all
# derive from, so the three can never drift out of sync (T016).
_FIELD_BOUNDS: dict[str, tuple[float, float]] = {
    "exposure": (-100.0, 100.0),
    "contrast": (-100.0, 100.0),
    "contrast_pivot": (0.2, 0.8),
    "blacks": (-100.0, 100.0),
    "shadows": (-100.0, 100.0),
    "highlights": (-100.0, 100.0),
    "whites": (-100.0, 100.0),
    "black_point": (0.0, 0.10),
    "black_floor": (0.0, 0.10),
    "saturation": (0.0, 2.0),
    "temperature": (-1000.0, 1000.0),
    "tint": (-20.0, 20.0),
    "split_shadow_hue": (0.0, 360.0),
    "split_shadow_strength": (0.0, 20.0),
    "split_highlight_hue": (0.0, 360.0),
    "split_highlight_strength": (0.0, 20.0),
    "hsl_saturation_scale": (0.0, 2.0),
    "hsl_luminance_scale": (0.0, 2.0),
    "clarity": (-100.0, 100.0),
    "texture": (-100.0, 100.0),
    "sharpness": (-100.0, 100.0),
    "dehaze": (-100.0, 100.0),
    "bloom_threshold": (0.0, 1.0),
    "bloom_amount": (0.0, 50.0),
    "bloom_radius": (0.0, 5.0),
    "bloom_warmth": (-500.0, 500.0),
    "soft_detail_amount": (0.0, 50.0),
    "soft_detail_radius": (0.0, 8.0),
    "edge_protection": (0.0, 100.0),
    "vignette": (-100.0, 100.0),
    "grain": (0.0, 0.05),
}

# Cyclic fields (hue, 0..360) wrap via modulo rather than rejecting an out-of-range value outright
# -- there is no meaningful "out of range" for an angle.
_WRAP_FIELDS = frozenset({"split_shadow_hue", "split_highlight_hue"})


def _read_float(
    params: dict[str, Any], key: str, default: float, *, minimum: float, maximum: float, wrap: bool = False
) -> float:
    """Reads one field defensively -- a missing, non-numeric, or (for non-cyclic fields)
    out-of-range value falls back to `default` alone (the light-addon-contract.md completeness
    guarantee: per-key fallback, matching F-043's convention, applied at ~10x the field count).
    Cyclic fields (`wrap=True`) wrap via modulo instead of rejecting."""
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    if wrap:
        return value % 360.0
    if value < minimum or value > maximum:
        return default
    return value


def _apply_grade_overrides(base: _LightGrade, params: dict[str, Any]) -> _LightGrade:
    """Per-field override-or-default (T011): each of the 31 base-grade fields present in `params`
    replaces `base`'s own value (defensively resolved via `_read_float`, falling back to `base`'s
    OWN currently-resolved value -- i.e. a malformed override is simply not applied, the look's
    calibration passes through untouched for that field alone). Returns `base` itself (same object)
    when nothing overrides it, preserving the bit-identity fast path in `light_adjustments`."""
    overrides: dict[str, float] = {}
    for field_name, (minimum, maximum) in _FIELD_BOUNDS.items():
        if field_name in params:
            overrides[field_name] = _read_float(
                params, field_name, getattr(base, field_name),
                minimum=minimum, maximum=maximum, wrap=field_name in _WRAP_FIELDS,
            )
    if not overrides:
        return base
    return base._replace(**overrides)


def _apply_region_grade(rgb: numpy.ndarray, grade: _LightGrade) -> numpy.ndarray:
    """The full per-region pipeline (data-model.md's Processing pipeline), in order: exposure ->
    4-zone tone curve -> global + per-hue HSL saturation/luminance -> temperature/tint -> split
    tone -> dehaze -> detail bands -> black floor -> black clip. `rgb` must already be float32;
    never mutates its argument (every stage either no-ops or returns a new array)."""
    result = rgb
    if grade.exposure != 0.0:
        ev = grade.exposure / 100.0 * 2.0
        result = numpy.clip(result * (2.0 ** ev), 0.0, 255.0)

    hue, saturation, luminance = _rgb_to_hsl(result)
    luminance = _apply_tone_curve_4(
        luminance, grade.contrast, grade.contrast_pivot, grade.blacks, grade.shadows, grade.highlights, grade.whites
    )
    saturation = _apply_global_saturation(saturation, grade.saturation)
    if grade.hsl_saturation:
        scaled_saturation = {
            name: _clip(value * grade.hsl_saturation_scale, -50.0, 50.0) for name, value in grade.hsl_saturation.items()
        }
        saturation = _apply_hsl_saturation_by_hue(hue, saturation, scaled_saturation)
    if grade.hsl_luminance:
        scaled_luminance = {
            name: _clip(value * grade.hsl_luminance_scale, -30.0, 30.0) for name, value in grade.hsl_luminance.items()
        }
        luminance = _apply_hsl_luminance_by_hue(hue, luminance, scaled_luminance)

    result = _hsl_to_rgb(hue, saturation, luminance)
    result = _apply_temperature_tint(result, grade.temperature, grade.tint)
    result = _apply_split_tone(
        result, luminance, grade.split_shadow_hue, grade.split_shadow_strength,
        grade.split_highlight_hue, grade.split_highlight_strength,
    )
    result = _apply_dehaze(result, grade.dehaze)
    result = _apply_detail_bands(result, grade.clarity, grade.texture, grade.sharpness)
    result = _apply_black_floor(result, grade.black_floor)
    result = _apply_black_clip(result, grade.black_point)
    return result


# ---------------------------------------------------------------------------
# Subject/background region deltas (User Story 3, Decisions 7-9). 19 of the 31 base-grade fields
# get a subject_<field>/background_<field> delta pair -- 16 additive (default 0.0), 3
# multiplicative (default 1.0). Split-tone hue and every Halo/Douceur/Finition field have NO
# per-region delta -- they stay global (Decisions 8/9).
# ---------------------------------------------------------------------------

_ADDITIVE_REGION_FIELDS = (
    "exposure", "contrast", "blacks", "shadows", "highlights", "whites",
    "black_point", "black_floor", "temperature", "tint",
    "split_shadow_strength", "split_highlight_strength",
    "clarity", "texture", "sharpness", "dehaze",
)
_MULTIPLICATIVE_REGION_FIELDS = ("saturation", "hsl_saturation_scale", "hsl_luminance_scale")

# Composition rule per field, NOT encoded in the field's name -- lets the frontend strip the
# subject_/background_ prefix and group sliders with zero addon-specific special-casing (Decision
# 7).
_REGION_COMPOSITION: dict[str, str] = {
    **{name: "additive" for name in _ADDITIVE_REGION_FIELDS},
    **{name: "multiplicative" for name in _MULTIPLICATIVE_REGION_FIELDS},
}


class _RegionDeltas(NamedTuple):
    exposure: float = 0.0
    contrast: float = 0.0
    blacks: float = 0.0
    shadows: float = 0.0
    highlights: float = 0.0
    whites: float = 0.0
    black_point: float = 0.0
    black_floor: float = 0.0
    temperature: float = 0.0
    tint: float = 0.0
    split_shadow_strength: float = 0.0
    split_highlight_strength: float = 0.0
    clarity: float = 0.0
    texture: float = 0.0
    sharpness: float = 0.0
    dehaze: float = 0.0
    saturation: float = 1.0
    hsl_saturation_scale: float = 1.0
    hsl_luminance_scale: float = 1.0


def _read_region_deltas(params: dict[str, Any], prefix: str) -> _RegionDeltas:
    """Reads the 19 `{prefix}_<field>` keys (prefix is "subject"/"background") defensively -- each
    falls back to its OWN neutral default (0.0 additive / 1.0 multiplicative) independently,
    bounded by the same range as the underlying base-grade field (the raw delta's own declared
    range; `_compose_region` clips the RESULT to the base field's bounds again as a second,
    independent safety net)."""
    overrides: dict[str, float] = {}
    for field_name, kind in _REGION_COMPOSITION.items():
        key = f"{prefix}_{field_name}"
        if key in params:
            default = 0.0 if kind == "additive" else 1.0
            minimum, maximum = _FIELD_BOUNDS[field_name]
            overrides[field_name] = _read_float(params, key, default, minimum=minimum, maximum=maximum)
    if not overrides:
        return _RegionDeltas()
    return _RegionDeltas()._replace(**overrides)


def _compose_region(base: _LightGrade, deltas: _RegionDeltas) -> _LightGrade:
    """Applies each of the 19 region-eligible fields' delta per its composition rule, clipped to
    that field's own bounds -- every other _LightGrade field (contrast_pivot, split_*_hue, Halo/
    Douceur/Finition, the internal hsl_saturation/hsl_luminance dicts, grain_size) passes through
    from `base` unchanged. All-neutral `deltas` produces field values exactly equal to `base`'s own
    (x+0.0 and x*1.0 are exact in IEEE754, and `base` is already within its own bounds), so
    `_compose_region(base, _RegionDeltas()) == base` -- the single-pass equivalence check in
    `light_adjustments` relies on this."""
    overrides: dict[str, float] = {}
    for field_name, kind in _REGION_COMPOSITION.items():
        delta = getattr(deltas, field_name)
        base_value = getattr(base, field_name)
        minimum, maximum = _FIELD_BOUNDS[field_name]
        if kind == "additive":
            overrides[field_name] = _clip(base_value + delta, minimum, maximum)
        else:
            overrides[field_name] = _clip(base_value * delta, minimum, maximum)
    return base._replace(**overrides)


# ---------------------------------------------------------------------------
# Subject/background boundary (User Stories 3/4, Decision 5): flattened to fixed-capacity scalar
# keys rather than a new ParameterDescription.kind -- the Zoom wire is float-scalar-only end to
# end. `mask_point_count < 3` resolves to no mask (single-region path).
# ---------------------------------------------------------------------------

_MAX_MASK_VERTICES = 32
# The default centered rectangle (middle 50% of the image) a fresh Zoom session seeds
# SubjectMaskStage with when no mask_point_* key is in params yet.
_DEFAULT_MASK_POINTS: tuple[tuple[float, float], ...] = ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75))


class _MaskSpec(NamedTuple):
    points: tuple[tuple[float, float], ...]
    feather_pct: float
    invert: bool


def _read_bool(params: dict[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, None)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value) >= 0.5


def _read_mask(params: dict[str, Any]) -> _MaskSpec | None:
    """Resolves the polygon boundary from its flat scalar keys -- `count < 3` (missing, malformed,
    or explicitly below 3) returns `None` (no region split -- the degenerate-polygon case: a
    near-zero-vertex "shape" is simply treated as no boundary at all, never an error)."""
    count_float = _read_float(params, "mask_point_count", 0.0, minimum=0.0, maximum=_MAX_MASK_VERTICES)
    count = int(count_float)
    if count < 3:
        return None
    points = []
    for i in range(count):
        default_x, default_y = _DEFAULT_MASK_POINTS[i] if i < len(_DEFAULT_MASK_POINTS) else (0.5, 0.5)
        x = _read_float(params, f"mask_point_{i:02d}_x", default_x, minimum=0.0, maximum=1.0)
        y = _read_float(params, f"mask_point_{i:02d}_y", default_y, minimum=0.0, maximum=1.0)
        points.append((x, y))
    feather_pct = _read_float(params, "mask_feather", 2.0, minimum=0.0, maximum=20.0)
    invert = _read_bool(params, "mask_invert", False)
    return _MaskSpec(points=tuple(points), feather_pct=feather_pct, invert=invert)


def _polygon_mask(
    shape: tuple[int, ...], points: tuple[tuple[float, float], ...], feather_pct: float, invert: bool
) -> numpy.ndarray:
    """Rasterizes the polygon via PIL.ImageDraw (handles arbitrary, including self-intersecting,
    polygons via scanline fill with no crash risk -- the degenerate-polygon edge case),
    then feathers the hard edge via two `_box_blur` passes at half the feather radius each
    (triangular ~= gaussian falloff, Decision 6). Recomputed from the actual array `shape` on every
    call -- never cached across resolutions, so the mask is geometrically identical for the 480px
    preview and the full-resolution render."""
    height, width = shape[0], shape[1]
    canvas = PILImage.new("L", (width, height), 0)
    pixel_points = [(x * width, y * height) for x, y in points]
    ImageDraw.Draw(canvas).polygon(pixel_points, fill=255)
    mask = numpy.asarray(canvas, dtype=numpy.float32) / 255.0
    radius = max(0, int(round(feather_pct / 100.0 * min(height, width))))
    if radius > 0:
        half = max(1, radius // 2)
        mask = _box_blur(_box_blur(mask, half), half)
    return 1.0 - mask if invert else mask


# Padding (beyond the feather ramp itself) added to the mask's bounding box before cropping the
# subject-side render to it (T047 perf remediation, below) -- covers the widest per-region blur
# radius in play (clarity, ~2% of the minimum dimension) so that stage's own box-blur never reads
# past the crop edge and produces a visible seam.
_BOUNDING_BOX_SAFETY_MARGIN = 0.03


def _mask_bounding_box(
    points: tuple[tuple[float, float], ...], feather_pct: float, shape: tuple[int, ...]
) -> tuple[int, int, int, int]:
    """The polygon's axis-aligned bounding box in PIXEL coordinates for `shape`, padded by the
    feather radius plus a safety margin -- returns (x0, x1, y0, y1), half-open (x1/y1 exclusive).
    Outside this box the composite is, by construction, indistinguishable from the pure background
    render (alpha ~= 0 once the padding covers the full feather ramp), so `light_adjustments` only
    needs to compute the (expensive) subject-side grade WITHIN this box, not the whole image."""
    height, width = shape[0], shape[1]
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_y = max(p[1] for p in points)
    pad_fraction = feather_pct / 100.0 + _BOUNDING_BOX_SAFETY_MARGIN
    pad_x = pad_fraction * min(height, width) / width
    pad_y = pad_fraction * min(height, width) / height
    x0 = max(0, int((min_x - pad_x) * width))
    x1 = min(width, int((max_x + pad_x) * width) + 1)
    y0 = max(0, int((min_y - pad_y) * height))
    y1 = min(height, int((max_y + pad_y) * height) + 1)
    return x0, x1, y0, y1


# Region-delta and mask ParameterDescriptions are generated rather than written out by hand (105
# entries total) -- same precedent as color_splash.py's `_range_parameter_descriptions(i)` for its
# own variable-count hue ranges, spread into ADDON_DESCRIPTION.parameter_descriptions below.
_REGION_LABELS: dict[str, str] = {
    "exposure": "Exposition", "contrast": "Contraste", "blacks": "Noirs", "shadows": "Ombres",
    "highlights": "Hautes lumières", "whites": "Blancs", "black_point": "Point noir",
    "black_floor": "Plancher de noir", "temperature": "Température", "tint": "Teinte",
    "split_shadow_strength": "Virage ombres (force)", "split_highlight_strength": "Virage hautes lumières (force)",
    "clarity": "Clarté", "texture": "Texture", "sharpness": "Netteté", "dehaze": "Dehaze",
    "saturation": "Saturation", "hsl_saturation_scale": "Saturation HSL", "hsl_luminance_scale": "Luminance HSL",
}


def _region_delta_parameter_descriptions(prefix: str, region_label: str) -> tuple[ParameterDescription, ...]:
    descriptions = []
    for field_name, kind in _REGION_COMPOSITION.items():
        minimum, maximum = _FIELD_BOUNDS[field_name]
        default = 0.0 if kind == "additive" else 1.0
        step = (maximum - minimum) / 200.0
        descriptions.append(ParameterDescription(
            identifier=f"{prefix}_{field_name}", label=f"{_REGION_LABELS[field_name]} ({region_label})",
            kind="numeric_slider", default=default, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=minimum, maximum=maximum, step=step),
        ))
    return tuple(descriptions)


def _mask_parameter_descriptions() -> tuple[ParameterDescription, ...]:
    descriptions = [
        ParameterDescription(
            identifier="mask_point_count", label="Nombre de sommets", kind="numeric_slider", default=4.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=float(_MAX_MASK_VERTICES), step=1.0),
        ),
        ParameterDescription(
            identifier="mask_feather", label="Adoucissement du contour", kind="numeric_slider", default=2.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=20.0, step=0.5),
        ),
        ParameterDescription(
            identifier="mask_invert", label="Inverser le contour", kind="numeric_slider", default=0.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=1.0),
        ),
    ]
    for i in range(_MAX_MASK_VERTICES):
        default_x, default_y = _DEFAULT_MASK_POINTS[i] if i < len(_DEFAULT_MASK_POINTS) else (0.5, 0.5)
        descriptions.append(ParameterDescription(
            identifier=f"mask_point_{i:02d}_x", label=f"Sommet {i} (x)", kind="numeric_slider",
            default=default_x, zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.001),
        ))
        descriptions.append(ParameterDescription(
            identifier=f"mask_point_{i:02d}_y", label=f"Sommet {i} (y)", kind="numeric_slider",
            default=default_y, zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.001),
        ))
    return tuple(descriptions)


# ---------------------------------------------------------------------------
# Calibrations. Neutre has no calibration (no `look` key at all, matching film.py's Neutral).
# Balance is re-expressed on the new -100..100 scale (Decision 11) -- NOT a numeric re-derivation
# of the old ±1/±2-scale values, since Decision 11 explicitly accepts that old recipes become
# near-no-ops rather than requiring exact behavioral equivalence; the new calibration reproduces
# Balance's ORIGINAL INTENT (a mild exposure lift with highlight recovery) directly on the new
# scale. Low Key/High Key/Dramatique/Soft are new -- exact calibration numbers are a technical
# design detail, not a product requirement, fixed here to reproduce each preset's documented
# directional intent; each preset's own comment records the perceptual intent its 7-point
# reference curve described -- the literal curve values themselves are
# not reproduced verbatim (no point-curve interpolation exists in this engine, by design).
# ---------------------------------------------------------------------------

_NEUTRAL_GRADE = _LightGrade()

_BALANCE_GRADE = _LightGrade(
    exposure=15.0,
    shadows=25.0,
    highlights=-20.0,
)

_LOW_KEY_GRADE = _LightGrade(
    # Intent: dark, moody, contrasted -- deep blacks and shadows, a handful of highlights
    # preserved (not blown out), cool shadows with a small warm highlight accent, a nudge of
    # extra clarity/texture and a dark vignette to reinforce the mood.
    exposure=-35.0,
    contrast=25.0,
    contrast_pivot=0.45,
    blacks=-30.0,
    shadows=-35.0,
    highlights=-10.0,
    whites=-5.0,
    black_point=0.04,
    saturation=0.85,
    temperature=-80.0,
    split_shadow_hue=210.0,
    split_shadow_strength=10.0,
    split_highlight_hue=40.0,
    split_highlight_strength=3.0,
    clarity=15.0,
    texture=8.0,
    sharpness=5.0,
    dehaze=5.0,
    vignette=-25.0,
    grain=0.015,
)

_HIGH_KEY_GRADE = _LightGrade(
    # Intent: bright, airy, soft -- lifted shadows and a faded/lifted black floor, restrained
    # contrast, highlights nudged up but rolled off at the very top (whites slightly negative) so
    # they never go uniformly pure white, warm pastel colour, a light (not dark) vignette.
    exposure=30.0,
    contrast=-15.0,
    contrast_pivot=0.55,
    blacks=5.0,
    shadows=25.0,
    highlights=5.0,
    whites=-5.0,
    black_floor=0.06,
    saturation=0.90,
    temperature=60.0,
    tint=1.0,
    split_shadow_hue=45.0,
    split_shadow_strength=4.0,
    split_highlight_hue=50.0,
    split_highlight_strength=6.0,
    clarity=-10.0,
    texture=-5.0,
    dehaze=-5.0,
    vignette=10.0,
    grain=0.006,
)

_DRAMATIQUE_GRADE = _LightGrade(
    # Intent: intense, high contrast, deep shadows, a slight overall desaturation with a
    # teal-shadows/warm-highlights split (the split-tone strengths alone already favor shadows,
    # 8% vs. 6%, without needing a separate "balance" control), strong clarity/texture for a
    # punchy, detailed look. Calibrated so overall output std-dev exceeds the input's on a
    # realistic-tonal-variance fixture (SC-002's directional oracle) -- an
    # earlier, more heavily-darkened variant (larger negative exposure/shadows/highlights) instead
    # REDUCED std-dev by crushing too much of the range toward black; contrast carries most of the
    # "intense" effect here, exposure/shadows/highlights stay comparatively restrained.
    exposure=-5.0,
    contrast=60.0,
    blacks=-10.0,
    shadows=-15.0,
    highlights=-5.0,
    whites=10.0,
    black_point=0.02,
    saturation=0.80,
    temperature=-30.0,
    split_shadow_hue=195.0,
    split_shadow_strength=8.0,
    split_highlight_hue=35.0,
    split_highlight_strength=6.0,
    clarity=25.0,
    texture=15.0,
    sharpness=10.0,
    dehaze=10.0,
    vignette=-30.0,
    grain=0.02,
)

_SOFT_GRADE = _LightGrade(
    # Intent: gentle, low contrast, warm glow, reduced fine detail, PLUS (User Story 5) a soft halo
    # on bright zones and a protected soft-detail smoothing pass that spares sharp edges (FR-013).
    exposure=12.0,
    contrast=-25.0,
    blacks=8.0,
    shadows=15.0,
    highlights=-8.0,
    whites=-5.0,
    black_floor=0.05,
    saturation=0.85,
    temperature=40.0,
    tint=2.0,
    split_shadow_hue=30.0,
    split_shadow_strength=3.0,
    split_highlight_hue=45.0,
    split_highlight_strength=5.0,
    clarity=-20.0,
    texture=-15.0,
    sharpness=-10.0,
    dehaze=-8.0,
    bloom_threshold=0.72,
    bloom_amount=22.0,
    bloom_radius=2.5,
    bloom_warmth=150.0,
    soft_detail_amount=28.0,
    soft_detail_radius=3.0,
    edge_protection=75.0,
    grain=0.004,
)

_GRADES: dict[str, _LightGrade] = {
    "balance": _BALANCE_GRADE,
    "low_key": _LOW_KEY_GRADE,
    "high_key": _HIGH_KEY_GRADE,
    "dramatique": _DRAMATIQUE_GRADE,
    "soft": _SOFT_GRADE,
}


def resolve_zoom_values(params: dict[str, Any]) -> dict[str, float]:
    """Returns the effective value of every declared identifier -- base-grade fields (an override
    present in `params` wins, otherwise the selected look's own calibrated value), `intensity`,
    the 38 subject_*/background_* region-delta fields, and the 67 mask fields -- completeness
    (every identifier in ADDON_DESCRIPTION.parameter_descriptions has an entry here) is the direct
    regression guard for the bug already fixed once on this same addon in F-043."""
    intensity = _read_float(params, "intensity", 1.0, minimum=0.0, maximum=1.0)
    values: dict[str, float] = {"intensity": intensity}
    base = _GRADES.get(params.get("look"), _NEUTRAL_GRADE)
    grade = _apply_grade_overrides(base, params)
    for field_name in _FIELD_BOUNDS:
        values[field_name] = float(getattr(grade, field_name))

    for prefix in ("subject", "background"):
        deltas = _read_region_deltas(params, prefix)
        for field_name in _REGION_COMPOSITION:
            values[f"{prefix}_{field_name}"] = float(getattr(deltas, field_name))

    values["mask_point_count"] = _read_float(params, "mask_point_count", 4.0, minimum=0.0, maximum=_MAX_MASK_VERTICES)
    values["mask_feather"] = _read_float(params, "mask_feather", 2.0, minimum=0.0, maximum=20.0)
    values["mask_invert"] = 1.0 if _read_bool(params, "mask_invert", False) else 0.0
    for i in range(_MAX_MASK_VERTICES):
        default_x, default_y = _DEFAULT_MASK_POINTS[i] if i < len(_DEFAULT_MASK_POINTS) else (0.5, 0.5)
        values[f"mask_point_{i:02d}_x"] = _read_float(params, f"mask_point_{i:02d}_x", default_x, minimum=0.0, maximum=1.0)
        values[f"mask_point_{i:02d}_y"] = _read_float(params, f"mask_point_{i:02d}_y", default_y, minimum=0.0, maximum=1.0)
    return values


def light_adjustments(image: numpy.ndarray, params: dict[str, Any]) -> numpy.ndarray:
    """Light addon transform (data-model.md's Processing pipeline). No recognized key in `params`
    at all, or a base grade AND both region deltas resolving to strictly neutral values, returns
    `image` unchanged, bit-identical (SC-001) -- covers Neutre, an explicit all-neutral recipe, and
    an all-malformed reload alike. Never raises; does not mutate `image`."""
    if not params:
        return image
    base = _GRADES.get(params.get("look"), _NEUTRAL_GRADE)
    grade = _apply_grade_overrides(base, params)
    intensity = _read_float(params, "intensity", 1.0, minimum=0.0, maximum=1.0)
    subject_deltas = _read_region_deltas(params, "subject")
    background_deltas = _read_region_deltas(params, "background")
    if grade == _NEUTRAL_GRADE and subject_deltas == _RegionDeltas() and background_deltas == _RegionDeltas():
        return image
    if intensity == 0.0:
        return image

    source = image.astype(numpy.float32)
    mask = _read_mask(params)
    subject_grade = _compose_region(grade, subject_deltas)
    background_grade = _compose_region(grade, background_deltas)

    if mask is None or subject_grade == background_grade:
        # No boundary drawn -- the "Global" reading of every field. Per the documented edge case
        # ("sans contour défini... le réglage du Fond s'applique à l'image entière"), the
        # background-composed grade is the one applied -- it equals subject_grade whenever they're
        # equal anyway, so this is a single, unambiguous choice either way.
        graded = _apply_region_grade(source, background_grade)
    else:
        # Perf remediation (T047, measured on a 12MP image: naive two full-image grades cost
        # ~2.2x a single-region render). The mask's own (feather-padded) bounding box is where
        # alpha actually transitions -- outside it, alpha is ~0 or ~1 by construction (uniformly
        # background or uniformly subject), so only ONE of the two region renders ever needs to be
        # full-image; the other can be cropped to the bounding box and blended in. Which one is
        # "small" flips with `invert`: normally the SUBJECT region is the polygon interior (crop
        # it, render background full-image) -- inverted, the polygon interior becomes the
        # BACKGROUND region instead (crop it, render subject full-image). Cropping the wrong side
        # here silently drops the region delta over most of the image whenever inverted (bug found
        # 2026-07-28: the original version always cropped the subject render, which is correct only
        # for the non-inverted case).
        x0, x1, y0, y1 = _mask_bounding_box(mask.points, mask.feather_pct, source.shape)
        alpha = _polygon_mask(source.shape, mask.points, mask.feather_pct, mask.invert)[..., numpy.newaxis]
        if not mask.invert:
            full_result = _apply_region_grade(source, background_grade)
            graded = full_result.copy()
            if x1 > x0 and y1 > y0:
                crop_result = _apply_region_grade(source[y0:y1, x0:x1], subject_grade)
                alpha_crop = alpha[y0:y1, x0:x1]
                graded[y0:y1, x0:x1] = alpha_crop * crop_result + (1.0 - alpha_crop) * full_result[y0:y1, x0:x1]
        else:
            full_result = _apply_region_grade(source, subject_grade)
            graded = full_result.copy()
            if x1 > x0 and y1 > y0:
                crop_result = _apply_region_grade(source[y0:y1, x0:x1], background_grade)
                alpha_crop = alpha[y0:y1, x0:x1]
                graded[y0:y1, x0:x1] = alpha_crop * full_result[y0:y1, x0:x1] + (1.0 - alpha_crop) * crop_result

    # Global tail (Decision 9): applied once on the composite, never per-region, in this order:
    # soft-detail -> bloom -> vignette -> grain.
    graded = _apply_soft_detail(graded, grade.soft_detail_amount, grade.soft_detail_radius, grade.edge_protection)
    graded = _apply_bloom(graded, grade.bloom_threshold, grade.bloom_amount, grade.bloom_radius, grade.bloom_warmth)
    graded = _apply_vignette(graded, grade.vignette)
    graded = _apply_grain(graded, grade.grain, grade.grain_size)

    if intensity == 1.0:
        result = graded
    else:
        result = source * (1.0 - intensity) + graded * intensity
    return numpy.clip(result, 0, 255).round().astype(numpy.uint8)


ADDON_DESCRIPTION = AddonSubmission(
    identifier="light_adjustments",
    label="Lumière",
    category="light",
    thumbnail_presets=(
        ThumbnailPreset(identifier="neutral", label="Neutre", neutral=True),
        ThumbnailPreset(identifier="Balance", label="Balance", preset_parameters={"look": "balance", "intensity": 1.0}),
        ThumbnailPreset(identifier="Low Key", label="Low Key", preset_parameters={"look": "low_key", "intensity": 1.0}),
        ThumbnailPreset(identifier="High Key", label="High Key", preset_parameters={"look": "high_key", "intensity": 1.0}),
        ThumbnailPreset(identifier="Dramatique", label="Dramatique", preset_parameters={"look": "dramatique", "intensity": 1.0}),
        ThumbnailPreset(identifier="Soft", label="Soft", preset_parameters={"look": "soft", "intensity": 1.0}),
    ),
    processing_function=light_adjustments,
    resolve_zoom_values=resolve_zoom_values,
    parameter_descriptions=(
        ParameterDescription(
            identifier="intensity", label="Intensité", kind="numeric_slider", default=1.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.01),
        ),
        ParameterDescription(
            identifier="exposure", label="Exposition", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="contrast", label="Contraste", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="contrast_pivot", label="Pivot de contraste", kind="numeric_slider", default=0.5,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.2, maximum=0.8, step=0.01),
        ),
        ParameterDescription(
            identifier="blacks", label="Noirs", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="shadows", label="Ombres", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="highlights", label="Hautes lumières", kind="numeric_slider", default=0.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="whites", label="Blancs", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="black_point", label="Point noir", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=0.10, step=0.005),
        ),
        ParameterDescription(
            identifier="black_floor", label="Plancher de noir", kind="numeric_slider", default=0.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=0.10, step=0.005),
        ),
        ParameterDescription(
            identifier="saturation", label="Saturation", kind="numeric_slider", default=1.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=0.01),
        ),
        ParameterDescription(
            identifier="temperature", label="Température", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-1000.0, maximum=1000.0, step=10.0),
        ),
        ParameterDescription(
            identifier="tint", label="Teinte", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-20.0, maximum=20.0, step=0.5),
        ),
        ParameterDescription(
            identifier="split_shadow_hue", label="Virage ombres (teinte)", kind="numeric_slider",
            default=220.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=360.0, step=1.0),
        ),
        ParameterDescription(
            identifier="split_shadow_strength", label="Virage ombres (force)", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=20.0, step=0.5),
        ),
        ParameterDescription(
            identifier="split_highlight_hue", label="Virage hautes lumières (teinte)", kind="numeric_slider",
            default=45.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=360.0, step=1.0),
        ),
        ParameterDescription(
            identifier="split_highlight_strength", label="Virage hautes lumières (force)", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=20.0, step=0.5),
        ),
        ParameterDescription(
            identifier="hsl_saturation_scale", label="Saturation HSL", kind="numeric_slider", default=1.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=0.05),
        ),
        ParameterDescription(
            identifier="hsl_luminance_scale", label="Luminance HSL", kind="numeric_slider", default=1.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=0.05),
        ),
        ParameterDescription(
            identifier="clarity", label="Clarté", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="texture", label="Texture", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="sharpness", label="Netteté", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="dehaze", label="Dehaze", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="bloom_threshold", label="Halo (seuil)", kind="numeric_slider", default=0.8,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.01),
        ),
        ParameterDescription(
            identifier="bloom_amount", label="Halo (intensité)", kind="numeric_slider", default=0.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=50.0, step=1.0),
        ),
        ParameterDescription(
            identifier="bloom_radius", label="Halo (rayon)", kind="numeric_slider", default=2.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=5.0, step=0.1),
        ),
        ParameterDescription(
            identifier="bloom_warmth", label="Halo (chaleur)", kind="numeric_slider", default=0.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=-500.0, maximum=500.0, step=10.0),
        ),
        ParameterDescription(
            identifier="soft_detail_amount", label="Douceur (intensité)", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=50.0, step=1.0),
        ),
        ParameterDescription(
            identifier="soft_detail_radius", label="Douceur (rayon)", kind="numeric_slider",
            default=3.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=8.0, step=0.1),
        ),
        ParameterDescription(
            identifier="edge_protection", label="Protection des contours", kind="numeric_slider",
            default=70.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="vignette", label="Vignettage", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="grain", label="Grain", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=0.05, step=0.001),
        ),
        *_region_delta_parameter_descriptions("subject", "Sujet"),
        *_region_delta_parameter_descriptions("background", "Fond"),
        *_mask_parameter_descriptions(),
    ),
    overlay_descriptions=(),
)
