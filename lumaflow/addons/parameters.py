# LumaFlow v1.0 (2026-08-07)
# Descriptions declaratives des parametres UI et overlays d'addon (sliders, hue_range),
# leur validation et leur conversion en ZoomParameterDeclaration.
"""Declarative UI parameter/overlay descriptions for addons — no Qt, no pipeline engine, no
persistence module import (FR-020-07).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from lumaflow.addons.contract import ZoomParameterDeclaration

# Public types: NumericSliderConstraints, HueRangeConstraints, ParameterDescription,
# OverlayDescription, DescriptionValidationIssue, DescriptionValidationReport,
# validate_parameter_description, validate_overlay_description, parameter_to_zoom_declaration,
# overlay_to_zoom_declaration


@dataclass(frozen=True)
class NumericSliderConstraints:
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None


@dataclass(frozen=True)
class HueRangeConstraints:
    """Constraints for kind="hue_range" -- a circular hue-selection control (center +
    feather/adoucissement), first introduced by the Color Splash addon (feature 046). Distinct
    from NumericSliderConstraints because a hue center is cyclic (0-360, no true min/max) and the
    control groups two underlying scalar parameters (identified as
    f"{ParameterDescription.identifier}_hue_center" / f"..._feather") rather than one.
    """

    hue_minimum: Optional[float] = None
    hue_maximum: Optional[float] = None
    hue_default: Optional[float] = None
    feather_minimum: Optional[float] = None
    feather_maximum: Optional[float] = None
    feather_default: Optional[float] = None


@dataclass(frozen=True)
class ParameterDescription:
    identifier: Optional[str] = None
    label: Optional[str] = None
    kind: Optional[str] = None
    default: Optional[float] = None
    constraints: Optional[Union[NumericSliderConstraints, HueRangeConstraints]] = None
    zoom_only: bool = False


@dataclass(frozen=True)
class OverlayDescription:
    kind: Optional[str] = None
    label: Optional[str] = None
    default_active: Optional[bool] = None
    graphical_parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DescriptionValidationIssue:
    field: str
    reason: str


@dataclass(frozen=True)
class DescriptionValidationReport:
    issues: tuple[DescriptionValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues


def validate_parameter_description(description: ParameterDescription) -> DescriptionValidationReport:
    issues: list[DescriptionValidationIssue] = []

    for name in ("identifier", "label", "kind", "default", "constraints"):
        if getattr(description, name) is None:
            issues.append(DescriptionValidationIssue(field=name, reason="missing"))

    if description.kind == "numeric_slider" and description.constraints is not None:
        constraints = description.constraints
        for sub_name in ("minimum", "maximum", "step"):
            if getattr(constraints, sub_name) is None:
                issues.append(
                    DescriptionValidationIssue(field=f"constraints.{sub_name}", reason="missing")
                )

        min_greater_than_max = False
        if constraints.minimum is not None and constraints.maximum is not None:
            if constraints.minimum > constraints.maximum:
                min_greater_than_max = True
                issues.append(
                    DescriptionValidationIssue(field="constraints", reason="min_greater_than_max")
                )

        if (
            not min_greater_than_max
            and description.default is not None
            and constraints.minimum is not None
            and constraints.maximum is not None
            and not (constraints.minimum <= description.default <= constraints.maximum)
        ):
            issues.append(
                DescriptionValidationIssue(field="default", reason="default_out_of_range")
            )

    if description.kind == "hue_range" and description.constraints is not None:
        constraints = description.constraints
        for sub_name in (
            "hue_minimum", "hue_maximum", "hue_default",
            "feather_minimum", "feather_maximum", "feather_default",
        ):
            if getattr(constraints, sub_name, None) is None:
                issues.append(
                    DescriptionValidationIssue(field=f"constraints.{sub_name}", reason="missing")
                )

        hue_bounds_valid = (
            constraints.hue_minimum is not None
            and constraints.hue_maximum is not None
            and constraints.hue_minimum <= constraints.hue_maximum
        )
        if not hue_bounds_valid and constraints.hue_minimum is not None and constraints.hue_maximum is not None:
            issues.append(DescriptionValidationIssue(field="constraints", reason="hue_min_greater_than_max"))
        if (
            hue_bounds_valid
            and constraints.hue_default is not None
            and not (constraints.hue_minimum <= constraints.hue_default <= constraints.hue_maximum)
        ):
            issues.append(DescriptionValidationIssue(field="hue_default", reason="default_out_of_range"))

        feather_bounds_valid = (
            constraints.feather_minimum is not None
            and constraints.feather_maximum is not None
            and constraints.feather_minimum <= constraints.feather_maximum
        )
        if (
            not feather_bounds_valid
            and constraints.feather_minimum is not None
            and constraints.feather_maximum is not None
        ):
            issues.append(
                DescriptionValidationIssue(field="constraints", reason="feather_min_greater_than_max")
            )
        if (
            feather_bounds_valid
            and constraints.feather_default is not None
            and not (constraints.feather_minimum <= constraints.feather_default <= constraints.feather_maximum)
        ):
            issues.append(DescriptionValidationIssue(field="feather_default", reason="default_out_of_range"))

    return DescriptionValidationReport(issues=tuple(issues))


def validate_overlay_description(overlay: OverlayDescription) -> DescriptionValidationReport:
    issues: list[DescriptionValidationIssue] = []

    for name in ("kind", "label", "default_active"):
        if getattr(overlay, name) is None:
            issues.append(DescriptionValidationIssue(field=name, reason="missing"))

    return DescriptionValidationReport(issues=tuple(issues))


def parameter_to_zoom_declaration(description: ParameterDescription) -> ZoomParameterDeclaration:
    constraints: dict[str, Any] = {}
    if description.kind == "hue_range" and isinstance(description.constraints, HueRangeConstraints):
        constraints["hue_minimum"] = description.constraints.hue_minimum
        constraints["hue_maximum"] = description.constraints.hue_maximum
        constraints["hue_default"] = description.constraints.hue_default
        constraints["feather_minimum"] = description.constraints.feather_minimum
        constraints["feather_maximum"] = description.constraints.feather_maximum
        constraints["feather_default"] = description.constraints.feather_default
    elif description.constraints is not None:
        constraints["minimum"] = description.constraints.minimum
        constraints["maximum"] = description.constraints.maximum
        constraints["step"] = description.constraints.step
    constraints["default"] = description.default

    return ZoomParameterDeclaration(
        identifier=description.identifier,
        label=description.label,
        kind=description.kind,
        constraints=constraints,
        zoom_only=description.zoom_only,
    )


def overlay_to_zoom_declaration(identifier: str, overlay: OverlayDescription) -> ZoomParameterDeclaration:
    constraints: dict[str, Any] = {
        "default_active": overlay.default_active,
        "graphical_parameters": overlay.graphical_parameters,
    }

    return ZoomParameterDeclaration(
        identifier=identifier,
        label=overlay.label,
        kind=overlay.kind,
        constraints=constraints,
    )
