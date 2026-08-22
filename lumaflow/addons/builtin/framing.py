# LumaFlow v1.0 (2026-08-07)
# Addon Cadrage : recadrage manuel libre plus catalogue de guides de composition
# (tiers, section/spirale d'or, lignes, diagonale, pyramide, courbe composee).
"""Framing addon -- free-form manual crop with a catalog of selectable
composition guide overlays (thirds, golden section/triangles/spiral, center
lines, diagonal, pyramid, compound curve, symmetry). No aspect-ratio-locked
presets: the crop always starts full-frame and is shaped entirely through the
crop_x/y/width/height parameters (drag-handle UI on the web side).

No Qt, no pipeline engine, no persistence module import (same convention as
every module under lumaflow/addons/).
"""

from __future__ import annotations

from typing import Any

import numpy

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission
from lumaflow.addons.parameters import NumericSliderConstraints, OverlayDescription, ParameterDescription

_MINIMUM_SIZE = 0.05


def _resolve_box(params: dict[str, Any]) -> tuple[float, float, float, float]:
    """Reads crop_x/crop_y/crop_width/crop_height independently -- each
    missing/non-numeric value falls back to its own default (0.0/0.0/1.0/1.0)
    rather than discarding the whole box. Clamps
    crop_width/crop_height to a minimum of 0.05 and shrinks the box (never
    shifts it) to stay within [0, 1] on both axes.
    """
    raw = {
        "crop_x": params.get("crop_x", 0.0),
        "crop_y": params.get("crop_y", 0.0),
        "crop_width": params.get("crop_width", 1.0),
        "crop_height": params.get("crop_height", 1.0),
    }
    defaults = {"crop_x": 0.0, "crop_y": 0.0, "crop_width": 1.0, "crop_height": 1.0}
    values: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            values[key] = defaults[key]
        else:
            values[key] = float(value)

    x, y = values["crop_x"], values["crop_y"]
    w = max(values["crop_width"], _MINIMUM_SIZE)
    h = max(values["crop_height"], _MINIMUM_SIZE)

    w = min(w, 1.0)
    h = min(h, 1.0)
    x = min(max(x, 0.0), 1.0 - w)
    y = min(max(y, 0.0), 1.0 - h)

    return x, y, w, h


def resolve_zoom_values(params: dict[str, Any]) -> dict[str, float]:
    """Returns the crop box actually in effect (an override present in
    `params` wins, otherwise each field's own default) so the Zoom overlay
    can seed its crop-frame UI with the real active box instead of resetting
    to the generic 0/0/1/1 default every time the view is reopened.
    """
    x, y, w, h = _resolve_box(params)
    return {"crop_x": x, "crop_y": y, "crop_width": w, "crop_height": h}


def crop(image: numpy.ndarray, params: dict[str, Any]) -> numpy.ndarray:
    """Manual/preset crop addon transform. The
    clamped full-frame box ``(0, 0, 1, 1)`` returns ``image`` unchanged --
    bit-identical, not merely visually indistinguishable (SC-001). Otherwise
    slices the image to the kept region -- a new array with a different
    ``(H, W)`` than the input. Never raises; does not mutate ``image``.
    """
    x, y, w, h = _resolve_box(params)
    if (x, y, w, h) == (0.0, 0.0, 1.0, 1.0):
        return image
    height, width = image.shape[0], image.shape[1]
    x0 = int(round(x * width))
    y0 = int(round(y * height))
    x1 = max(x0 + 1, int(round((x + w) * width)))
    y1 = max(y0 + 1, int(round((y + h) * height)))
    x1 = min(x1, width)
    y1 = min(y1, height)
    return image[y0:y1, x0:x1].copy()


ADDON_DESCRIPTION = AddonSubmission(
    identifier="framing_crop",
    label="Cadrage",
    category="framing",
    thumbnail_presets=(
        ThumbnailPreset(identifier="neutral", label="Neutre", neutral=True),
    ),
    processing_function=crop,
    resolve_zoom_values=resolve_zoom_values,
    parameter_descriptions=(
        ParameterDescription(
            identifier="crop_x", label="X", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.01),
        ),
        ParameterDescription(
            identifier="crop_y", label="Y", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.01),
        ),
        ParameterDescription(
            identifier="crop_width", label="Width", kind="numeric_slider", default=1.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.01),
        ),
        ParameterDescription(
            identifier="crop_height", label="Height", kind="numeric_slider", default=1.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.01),
        ),
    ),
    # Composition guide catalog rendered inside the crop frame on the web side
    # (lib/cropGuides.ts) -- purely geometric, selected exclusively (one active
    # at a time) via small vignettes on the frame border. "thirds" is the only
    # one active by default; golden_spiral is the only kind with a frontend-
    # local orientation sub-control (graphical_parameters here is just the
    # catalog's default hint, not live per-session state).
    overlay_descriptions=(
        OverlayDescription(
            kind="thirds", label="Règle des tiers", default_active=True, graphical_parameters={},
        ),
        # Golden Section / Golden Triangles / Golden Spiral: kept untranslated -- these are
        # established English composition-guide names (as in every mainstream photo editor); a
        # literal French translation reads as unnatural/meaningless (user feedback, 2026-07-24).
        OverlayDescription(
            kind="golden_section", label="Golden Section", default_active=False, graphical_parameters={},
        ),
        OverlayDescription(
            kind="golden_triangles", label="Golden Triangles", default_active=False, graphical_parameters={},
        ),
        OverlayDescription(
            kind="golden_spiral", label="Golden Spiral", default_active=False, graphical_parameters={},
        ),
        OverlayDescription(
            kind="center_lines", label="Lignes vers le centre", default_active=False, graphical_parameters={},
        ),
        OverlayDescription(
            kind="diagonal", label="Diagonale", default_active=False, graphical_parameters={},
        ),
        OverlayDescription(
            kind="pyramid", label="Pyramide", default_active=False, graphical_parameters={},
        ),
        OverlayDescription(
            kind="compound_curve", label="Courbe composée", default_active=False, graphical_parameters={},
        ),
        # "Symétrie" (full edge-to-edge cross) removed: visually indistinguishable from
        # "Lignes vers le centre" once both are on screen at typical crop-frame sizes (user
        # feedback, 2026-07-24) -- rather than trying yet another visual differentiation, the
        # simpler guide (center_lines) was kept and this one dropped outright.
    ),
)
