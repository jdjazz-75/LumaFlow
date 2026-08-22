# LumaFlow v1.0 (2026-08-07)
# Decode un fichier RAW (demosaic via rawpy) avec balance des blancs as-shot
# appliquee avant demosaic ; expose decode_raw() et resolve_white_balance_gains().
"""RAW decoding — demosaic a RAW candidate (spec 051) into a base RGB matrix,
white-balanced using the file's own as-shot metadata.

Deliberately produces a matrix with no tone curve beyond white balance.
The remaining "initial development"
step (053) turns this scene-referred output into a display-referred image —
052's own job now includes white balance (see amendment below), but stops short
of any tone-mapping/contrast adjustment.

**Amendment 3 (2026-08-21)**: `output_bps` raised from 8 to 16. This function's
output is *linear light* (`gamma=(1, 1)`, `no_auto_bright=True`), and quantizing
linear light to 8 bits before any transfer function is applied throws away most
of the shadow precision — the sRGB encoding that 053 now applies stretches the
bottom of the range hard (a linear 0.18 mid-gray maps to ~0.46 encoded), so an
8-bit linear intermediate would band visibly. 16 bits keeps the decode lossless
with respect to the tone stage that follows. This changes decode_raw()'s return
dtype from uint8 to uint16 — `develop_initial()` (053) is the only production
caller and it now requires uint16. The final `ImageSession` is still uint8; the
16-bit values never leave the RAW decode/develop pair.

**Amendment (2026-08-04)**: `use_camera_wb=False, use_auto_wb=False` alone does
NOT mean "no white balance" — per rawpy's own `postprocess()` docstring, "If
use_camera_wb and use_auto_wb are False and user_wb is None, then daylight
white balance correction is used." Leaving `user_wb` unset made this function
silently apply a real (non-identity) daylight WB, which 053's develop_initial()
then multiplied a second, camera-specific WB gain on top of — a double
correction that showed up as a strong red cast on real camera files.

**Amendment 2 (2026-08-04)**: passing a fixed identity `user_wb=[1,1,1,1]`
(the first amendment's fix) removed the double correction but introduced a
*different* color cast (excess green), confirmed against real Canon/Nikon/Sony
files in `exemples/raw/`. Root cause, verified by comparing decode_raw()'s
identity-WB output against rawpy's own `use_camera_wb=True` reference output
pixel-for-pixel: LibRaw applies white balance *before* demosaicing, as an
input to its own interpolation algorithm — it is not a simple post-hoc
per-channel multiply. Multiplying a WB gain onto an *already-demosaiced*,
identity-WB image (053's old approach) cannot reproduce the same colors as
applying that gain before demosaic, regardless of intermediate bit depth
(verified: re-running the same experiment with `output_bps=16` before the
gain multiply produced the same wrong result as 8-bit — this is an ordering
bug, not a precision bug). The only correct fix is to resolve the real as-shot
white-balance gains *before* calling `postprocess()` and pass them as
`user_wb`, in this single decode call — white balance is therefore now
decode_raw()'s responsibility, not 053's. Verified empirically against real
Canon/Nikon/Sony files.
"""
from __future__ import annotations

import pathlib

import numpy
import rawpy

DEFAULT_WHITE_BALANCE_GAINS: tuple[float, float, float] = (1.0, 1.0, 1.0)


def resolve_white_balance_gains(path: pathlib.Path) -> tuple[tuple[float, float, float], str]:
    """Read the RAW file's as-shot `camera_whitebalance` metadata and
    normalize it to green-relative gains `(R/G, 1.0, B/G)`. Falls back to
    `DEFAULT_WHITE_BALANCE_GAINS` (source "fallback") when the file can't be
    reopened for a header-only read, or the metadata is missing/invalid —
    never raises."""
    try:
        with rawpy.imread(str(path)) as raw:
            camera_wb = raw.camera_whitebalance
    except Exception:
        return DEFAULT_WHITE_BALANCE_GAINS, "fallback"

    if not camera_wb or len(camera_wb) < 3:
        return DEFAULT_WHITE_BALANCE_GAINS, "fallback"

    red, green, blue = camera_wb[0], camera_wb[1], camera_wb[2]
    if red <= 0 or green <= 0 or blue <= 0:
        return DEFAULT_WHITE_BALANCE_GAINS, "fallback"

    return (red / green, 1.0, blue / green), "metadata"


def decode_raw(path: pathlib.Path) -> numpy.ndarray:
    """Decode a RAW candidate file into an (H, W, 3) uint16 RGB array holding
    **linear light** (scene-referred), with the file's own as-shot white
    balance applied during demosaic (or the documented neutral fallback when
    metadata is missing/invalid — see `resolve_white_balance_gains`).

    The output is deliberately *not* displayable as-is: with no transfer
    function applied it reads as very dark on screen. Turning it into a
    display-referred image is `develop_initial()`'s job (053).

    Read-only: never writes to `path`. Raises on any decode failure (e.g.
    `rawpy.LibRawError` for a corrupted or unrecognized file) — translating
    that into a user-facing error is `load_image()`'s job, not this
    function's."""
    gains, _source = resolve_white_balance_gains(path)
    with rawpy.imread(str(path)) as raw:
        return raw.postprocess(
            use_camera_wb=False,
            use_auto_wb=False,
            # Real as-shot gains (or neutral fallback) applied here, before
            # demosaic — see module docstring amendment 2.
            user_wb=[gains[0], gains[1], gains[2], gains[1]],
            # Linear, unbrightened output: the tone curve (auto-exposure,
            # highlight shoulder, sRGB OETF) belongs to 053, which needs an
            # untouched scene-referred signal to work from.
            no_auto_bright=True,
            gamma=(1, 1),
            # 16 bits, not 8 — see module docstring amendment 3.
            output_bps=16,
            # Orientation is 054's exclusive responsibility (raw_metadata.apply_orientation,
            # driven by raw.sizes.flip) — never let LibRaw auto-rotate here, or the two would
            # compound.
            user_flip=0,
        )
