# LumaFlow v1.0 (2026-08-07)
# Definit le contrat declaratif d'un addon (AddonDescriptor, ThumbnailPreset,
# ZoomParameterDeclaration) et sa validation via validate_addon.
"""Declarative addon contract — the shape an addon must satisfy to be recognized by the core.

No Qt, no pipeline engine, no persistence module import (FR-019-09).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy

# Public types: ProcessingFunction, ThumbnailPreset, ZoomParameterDeclaration, AddonDescriptor,
# AddonValidationIssue, AddonValidationReport, validate_addon

ProcessingFunction = Callable[[numpy.ndarray, dict[str, Any]], numpy.ndarray]


@dataclass(frozen=True)
class ThumbnailPreset:
    identifier: str
    label: str
    neutral: bool = False
    preset_parameters: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ZoomParameterDeclaration:
    identifier: str
    label: str
    kind: str
    constraints: dict[str, Any] = field(default_factory=dict)
    zoom_only: bool = False
    # Session-local, non-portable value: edited in Zoom like any other parameter, but
    # deliberately NOT written into a saved recipe (build_recipe strips it, see
    # lumaflow/api/session.py) -- reloading the recipe therefore restores this parameter's
    # declared default. For image-specific geometry that means nothing on another photo, at a
    # granularity the pre-existing per-STEP exclusion (persistence/recipe.py's
    # EXCLUDED_STEP_IDENTIFIERS, all-or-nothing) cannot express: Color Splash's per-range
    # application zones must not travel, while the rest of its configuration must.
    transient: bool = False


@dataclass(frozen=True)
class AddonDescriptor:
    identifier: Optional[str] = None
    label: Optional[str] = None
    category: Optional[str] = None
    thumbnail_presets: Optional[tuple[ThumbnailPreset, ...]] = None
    processing_function: Optional[ProcessingFunction] = None
    zoom_parameters: Optional[tuple[ZoomParameterDeclaration, ...]] = None
    # Optional: given a step's current parameter values (e.g. {"look": ...,
    # "intensity": ...}), returns the EFFECTIVE absolute value of every zoom
    # parameter this addon declares -- an override present in the input wins,
    # otherwise the addon resolves its own "as calibrated" value (Zoom
    # overlay screen, 2026-07-22: lets the API seed sliders with what's
    # actually in effect, without knowing addon-internal grade tables).
    # None means "no addon-specific resolution" -- the caller falls back to
    # each ZoomParameterDeclaration's own generic declared default.
    resolve_zoom_values: Optional[Callable[[dict[str, Any]], dict[str, float]]] = None


@dataclass(frozen=True)
class AddonValidationIssue:
    field: str
    reason: str


@dataclass(frozen=True)
class AddonValidationReport:
    issues: tuple[AddonValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues


def validate_addon(descriptor: AddonDescriptor) -> AddonValidationReport:
    issues: list[AddonValidationIssue] = []

    for name in ("identifier", "label", "category"):
        value = getattr(descriptor, name)
        if value is None:
            issues.append(AddonValidationIssue(field=name, reason="missing"))
        elif not value.strip():
            issues.append(AddonValidationIssue(field=name, reason="empty"))

    if descriptor.thumbnail_presets is None:
        issues.append(AddonValidationIssue(field="thumbnail_presets", reason="missing"))
    elif len(descriptor.thumbnail_presets) == 0:
        issues.append(AddonValidationIssue(field="thumbnail_presets", reason="empty"))

    if descriptor.processing_function is None:
        issues.append(AddonValidationIssue(field="processing_function", reason="missing"))

    if descriptor.zoom_parameters is None:
        issues.append(AddonValidationIssue(field="zoom_parameters", reason="missing"))

    return AddonValidationReport(issues=tuple(issues))
