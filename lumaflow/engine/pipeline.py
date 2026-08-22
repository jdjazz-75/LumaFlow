# LumaFlow v1.0 (2026-08-07)
# Types de base du pipeline de traitement : PipelineStep, Pipeline et PipelineEngine
# qui execute sequentiellement les steps sur une image et capture les erreurs par step.
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TYPE_CHECKING

import numpy

from lumaflow.engine.errors import StepError

if TYPE_CHECKING:
    from lumaflow.engine.image_session import ImageSession


@dataclass
class StepParameters:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineStep:
    identifier: str = field(default_factory=lambda: uuid.uuid4().hex)
    selected: bool = False
    parameters: StepParameters = field(default_factory=StepParameters)
    # Callable inline (pas importe du contrat addon) pour eviter une dependance
    # cross-domain ; lie uniquement par app.py, a la construction du pipeline.
    # None preserve le comportement d'identite preexistant.
    processor: Optional[Callable[[numpy.ndarray, dict[str, Any]], numpy.ndarray]] = None

    def apply(self, image: numpy.ndarray) -> numpy.ndarray:
        return self.processor(image, self.parameters.values) if self.processor is not None else image


@dataclass
class ExecutionResult:
    final: numpy.ndarray | None
    outputs: dict[str, numpy.ndarray] = field(default_factory=dict)
    error: StepError | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class Pipeline:
    def __init__(self) -> None:
        self._steps: list[PipelineStep] = []

    def add_step(self, step: PipelineStep) -> None:
        for existing in self._steps:
            if existing.identifier == step.identifier:
                raise ValueError(
                    f"Step identifier '{step.identifier}' is already registered in this pipeline."
                )
        self._steps.append(step)

    def execute(self, image: numpy.ndarray) -> numpy.ndarray:
        result = PipelineEngine().run(self, image)
        if result.error is not None:
            raise result.error
        return result.final


class PipelineEngine:
    def run(self, pipeline: Pipeline, source: numpy.ndarray, start_index: int = 0) -> ExecutionResult:
        if (
            source is None
            or not isinstance(source, numpy.ndarray)
            or source.dtype != numpy.uint8
            or source.ndim != 3
            or source.shape[2] != 3
        ):
            raise ValueError("Source image must be a (H,W,3) uint8 NumPy array.")

        outputs: dict[str, numpy.ndarray] = {}
        out = source
        for i, step in enumerate(pipeline._steps[start_index:], start=start_index):
            try:
                out = step.apply(out)
            except Exception as exc:
                step_error = StepError(
                    step_identifier=step.identifier,
                    step_index=i,
                    detail=str(exc),
                    cause=exc,
                )
                return ExecutionResult(final=None, outputs=outputs, error=step_error)
            outputs[step.identifier] = out

        return ExecutionResult(final=out, outputs=outputs, error=None)

    def apply_to_session(self, pipeline: Pipeline, session: ImageSession) -> ExecutionResult:
        result = self.run(pipeline, session.original)
        if result.error is None:
            session.replace_active(result.final)
        return result
