# LumaFlow v1.0 (2026-08-07)
# Verifie la compatibilite d'un pipeline avec l'image cible avant application
# (check_compatibility, apply_recipe_pipeline).
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from lumaflow.engine.image_session import ImageSession
from lumaflow.engine.pipeline import ExecutionResult, Pipeline, PipelineEngine, PipelineStep

CompatibilityRule = Callable[[PipelineStep, tuple[int, int, int]], Optional[str]]


@dataclass(frozen=True)
class CompatibilityIssue:
    step_identifier: str
    reason: str


@dataclass(frozen=True)
class CompatibilityReport:
    issues: list[CompatibilityIssue] = field(default_factory=list)

    @property
    def compatible(self) -> bool:
        return not self.issues


def check_compatibility(
    pipeline: Pipeline,
    target_shape: tuple[int, int, int],
    rules: Optional[list[CompatibilityRule]] = None,
) -> CompatibilityReport:
    if not rules:
        return CompatibilityReport()

    issues: list[CompatibilityIssue] = []
    for step in pipeline._steps:
        for rule in rules:
            reason = rule(step, target_shape)
            if reason is not None:
                issues.append(CompatibilityIssue(step_identifier=step.identifier, reason=reason))
    return CompatibilityReport(issues=issues)


@dataclass(frozen=True)
class ApplicationResult:
    compatibility: CompatibilityReport
    execution: Optional[ExecutionResult]

    @property
    def succeeded(self) -> bool:
        return self.compatibility.compatible and self.execution is not None and self.execution.succeeded


def apply_recipe_pipeline(
    pipeline: Pipeline,
    session: ImageSession,
    rules: Optional[list[CompatibilityRule]] = None,
) -> ApplicationResult:
    report = check_compatibility(pipeline, session.original.shape, rules)
    if not report.compatible:
        return ApplicationResult(compatibility=report, execution=None)

    execution = PipelineEngine().apply_to_session(pipeline, session)
    return ApplicationResult(compatibility=report, execution=execution)
