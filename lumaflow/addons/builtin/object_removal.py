# LumaFlow v1.2 (2026-09-24)
# Addon Suppression d'objets : retire jusqu'a 4 zones d'une photo par completion
# d'image (LaMa, voir lumaflow/addons/inpainting/).
"""Object removal addon (feature 100) -- up to 4 user-drawn polygon zones, filled by
`lumaflow.addons.inpainting.inpaint_regions` (LaMa, a pretrained inpainting model -- see
`lumaflow/addons/inpainting/engine.py`'s module docstring for the pivot from the original
PatchMatch engine, `specs/100-addon-object-removal-v1/research.md` R3). `_MAX_ZONES` was lowered
from 8 to 4 on 2026-09-24 (ergonomics revision): the frontend now toggles each zone on/off from a
small fixed list in the Zoom panel rather than dynamically adding up to 8, and 4 fixed rows read
better there than 8.

No Qt, no pipeline engine, no persistence module import (same convention as every module under
lumaflow/addons/). Loaded via `importlib.util.spec_from_file_location` WITHOUT being registered in
`sys.modules` -- internal structures here use `typing.NamedTuple`, never `@dataclass`. The inpainting
ENGINE itself (`lumaflow/addons/inpainting/`) is a normal package, not a `builtin/` addon file, so
IT is registered in `sys.modules` and imported here with an ordinary absolute import -- see that
package's own `__init__.py` docstring for why.

Runs FIRST in the pipeline (row `removal`, before `geometry`/`framing` -- see
`.specify/memory/constitution.md` v1.7.0's Contraintes Produit): a zone's polygon is defined in
coordinates of the SOURCE photo, so a later rotation/perspective/crop never shifts it and never
re-triggers this addon's own (comparatively expensive) computation -- the per-pipeline-position
render cache in `lumaflow/api/session.py` only replays a step when ITS OWN parameters, or an
earlier step's, change.

Zone model: up to `_MAX_ZONES` independent polygons, each 3-32 vertices, flattened to scalar keys
exactly like `light.py`'s subject mask (`zone_{n}_mask_point_count`/`zone_{n}_mask_point_{ii}_x`/
`_y`) -- the `mask_` infix is deliberate, it lets the frontend's existing `maskValuesFromById`/
`isMaskParameter` helpers handle this addon's zones unchanged, just parameterized by a `zone_{n}_`
prefix instead of Light's bare one. Unlike Light's mask, there is no per-zone `feather`/`invert`:
"Marge" (dilation) and "Fondu" (feather) are single GLOBAL sliders shared by every zone on the photo
(one removal operation, one blend budget), and "Inverser" has no meaning for a removal tool.

All zone parameters are `transient=True` (never travel in a saved recipe) AND the whole `removal`
row is additionally excluded from recipes altogether (`lumaflow/persistence/recipe.py`'s
`EXCLUDED_STEP_IDENTIFIERS`) -- the same double safeguard `color_splash.py`'s own zones use,
mirroring Geometry/Framing's own exclusion (a removal zone is exactly as image-specific as a crop).
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.inpainting import inpaint_regions
from lumaflow.addons.loader import AddonSubmission
from lumaflow.addons.parameters import NumericSliderConstraints, ParameterDescription

_MAX_ZONES = 4
_MAX_MASK_VERTICES = 32


def _read_float(
    params: dict[str, Any], key: str, default: float, *, minimum: float | None = None, maximum: float | None = None
) -> float:
    """Reads one atomic parameter defensively -- a missing, non-numeric, boolean, or non-finite
    (NaN/inf) value falls back to its OWN default rather than discarding the whole step, same
    per-key fallback convention every addon in this codebase uses (e.g. `color_splash.py`'s own
    `_read_float`). The `math.isfinite` check is this addon's own addition on top of that shared
    convention -- a `_box_blur` overshoot or a malformed client payload could otherwise smuggle a
    NaN/inf through `isinstance(value, (int, float))` (both are real floats to Python) straight into
    `inpaint_regions`' geometry math; see `light.py:_read_float`'s own gotcha, noted but never
    fixed there since it is out of that addon's scope."""
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    if not math.isfinite(value):
        return default
    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


class _Zone(NamedTuple):
    points: tuple[tuple[float, float], ...]


def _read_zone(params: dict[str, Any], index: int) -> _Zone | None:
    """Resolves one zone's polygon from its flat scalar keys -- `count < 3` (missing, malformed, or
    explicitly below 3) returns `None`, meaning this zone slot is simply unused (the
    degenerate-polygon case: a near-zero-vertex "shape" is not an error, just nothing to remove)."""
    prefix = f"zone_{index}_"
    count = int(_read_float(params, f"{prefix}mask_point_count", 0.0, minimum=0.0, maximum=float(_MAX_MASK_VERTICES)))
    if count < 3:
        return None
    points = []
    for i in range(count):
        x = _read_float(params, f"{prefix}mask_point_{i:02d}_x", 0.5, minimum=0.0, maximum=1.0)
        y = _read_float(params, f"{prefix}mask_point_{i:02d}_y", 0.5, minimum=0.0, maximum=1.0)
        points.append((x, y))
    return _Zone(points=tuple(points))


def _read_zones(params: dict[str, Any]) -> tuple[tuple[tuple[float, float], ...], ...]:
    zones = []
    for index in range(_MAX_ZONES):
        zone = _read_zone(params, index)
        if zone is not None:
            zones.append(zone.points)
    return tuple(zones)


def remove_objects(image, params: dict[str, Any]):
    """Processing function (Principle III's declarative addon contract): never raises, never
    mutates `image`, returns `image` itself (bit-identical, no copy) when there is nothing to
    remove -- no zone at all, matching the neutral-return convention every addon here follows."""
    zones = _read_zones(params)
    if not zones:
        return image
    dilation_pct = _read_float(params, "dilation", 0.5, minimum=0.0, maximum=3.0)
    feather_pct = _read_float(params, "feather", 0.3, minimum=0.0, maximum=2.0)
    variant = int(_read_float(params, "variant", 0.0, minimum=0.0, maximum=999.0))
    return inpaint_regions(image, zones, dilation_pct, feather_pct, variant)


def resolve_zoom_values(params: dict[str, Any]) -> dict[str, float]:
    """Given a step's current parameter values, returns the EFFECTIVE value of every zoom
    parameter this addon declares -- an override present in `params` wins, otherwise this
    function's own declared default (mirrors `color_splash.py`'s resolver). Used by the Zoom
    overlay's "before"/"Réinitialiser" probes; also what `auxiliary_zoom_pure_default_values`
    (`lumaflow/api/session.py`) calls with `{"look": None, "intensity": 1.0}` when a DIFFERENT
    row's Zoom probes this row's own pure defaults -- neither `look` nor `intensity` is a key this
    addon reads, so that probe harmlessly falls through to 0 zones, exactly the "Réinitialiser"
    target."""
    values: dict[str, float] = {"dilation": 0.5, "feather": 0.3, "variant": 0.0}
    for index in range(_MAX_ZONES):
        prefix = f"zone_{index}_"
        values[f"{prefix}mask_point_count"] = 0.0
        for vertex in range(_MAX_MASK_VERTICES):
            values[f"{prefix}mask_point_{vertex:02d}_x"] = 0.5
            values[f"{prefix}mask_point_{vertex:02d}_y"] = 0.5
    for key, default in values.items():
        value = params.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            value = default
        values[key] = float(value)
    return values


def _zone_parameter_descriptions(index: int) -> tuple[ParameterDescription, ...]:
    """One zone's 65 vertex parameters, generated rather than hand-written (same precedent as
    `light.py`'s/`color_splash.py`'s own `_mask_parameter_descriptions`). All `transient=True` (see
    module docstring) and hidden from the plain slider list by `ZoomOverlay.tsx`'s existing
    `isMaskParameter` filter (matches on the `mask_` infix, unaware of which addon owns it)."""
    prefix = f"zone_{index}_"
    descriptions = [
        ParameterDescription(
            identifier=f"{prefix}mask_point_count", label=f"Zone {index + 1} — nombre de sommets",
            kind="numeric_slider", default=0.0, zoom_only=True, transient=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=float(_MAX_MASK_VERTICES), step=1.0),
        ),
    ]
    for vertex in range(_MAX_MASK_VERTICES):
        for axis in ("x", "y"):
            descriptions.append(ParameterDescription(
                identifier=f"{prefix}mask_point_{vertex:02d}_{axis}",
                label=f"Zone {index + 1} — sommet {vertex} ({axis})",
                kind="numeric_slider", default=0.5, zoom_only=True, transient=True,
                constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.001),
            ))
    return tuple(descriptions)


ADDON_DESCRIPTION = AddonSubmission(
    identifier="object_removal",
    label="Suppression d'objets",
    category="object_removal",
    thumbnail_presets=(
        ThumbnailPreset(identifier="neutral", label="Neutre", neutral=True),
    ),
    processing_function=remove_objects,
    resolve_zoom_values=resolve_zoom_values,
    parameter_descriptions=(
        ParameterDescription(
            identifier="dilation", label="Marge", kind="numeric_slider", default=0.5, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=3.0, step=0.1),
        ),
        ParameterDescription(
            identifier="feather", label="Fondu", kind="numeric_slider", default=0.3, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=0.1),
        ),
        ParameterDescription(
            identifier="variant", label="Proposition", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=999.0, step=1.0),
        ),
        *[description for index in range(_MAX_ZONES) for description in _zone_parameter_descriptions(index)],
    ),
    overlay_descriptions=(),
)
