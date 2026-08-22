# LumaFlow v1.0 (2026-08-07)
# PipelineStateTracker : suivi de validite par etape et recalcul incremental
# du pipeline a partir du premier step invalide (cache par identifiant de step).
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy

from lumaflow.engine.image_session import ImageSession
from lumaflow.engine.pipeline import ExecutionResult, Pipeline, PipelineEngine


class StepValidityState(Enum):
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class InvalidationEvent:
    step_identifier: str
    position: int


class PipelineStateTracker:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self._validity: dict[str, StepValidityState] = {
            s.identifier: StepValidityState.INVALID for s in pipeline._steps
        }
        self._cache: dict[str, numpy.ndarray] = {}

    def validity(self, step_identifier: str) -> StepValidityState:
        return self._validity[step_identifier]

    def validity_map(self) -> dict[str, StepValidityState]:
        return dict(self._validity)

    def invalidate(self, step_identifier: str) -> InvalidationEvent:
        position = next(
            (i for i, s in enumerate(self.pipeline._steps) if s.identifier == step_identifier),
            None,
        )
        if position is None:
            raise ValueError(f"Step identifier '{step_identifier}' not found in pipeline.")
        for i, s in enumerate(self.pipeline._steps):
            if i >= position:
                self._validity[s.identifier] = StepValidityState.INVALID
        return InvalidationEvent(step_identifier, position)

    def recompute(self, source: numpy.ndarray) -> ExecutionResult:
        if (
            source is None
            or not isinstance(source, numpy.ndarray)
            or source.dtype != numpy.uint8
            or source.ndim != 3
            or source.shape[2] != 3
        ):
            raise ValueError("Source image must be a (H,W,3) uint8 NumPy array.")

        K = next(
            (
                i
                for i, s in enumerate(self.pipeline._steps)
                if self._validity[s.identifier] is StepValidityState.INVALID
            ),
            None,
        )

        if K is None:
            if self.pipeline._steps:
                return ExecutionResult(
                    final=self._cache[self.pipeline._steps[-1].identifier],
                    outputs=dict(self._cache),
                    error=None,
                )
            return ExecutionResult(final=source, outputs={}, error=None)

        seed = source if K == 0 else self._cache[self.pipeline._steps[K - 1].identifier]
        result = PipelineEngine().run(self.pipeline, seed, start_index=K)

        if result.error is not None:
            return result

        merged: dict[str, numpy.ndarray] = {
            s.identifier: self._cache[s.identifier]
            for i, s in enumerate(self.pipeline._steps)
            if i < K
        }
        merged.update(result.outputs)
        self._cache = merged

        for s in self.pipeline._steps:
            self._validity[s.identifier] = StepValidityState.VALID

        return ExecutionResult(final=result.final, outputs=merged, error=None)

    def recompute_on_session(self, session: ImageSession) -> ExecutionResult:
        result = self.recompute(session.original)
        if result.error is None:
            session.replace_active(result.final)
        return result
