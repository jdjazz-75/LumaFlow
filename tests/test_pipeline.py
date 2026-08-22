# LumaFlow v1.0 (2026-08-07)
# Teste le moteur de pipeline générique (Pipeline/PipelineStep) : exécution ordonnée sans effet de
# bord, validation des entrées, identifiants stables et distincts, et conteneur de paramètres.

from __future__ import annotations

import numpy
import pytest

from lumaflow.engine.pipeline import Pipeline, PipelineStep, StepParameters


# ---------------------------------------------------------------------------
# US1 — Ordered Workflow Execution Without Side Effects
# ---------------------------------------------------------------------------

def test_empty_pipeline_returns_source():
    source = numpy.zeros((8, 8, 3), dtype=numpy.uint8)
    out = Pipeline().execute(source)
    assert numpy.array_equal(out, source)


def test_six_neutral_steps_return_source():
    source = numpy.full((8, 8, 3), 42, dtype=numpy.uint8)
    pipeline = Pipeline()
    for _ in range(6):
        pipeline.add_step(PipelineStep())
    out = pipeline.execute(source)
    assert numpy.array_equal(out, source)


def test_execute_order_matches_registration():
    trace: list[str] = []

    class RecordingStep(PipelineStep):
        def apply(self, image: numpy.ndarray) -> numpy.ndarray:
            trace.append(self.identifier)
            return image

    pipeline = Pipeline()
    for label in ("first", "second", "third"):
        pipeline.add_step(RecordingStep(identifier=label))

    source = numpy.zeros((4, 4, 3), dtype=numpy.uint8)
    pipeline.execute(source)
    assert trace == ["first", "second", "third"]


def test_execute_none_source_raises():
    with pytest.raises(ValueError):
        Pipeline().execute(None)


def test_execute_invalid_shape_raises():
    with pytest.raises(ValueError):
        Pipeline().execute(numpy.zeros((4, 4), dtype=numpy.uint8))


# ---------------------------------------------------------------------------
# US2 — Each Step Has a Stable Identity and Parameters
# ---------------------------------------------------------------------------

def test_auto_identifiers_are_distinct():
    s1 = PipelineStep()
    s2 = PipelineStep()
    assert s1.identifier != s2.identifier


def test_identifier_stable_after_execution():
    step = PipelineStep()
    original_id = step.identifier
    pipeline = Pipeline()
    pipeline.add_step(step)
    source = numpy.zeros((4, 4, 3), dtype=numpy.uint8)
    pipeline.execute(source)
    assert step.identifier == original_id


def test_duplicate_identifier_rejected():
    pipeline = Pipeline()
    pipeline.add_step(PipelineStep(identifier="dup"))
    with pytest.raises(ValueError, match="dup"):
        pipeline.add_step(PipelineStep(identifier="dup"))


def test_selection_state_isolated():
    s1 = PipelineStep()
    s2 = PipelineStep()
    s1.selected = True
    assert s2.selected is False


def test_parameters_container_present_and_empty():
    step = PipelineStep()
    assert isinstance(step.parameters, StepParameters)
    assert step.parameters.values == {}
