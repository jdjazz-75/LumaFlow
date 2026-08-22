# LumaFlow v1.0 (2026-08-07)
# Decouverte, import dynamique, validation et indexation des addons (load_addons).
"""Addon discovery, validation, and indexing — no Qt, no pipeline engine, no persistence module
import.

`contract.py` (F-019) and `parameters.py` (F-020) are read-only dependencies, never modified.
"""

from __future__ import annotations

import importlib.util
import pathlib
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

from lumaflow.addons.contract import (
    AddonDescriptor,
    ProcessingFunction,
    ThumbnailPreset,
    validate_addon,
)
from lumaflow.addons.parameters import (
    OverlayDescription,
    ParameterDescription,
    overlay_to_zoom_declaration,
    parameter_to_zoom_declaration,
    validate_overlay_description,
    validate_parameter_description,
)

# Public types: DiscoveryLocation, AddonSubmission, AddonLoadIssueKind, AddonLoadIssue, LoadReport,
# load_addons


@dataclass(frozen=True)
class DiscoveryLocation:
    path: pathlib.Path


@dataclass(frozen=True)
class AddonSubmission:
    identifier: Optional[str] = None
    label: Optional[str] = None
    category: Optional[str] = None
    thumbnail_presets: Optional[tuple[ThumbnailPreset, ...]] = None
    processing_function: Optional[ProcessingFunction] = None
    parameter_descriptions: tuple[ParameterDescription, ...] = ()
    overlay_descriptions: tuple[OverlayDescription, ...] = ()
    resolve_zoom_values: Optional[Callable[[dict[str, Any]], dict[str, float]]] = None


class AddonLoadIssueKind(Enum):
    INVALID_ADDON = auto()
    DUPLICATE_IDENTIFIER = auto()
    LOAD_ABORTED = auto()


@dataclass(frozen=True)
class AddonLoadIssue:
    kind: AddonLoadIssueKind
    identifier: Optional[str]
    detail: str


@dataclass(frozen=True)
class LoadReport:
    index: dict[str, AddonDescriptor] = field(default_factory=dict)
    issues: tuple[AddonLoadIssue, ...] = ()
    aborted: bool = False

    @property
    def succeeded(self) -> bool:
        return not self.aborted


def _discover_candidate_files(directory: pathlib.Path) -> list[pathlib.Path]:
    try:
        candidates = [
            entry
            for entry in directory.iterdir()
            if entry.is_file() and entry.suffix == ".py" and not entry.name.startswith("_")
        ]
    except OSError:
        return []
    return sorted(candidates, key=lambda entry: entry.name)


def _import_module(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_submission(submission: AddonSubmission) -> tuple[Optional[AddonDescriptor], list[str]]:
    problems: list[str] = []

    for description in submission.parameter_descriptions:
        report = validate_parameter_description(description)
        for issue in report.issues:
            problems.append(f"parameter {issue.field}: {issue.reason}")

    for overlay in submission.overlay_descriptions:
        report = validate_overlay_description(overlay)
        for issue in report.issues:
            problems.append(f"overlay {issue.field}: {issue.reason}")

    if problems:
        return None, problems

    zoom_parameters = tuple(
        parameter_to_zoom_declaration(description) for description in submission.parameter_descriptions
    ) + tuple(
        overlay_to_zoom_declaration(f"overlay_{i}", overlay)
        for i, overlay in enumerate(submission.overlay_descriptions)
    )

    descriptor = AddonDescriptor(
        identifier=submission.identifier,
        label=submission.label,
        category=submission.category,
        thumbnail_presets=submission.thumbnail_presets,
        processing_function=submission.processing_function,
        zoom_parameters=zoom_parameters,
        resolve_zoom_values=submission.resolve_zoom_values,
    )

    report = validate_addon(descriptor)
    for issue in report.issues:
        problems.append(f"{issue.field}: {issue.reason}")

    if problems:
        return None, problems

    return descriptor, []


def load_addons(location: DiscoveryLocation, *, fail_fast: bool = False) -> LoadReport:
    issues: list[AddonLoadIssue] = []
    successes: list[tuple[str, AddonDescriptor]] = []

    for candidate_path in _discover_candidate_files(location.path):
        try:
            module = _import_module(candidate_path)
        except Exception as exc:
            issues.append(
                AddonLoadIssue(
                    kind=AddonLoadIssueKind.INVALID_ADDON,
                    identifier=None,
                    detail=f"{candidate_path.name}: import failed: {exc}",
                )
            )
            if fail_fast:
                issues.append(
                    AddonLoadIssue(
                        kind=AddonLoadIssueKind.LOAD_ABORTED,
                        identifier=None,
                        detail=f"Load aborted after {candidate_path.name} failed to import.",
                    )
                )
                return LoadReport(index={}, issues=tuple(issues), aborted=True)
            continue

        submission = getattr(module, "ADDON_DESCRIPTION", None)
        if submission is None:
            continue

        descriptor, problems = _validate_submission(submission)
        if descriptor is None:
            issues.append(
                AddonLoadIssue(
                    kind=AddonLoadIssueKind.INVALID_ADDON,
                    identifier=submission.identifier,
                    detail="; ".join(problems),
                )
            )
            if fail_fast:
                issues.append(
                    AddonLoadIssue(
                        kind=AddonLoadIssueKind.LOAD_ABORTED,
                        identifier=submission.identifier,
                        detail=f"Load aborted after '{submission.identifier}' failed validation.",
                    )
                )
                return LoadReport(index={}, issues=tuple(issues), aborted=True)
            continue

        successes.append((submission.identifier, descriptor))

    groups: dict[str, list[AddonDescriptor]] = {}
    for identifier, descriptor in successes:
        groups.setdefault(identifier, []).append(descriptor)

    index: dict[str, AddonDescriptor] = {}
    for identifier, descriptors in groups.items():
        if len(descriptors) == 1:
            index[identifier] = descriptors[0]
        else:
            issues.append(
                AddonLoadIssue(
                    kind=AddonLoadIssueKind.DUPLICATE_IDENTIFIER,
                    identifier=identifier,
                    detail=f"{len(descriptors)} addons declared identifier '{identifier}'.",
                )
            )

    return LoadReport(index=index, issues=tuple(issues), aborted=False)
