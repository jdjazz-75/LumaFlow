# LumaFlow v1.0 (2026-08-07)
# Developpement initial post-decodage RAW : transforme le lineaire scene-referred
# de decode_raw() en image display-referred (auto-exposition bornee, epaulement
# hautes lumieres, encodage sRGB) via une LUT 16 bits -> 8 bits.
"""RAW initial development — turns 052's `decode_raw()` output (linear light,
uint16, scene-referred) into a display-referred uint8 image that looks like the
photo the camera took. Deliberately not a full RAW developer (no per-channel
contrast stretch, no camera picture-style emulation).

**Amendment (2026-08-04)**: white balance used to be applied *here*, as a
per-channel gain multiplied onto `decode_raw()`'s already-demosaiced output.
That approach is colorimetrically wrong — LibRaw applies white balance
*before* demosaic, as an input to its own interpolation, so a post-hoc gain
cannot reproduce the same colors (confirmed against real Canon/Nikon/Sony
files; see raw_decode.py's amendment 2). White balance is now
`decode_raw()`'s responsibility (052); this module only resolves the same
gains a second time (a cheap header-only read, not a second demosaic — R4)
for traceability reporting on `RawDevelopmentParams`.

**Amendment 2 (2026-08-21) — the "RAW files open far too dark" fix**: this
module used to apply only a degenerate-exposure safeguard that fired when the
95th percentile was <= 10/255 or the 5th was >= 245/255. On any real photo
that test never fires, so the pipeline shipped raw *linear light* straight to
the screen, where it is interpreted as if it were sRGB-encoded. Measured on 12
Canon/Nikon/Sony files: median luminance 6-54/255, against 45-180 for the
camera's own embedded JPEG. The missing piece was never white balance or the
decoding library — it was the display transfer function.

The chain below replaces that safeguard (which it subsumes: a gain clamped to
[0, +2] EV can no longer produce an all-black or all-white default):

  1. bounded auto-exposure, computed from subsampled luminance statistics;
  2. a soft highlight shoulder, so the gain cannot clip highlights;
  3. the sRGB OETF, i.e. the transfer function that was missing entirely.

Measured against the cameras' own embedded JPEGs on those same 12 files: mean
absolute median error 20.2 (down from ~85), medians 87-165, clipping <= 0.08%.

Why the exposure gain is bounded and never darkens: the RAW already carries the
exposure the photographer chose. Normalizing every image onto a fixed mid-gray
target was measured and is *worse* (mean error 27.6) — it flattens a
deliberately dark frame up and a bright one down, erasing intent. What was
missing is a display transform, not a normalization; the gain only rescues
under-exposure.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass

import numpy

from lumaflow.engine.raw_decode import (
    DEFAULT_WHITE_BALANCE_GAINS,
    resolve_white_balance_gains,
)

# Auto-exposure. Two independent estimates are combined as a geometric mean
# (= the average of the two in EV space): a highlight-anchored one, which asks
# "how far is the brightest real content from the top of the range?", and a
# mid-gray one, which asks "how far is the typical tone from 18% gray?".
# Neither alone tracks the camera rendering well across the test set; their
# EV-average does.
_HIGHLIGHT_PERCENTILE = 99.5  # ignores specular pinpoints and hot pixels
_HIGHLIGHT_TARGET = 0.90  # leave headroom above the brightest real content
_MID_GRAY_PERCENTILE = 50
_MID_GRAY_TARGET = 0.18
_COMPONENT_GAIN_MAX = 16.0  # clamp each estimate before averaging
_GAIN_MIN = 1.0  # never darken: the RAW's exposure is the photographer's
_GAIN_MAX = 4.0  # +2 EV ceiling

# Statistics are computed on every 4th pixel in each axis. Measured on a
# 6080x4044 Nikon D3X file: 0.003 EV away from the full-resolution result.
_STATS_STRIDE = 4

# Rec.709 luminance weights.
_LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)

# Highlight shoulder: below the knee the response stays linear, above it an
# exponential roll-off approaches 1.0 asymptotically, so applying the gain can
# no longer push highlights to a hard clip.
_SHOULDER_KNEE = 0.75

# sRGB OETF (IEC 61966-2-1).
_SRGB_LINEAR_THRESHOLD = 0.0031308
_SRGB_LINEAR_SLOPE = 12.92
_SRGB_ALPHA = 1.055
_SRGB_EXPONENT = 1 / 2.4

_UINT16_MAX = 65535.0


@dataclass(frozen=True)
class RawDevelopmentParams:
    white_balance_gains: tuple[float, float, float]
    white_balance_source: str  # "metadata" | "fallback"
    exposure_gain_ev: float = 0.0


def _auto_exposure_gain(linear_pixels: numpy.ndarray) -> float:
    """Resolve the linear exposure multiplier for an (H, W, 3) uint16 linear
    image. Always within [`_GAIN_MIN`, `_GAIN_MAX`]."""
    sample = linear_pixels[::_STATS_STRIDE, ::_STATS_STRIDE].astype(numpy.float32)
    sample /= _UINT16_MAX
    luma = sample @ numpy.asarray(_LUMA_WEIGHTS, dtype=numpy.float32)

    highlight = float(numpy.percentile(luma, _HIGHLIGHT_PERCENTILE))
    mid_gray = float(numpy.percentile(luma, _MID_GRAY_PERCENTILE))

    highlight_gain = numpy.clip(
        _HIGHLIGHT_TARGET / max(highlight, 1e-5), _GAIN_MIN, _COMPONENT_GAIN_MAX
    )
    mid_gray_gain = numpy.clip(
        _MID_GRAY_TARGET / max(mid_gray, 1e-5), _GAIN_MIN, _COMPONENT_GAIN_MAX
    )

    combined = float(numpy.sqrt(highlight_gain * mid_gray_gain))
    return float(numpy.clip(combined, _GAIN_MIN, _GAIN_MAX))


def _tone_transfer(linear: numpy.ndarray, gain: float) -> numpy.ndarray:
    """The per-channel scalar tone chain — exposure gain, highlight shoulder,
    sRGB OETF — on linear values already normalized to 0..1. Kept separate from
    `_build_tone_lut` so tests can check the LUT against it directly."""
    x = numpy.clip(linear * gain, 0.0, None)

    knee = _SHOULDER_KNEE
    span = 1.0 - knee
    x = numpy.where(x > knee, knee + span * (1.0 - numpy.exp(-(x - knee) / span)), x)

    x = numpy.clip(x, 0.0, 1.0)
    return numpy.where(
        x <= _SRGB_LINEAR_THRESHOLD,
        x * _SRGB_LINEAR_SLOPE,
        _SRGB_ALPHA * numpy.power(x, _SRGB_EXPONENT) - (_SRGB_ALPHA - 1.0),
    )


def _build_tone_lut(gain: float) -> numpy.ndarray:
    """Fold the whole tone chain into a uint16 -> uint8 lookup table.

    Everything after the gain is resolved is a scalar function applied
    independently per channel, so the 65536 possible input values can be
    precomputed once and applied by fancy indexing. Measured on a 6080x4044
    file: 0.18s versus 4.10s for the same math evaluated over the full array,
    bit-for-bit identical, and it skips the ~295 MB float32 copy the direct
    form needs."""
    domain = numpy.arange(65536, dtype=numpy.float32) / _UINT16_MAX
    encoded = _tone_transfer(domain, gain) * 255.0
    return numpy.clip(numpy.round(encoded), 0, 255).astype(numpy.uint8)


def develop_initial(
    path: pathlib.Path, base_pixels: numpy.ndarray
) -> tuple[numpy.ndarray, RawDevelopmentParams]:
    """Develop `decode_raw()`'s linear uint16 output into a display-referred
    uint8 image. Never mutates `base_pixels`; never raises for missing or
    unreadable white-balance metadata (falls back silently, reported via
    `RawDevelopmentParams.white_balance_source`).

    Requires uint16 input — `decode_raw()` has produced linear 16-bit since
    its amendment 3 (2026-08-21), and interpreting 8-bit input here would
    silently apply the tone curve to the wrong scale."""
    if base_pixels.dtype != numpy.uint16:
        raise ValueError(
            "base_pixels must be the uint16 linear output of decode_raw(), "
            f"got dtype {base_pixels.dtype}."
        )

    gains, source = resolve_white_balance_gains(path)

    gain = _auto_exposure_gain(base_pixels)
    developed = _build_tone_lut(gain)[base_pixels]

    return developed, RawDevelopmentParams(
        white_balance_gains=gains,
        white_balance_source=source,
        exposure_gain_ev=float(numpy.log2(gain)),
    )
