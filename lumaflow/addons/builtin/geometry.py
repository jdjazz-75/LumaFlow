# LumaFlow v1.0 (2026-08-07)
# Addon Geometry : rotation manuelle plus correction de perspective libre a 4 coins
# ancree sur un cadre de reference centre.
"""Geometry addon -- dynamic geometric correction: manual rotation plus a free-form 4-corner
perspective correction anchored on a fixed centered reference frame (feature: Geometry rewrite,
2026-07-24). Supersedes the rotation-only v1 (feature 040).

No Qt, no pipeline engine, no persistence module import (same convention as every module under
lumaflow/addons/).
"""

from __future__ import annotations

import math
from typing import Any

import numpy
from PIL import Image

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission
from lumaflow.addons.parameters import NumericSliderConstraints, ParameterDescription

_MINIMUM_ANGLE = -45.0
_MAXIMUM_ANGLE = 45.0

# The correction frame is a rectangle centered on the photo covering FRAME_AREA_FRACTION of its
# *area* -- with a centered rectangle sharing the photo's own aspect ratio, that area fraction
# means each side is sqrt(FRAME_AREA_FRACTION) of the corresponding image dimension, i.e. a margin
# of (1 - sqrt(FRAME_AREA_FRACTION)) / 2 on every edge.
FRAME_AREA_FRACTION = 0.75
FRAME_MARGIN = (1 - math.sqrt(FRAME_AREA_FRACTION)) / 2

# Fractional [0,1]x[0,1] default corner positions -- the frame's undistorted rectangle. Also the
# "source" points for the perspective solve: the region of the (rotated) image that gets stretched
# into whatever quadrilateral the user drags the corners to.
_DEFAULT_CORNERS: dict[str, float] = {
    "corner_tl_x": FRAME_MARGIN, "corner_tl_y": FRAME_MARGIN,
    "corner_tr_x": 1.0 - FRAME_MARGIN, "corner_tr_y": FRAME_MARGIN,
    "corner_br_x": 1.0 - FRAME_MARGIN, "corner_br_y": 1.0 - FRAME_MARGIN,
    "corner_bl_x": FRAME_MARGIN, "corner_bl_y": 1.0 - FRAME_MARGIN,
}

# Corners may be dragged up to 50% past the image's own edge on either axis -- needed for strong
# keystone/perspective correction (e.g. a wide-angle building shot genuinely needs anchor points
# outside the visible frame).
_CORNER_MINIMUM = -0.5
_CORNER_MAXIMUM = 1.5

_CORNER_ORDER = ("tl", "tr", "br", "bl")


def _resolve_angle(params: dict[str, Any]) -> float:
    """A missing, non-numeric, or out-of-range rotation_angle is treated as
    0.0 (Neutral) rather than raising (unchanged from feature 040).
    """
    angle = params.get("rotation_angle", 0.0)
    if isinstance(angle, bool) or not isinstance(angle, (int, float)):
        return 0.0
    angle = float(angle)
    if not (_MINIMUM_ANGLE <= angle <= _MAXIMUM_ANGLE):
        return 0.0
    return angle


def _resolve_corners(params: dict[str, Any]) -> dict[str, float]:
    """Reads the 8 corner_*_x/corner_*_y keys independently -- each missing or non-numeric value
    falls back to its own default (the neutral frame position) rather than discarding the whole
    quad, mirroring framing.py's _resolve_box. A numeric but out-of-range value is clamped to
    [-0.5, 1.5] rather than reset to default (unlike the angle's all-or-nothing convention), since
    a corner is a spatial coordinate that should degrade smoothly. No cross-field validation
    (self-intersection/bowtie) here -- that's the frontend's soft guard and _apply_perspective's
    LinAlgError fallback (below), not this function's job.
    """
    values: dict[str, float] = {}
    for key, default in _DEFAULT_CORNERS.items():
        raw = params.get(key, default)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            values[key] = default
        else:
            values[key] = min(max(float(raw), _CORNER_MINIMUM), _CORNER_MAXIMUM)
    return values


def resolve_zoom_values(params: dict[str, Any]) -> dict[str, float]:
    """Returns all 9 values actually in effect so the Zoom overlay can seed the rotation dial and
    corner frame with whatever was already committed, instead of resetting to neutral every time
    the panel is reopened (mirrors framing.py's resolve_zoom_values).
    """
    return {"rotation_angle": _resolve_angle(params), **_resolve_corners(params)}


def _rotate_image(image: numpy.ndarray, angle: float) -> numpy.ndarray:
    pil_image = Image.fromarray(image, mode="RGB")
    rotated = pil_image.rotate(
        angle, resample=Image.BICUBIC, expand=False, fillcolor=(0, 0, 0)
    )
    return numpy.asarray(rotated, dtype=numpy.uint8)


def _solve_perspective_coefficients(
    dest_points: list[tuple[float, float]], src_points: list[tuple[float, float]]
) -> tuple[float, float, float, float, float, float, float, float]:
    """Solves for the 8 coefficients of PIL's Image.PERSPECTIVE convention, where for each output
    pixel (x, y): x_src = (a*x + b*y + c) / (g*x + h*y + 1), y_src = (d*x + e*y + f) / (g*x + h*y +
    1) -- i.e. the coefficients already encode the output->source (inverse) mapping directly, no
    separate matrix inversion needed. Exactly 4 point correspondences -> 8 unknowns -> an exact
    `numpy.linalg.solve`, not a least-squares fit. Raises numpy.linalg.LinAlgError for a singular
    system (e.g. near-collinear corners) -- the caller degrades to identity rather than letting it
    propagate.
    """
    matrix = []
    vector = []
    for (dest_x, dest_y), (src_x, src_y) in zip(dest_points, src_points):
        matrix.append([dest_x, dest_y, 1, 0, 0, 0, -dest_x * src_x, -dest_y * src_x])
        vector.append(src_x)
        matrix.append([0, 0, 0, dest_x, dest_y, 1, -dest_x * src_y, -dest_y * src_y])
        vector.append(src_y)
    coeffs = numpy.linalg.solve(
        numpy.array(matrix, dtype=numpy.float64), numpy.array(vector, dtype=numpy.float64)
    )
    return tuple(float(c) for c in coeffs)  # type: ignore[return-value]


def _apply_perspective(image: numpy.ndarray, corners: dict[str, float]) -> numpy.ndarray:
    """Warps the whole image via a global perspective transform: the fixed reference frame
    rectangle (source) is mapped onto the user-dragged quadrilateral (destination), so the
    distortion made by dragging the frame's corners reproduces across the entire image, not just
    the pixels under the frame. Canvas size is unchanged; newly exposed regions fill solid black,
    matching _rotate_image's convention. Never raises: a degenerate (near-collinear) quad falls
    back to the input image unchanged.
    """
    height, width = image.shape[0], image.shape[1]
    src_points = [
        (_DEFAULT_CORNERS[f"corner_{name}_x"] * width, _DEFAULT_CORNERS[f"corner_{name}_y"] * height)
        for name in _CORNER_ORDER
    ]
    dest_points = [
        (corners[f"corner_{name}_x"] * width, corners[f"corner_{name}_y"] * height)
        for name in _CORNER_ORDER
    ]
    try:
        coeffs = _solve_perspective_coefficients(dest_points, src_points)
    except numpy.linalg.LinAlgError:
        return image
    pil_image = Image.fromarray(image, mode="RGB")
    warped = pil_image.transform(
        (width, height), Image.PERSPECTIVE, coeffs, resample=Image.BICUBIC, fillcolor=(0, 0, 0)
    )
    return numpy.asarray(warped, dtype=numpy.uint8)


def correct_geometry(image: numpy.ndarray, params: dict[str, Any]) -> numpy.ndarray:
    """Combined rotation + perspective-correction addon transform. Neutral in both dimensions
    (angle == 0.0 and all 8 corners at their default frame position) returns `image` unchanged --
    bit-identical, not merely visually indistinguishable. Otherwise rotates first (about the image
    center, unchanged from feature 040), then applies the perspective correction, each step skipped
    independently when neutral so a single-dimension edit costs only one resample pass. Never
    raises; does not mutate `image`.
    """
    angle = _resolve_angle(params)
    corners = _resolve_corners(params)
    corners_are_neutral = corners == _DEFAULT_CORNERS

    if angle == 0.0 and corners_are_neutral:
        return image

    working = image
    if angle != 0.0:
        working = _rotate_image(working, angle)
    if not corners_are_neutral:
        working = _apply_perspective(working, corners)
    return working


def _corner_parameter(identifier: str, label: str) -> ParameterDescription:
    return ParameterDescription(
        identifier=identifier,
        label=label,
        kind="numeric_slider",
        default=_DEFAULT_CORNERS[identifier],
        constraints=NumericSliderConstraints(
            minimum=_CORNER_MINIMUM, maximum=_CORNER_MAXIMUM, step=0.001
        ),
        zoom_only=True,
    )


ADDON_DESCRIPTION = AddonSubmission(
    identifier="geometry_correction",
    label="Geometry",
    category="geometry",
    thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutre", neutral=True),),
    processing_function=correct_geometry,
    resolve_zoom_values=resolve_zoom_values,
    parameter_descriptions=(
        ParameterDescription(
            identifier="rotation_angle",
            label="Rotation",
            kind="numeric_slider",
            default=0.0,
            constraints=NumericSliderConstraints(
                minimum=_MINIMUM_ANGLE, maximum=_MAXIMUM_ANGLE, step=0.1
            ),
            zoom_only=True,
        ),
        _corner_parameter("corner_tl_x", "Coin haut-gauche X"),
        _corner_parameter("corner_tl_y", "Coin haut-gauche Y"),
        _corner_parameter("corner_tr_x", "Coin haut-droit X"),
        _corner_parameter("corner_tr_y", "Coin haut-droit Y"),
        _corner_parameter("corner_br_x", "Coin bas-droit X"),
        _corner_parameter("corner_br_y", "Coin bas-droit Y"),
        _corner_parameter("corner_bl_x", "Coin bas-gauche X"),
        _corner_parameter("corner_bl_y", "Coin bas-gauche Y"),
    ),
    # No declared overlays: the alignment aids (vertical/horizontal line + 3x3 grid) are ephemeral
    # and client-side only (2026-07-24 decision) -- they never round-trip through the backend the
    # way Framing's composition-guide catalog does. The old kind="grid" "Level guide" overlay from
    # feature 040 is dropped; it was never actually rendered by the web frontend anyway (only the
    # deprecated Qt path drew it).
    overlay_descriptions=(),
)
