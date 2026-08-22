# LumaFlow v1.0 (2026-08-07)
# Teste PipelineEngine.run/apply_to_session : chaînage cumulatif non commutatif, identification de
# l'étape en échec (position et intermédiaires partiels préservés), sorties par étape accessibles,
# pont d'exécution des addons via PipelineStep.processor, et traversée d'une session d'origine RAW.

from __future__ import annotations

import numpy
import pytest

from lumaflow.engine.pipeline import ExecutionResult, Pipeline, PipelineEngine, PipelineStep
from lumaflow.engine.image_session import ImageSession, ImageSource


# ---------------------------------------------------------------------------
# Shared helpers and local test-only step subclasses
# ---------------------------------------------------------------------------

def _src(val: int = 10) -> numpy.ndarray:
    return numpy.full((8, 8, 3), val, dtype=numpy.uint8)


def _session(val: int = 10) -> ImageSession:
    pixels = _src(val)
    source = ImageSource(
        identifier="test-id",
        path=None,
        name="test",
        width=8,
        height=8,
        image_format="PNG",
    )
    return ImageSession.create(pixels=pixels, source=source)


class AddStep(PipelineStep):
    """Adds a constant k to every pixel (clipped to uint8). Non-commutative with MulStep."""

    def __init__(self, k: int, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._k = k

    def apply(self, image: numpy.ndarray) -> numpy.ndarray:
        return numpy.clip(image.astype(numpy.int32) + self._k, 0, 255).astype(numpy.uint8)


class MulStep(PipelineStep):
    """Multiplies every pixel by factor (clipped to uint8). Non-commutative with AddStep."""

    def __init__(self, factor: int, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._factor = factor

    def apply(self, image: numpy.ndarray) -> numpy.ndarray:
        return numpy.clip(image.astype(numpy.int32) * self._factor, 0, 255).astype(numpy.uint8)


class FailStep(PipelineStep):
    """Always raises RuntimeError("boom")."""

    def apply(self, image: numpy.ndarray) -> numpy.ndarray:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# US1 — Cumulative Transformations via Step Chaining
# ---------------------------------------------------------------------------

def test_forward_order_differs_from_reverse():
    # add+50 then mul×2 ≠ mul×2 then add+50 for source pixel=10
    source = _src(10)
    fwd = Pipeline()
    fwd.add_step(AddStep(k=50, identifier="add"))
    fwd.add_step(MulStep(factor=2, identifier="mul"))

    rev = Pipeline()
    rev.add_step(MulStep(factor=2, identifier="mul"))
    rev.add_step(AddStep(k=50, identifier="add"))

    engine = PipelineEngine()
    fwd_result = engine.run(fwd, source)
    rev_result = engine.run(rev, source)

    assert fwd_result.succeeded
    assert rev_result.succeeded
    assert not numpy.array_equal(fwd_result.final, rev_result.final)


def test_single_step_equals_direct_application():
    source = _src(20)
    step = AddStep(k=30, identifier="s1")
    pipeline = Pipeline()
    pipeline.add_step(step)
    result = PipelineEngine().run(pipeline, source)
    assert result.succeeded
    assert numpy.array_equal(result.final, step.apply(source))


def test_empty_pipeline_returns_source():
    source = _src(42)
    result = PipelineEngine().run(Pipeline(), source)
    assert result.succeeded
    assert numpy.array_equal(result.final, source)
    assert result.outputs == {}


def test_chaining_each_step_gets_previous_output():
    source = _src(0)
    pipeline = Pipeline()
    pipeline.add_step(AddStep(k=10, identifier="s1"))
    pipeline.add_step(AddStep(k=20, identifier="s2"))
    result = PipelineEngine().run(pipeline, source)
    assert result.succeeded
    # s1: 0+10=10; s2: 10+20=30
    assert numpy.array_equal(result.outputs["s1"], numpy.full((8, 8, 3), 10, dtype=numpy.uint8))
    assert numpy.array_equal(result.outputs["s2"], numpy.full((8, 8, 3), 30, dtype=numpy.uint8))


def test_pipeline_execute_neutral_delegates_unchanged():
    source = numpy.full((8, 8, 3), 77, dtype=numpy.uint8)
    pipeline = Pipeline()
    for _ in range(6):
        pipeline.add_step(PipelineStep())
    out = pipeline.execute(source)
    assert numpy.array_equal(out, source)


# ---------------------------------------------------------------------------
# US2 — Step Error Identification Without Data Loss
# ---------------------------------------------------------------------------

def test_failing_step_identified_at_first_position():
    source = _src(5)
    pipeline = Pipeline()
    pipeline.add_step(FailStep(identifier="first"))
    result = PipelineEngine().run(pipeline, source)
    assert not result.succeeded
    assert result.error.step_identifier == "first"
    assert result.error.step_index == 0


def test_failing_step_identified_at_middle_position():
    source = _src(5)
    pipeline = Pipeline()
    pipeline.add_step(AddStep(k=1, identifier="ok_before"))
    pipeline.add_step(FailStep(identifier="bad_step"))
    pipeline.add_step(AddStep(k=1, identifier="ok_after"))
    result = PipelineEngine().run(pipeline, source)
    assert not result.succeeded
    assert result.error.step_identifier == "bad_step"
    assert result.error.step_index == 1


def test_failing_step_identified_at_last_position():
    source = _src(5)
    pipeline = Pipeline()
    pipeline.add_step(AddStep(k=1, identifier="ok1"))
    pipeline.add_step(AddStep(k=1, identifier="ok2"))
    pipeline.add_step(FailStep(identifier="last_fail"))
    result = PipelineEngine().run(pipeline, source)
    assert not result.succeeded
    assert result.error.step_identifier == "last_fail"
    assert result.error.step_index == 2


def test_halt_partial_intermediates_accessible():
    source = _src(5)
    pipeline = Pipeline()
    pipeline.add_step(AddStep(k=1, identifier="ok_before"))
    pipeline.add_step(FailStep(identifier="bad_step"))
    pipeline.add_step(AddStep(k=1, identifier="ok_after"))
    result = PipelineEngine().run(pipeline, source)
    assert not result.succeeded
    assert "ok_before" in result.outputs
    assert "bad_step" not in result.outputs
    assert "ok_after" not in result.outputs


def test_source_intact_after_failure_via_apply_to_session():
    session = _session(10)
    snapshot = session.original.copy()
    pipeline = Pipeline()
    pipeline.add_step(FailStep(identifier="fail"))
    result = PipelineEngine().apply_to_session(pipeline, session)
    assert not result.succeeded
    assert numpy.array_equal(session.original, snapshot)
    assert numpy.array_equal(session.active, snapshot)


def test_success_writes_final_to_active():
    session = _session(10)
    original_snapshot = session.original.copy()
    pipeline = Pipeline()
    pipeline.add_step(AddStep(k=5, identifier="s1"))
    result = PipelineEngine().apply_to_session(pipeline, session)
    assert result.succeeded
    assert numpy.array_equal(session.active, result.final)
    assert numpy.array_equal(session.original, original_snapshot)


# ---------------------------------------------------------------------------
# US3 — Intermediate Step Outputs Available for Inspection
# ---------------------------------------------------------------------------

def test_per_step_output_accessible_by_identifier():
    source = _src(0)
    pipeline = Pipeline()
    pipeline.add_step(AddStep(k=10, identifier="s1"))
    pipeline.add_step(AddStep(k=20, identifier="s2"))
    pipeline.add_step(AddStep(k=5, identifier="s3"))
    result = PipelineEngine().run(pipeline, source)
    assert result.succeeded
    # cumulative: s1=10, s2=30, s3=35
    assert numpy.array_equal(result.outputs["s1"], numpy.full((8, 8, 3), 10, dtype=numpy.uint8))
    assert numpy.array_equal(result.outputs["s2"], numpy.full((8, 8, 3), 30, dtype=numpy.uint8))
    assert numpy.array_equal(result.outputs["s3"], numpy.full((8, 8, 3), 35, dtype=numpy.uint8))


def test_per_step_output_preserves_execution_order():
    source = _src(0)
    pipeline = Pipeline()
    for label in ("s1", "s2", "s3"):
        pipeline.add_step(AddStep(k=1, identifier=label))
    result = PipelineEngine().run(pipeline, source)
    assert result.succeeded
    assert list(result.outputs.keys()) == ["s1", "s2", "s3"]


def test_partial_outputs_after_failure():
    source = _src(0)
    pipeline = Pipeline()
    pipeline.add_step(AddStep(k=1, identifier="ok1"))
    pipeline.add_step(FailStep(identifier="bad"))
    pipeline.add_step(AddStep(k=1, identifier="ok2"))
    result = PipelineEngine().run(pipeline, source)
    assert not result.succeeded
    assert len(result.outputs) == 1
    assert "ok1" in result.outputs


def test_final_equals_last_step_output():
    source = _src(0)
    pipeline = Pipeline()
    for label in ("s1", "s2", "s3"):
        pipeline.add_step(AddStep(k=5, identifier=label))
    result = PipelineEngine().run(pipeline, source)
    assert result.succeeded
    assert numpy.array_equal(result.final, result.outputs["s3"])


# ---------------------------------------------------------------------------
# Addon-execution bridge (feature 040) — PipelineStep.processor
# ---------------------------------------------------------------------------

def test_processor_output_used_by_apply_and_run():
    def double(image: numpy.ndarray, params: dict) -> numpy.ndarray:
        return numpy.clip(image.astype(numpy.int32) * 2, 0, 255).astype(numpy.uint8)

    source = _src(10)
    step = PipelineStep(identifier="s1", processor=double)
    assert numpy.array_equal(step.apply(source), numpy.full((8, 8, 3), 20, dtype=numpy.uint8))

    pipeline = Pipeline()
    pipeline.add_step(step)
    result = PipelineEngine().run(pipeline, source)
    assert result.succeeded
    assert numpy.array_equal(result.final, numpy.full((8, 8, 3), 20, dtype=numpy.uint8))


def test_processor_receives_own_parameters_values():
    received = {}

    def capture(image: numpy.ndarray, params: dict) -> numpy.ndarray:
        received.update(params)
        return image

    from lumaflow.engine.pipeline import StepParameters

    step = PipelineStep(
        identifier="s1", processor=capture, parameters=StepParameters(values={"angle": 12.5})
    )
    step.apply(_src(10))
    assert received == {"angle": 12.5}


def test_processor_unset_still_noops():
    source = _src(33)
    step = PipelineStep(identifier="s1")
    assert step.processor is None
    assert numpy.array_equal(step.apply(source), source)

    pipeline = Pipeline()
    pipeline.add_step(step)
    result = PipelineEngine().run(pipeline, source)
    assert result.succeeded
    assert numpy.array_equal(result.final, source)


def test_succeeded_property():
    source = _src(10)

    ok_pipeline = Pipeline()
    ok_pipeline.add_step(AddStep(k=1, identifier="ok"))
    assert PipelineEngine().run(ok_pipeline, source).succeeded is True

    fail_pipeline = Pipeline()
    fail_pipeline.add_step(FailStep(identifier="fail"))
    assert PipelineEngine().run(fail_pipeline, source).succeeded is False


# ---------------------------------------------------------------------------
# US3 (052) — a RAW-origin session traverses the existing neutral pipeline
# exactly like a JPEG/PNG-origin session (skipif no decodable fixture).
# ---------------------------------------------------------------------------

from conftest import decodable_raw_fixtures

_FIRST_DECODABLE_RAW_FIXTURE = next(iter(decodable_raw_fixtures().values()), None)


@pytest.mark.skipif(
    _FIRST_DECODABLE_RAW_FIXTURE is None,
    reason="No decodable RAW fixture in tests/fixtures/raw/ (see README.md there)",
)
def test_neutral_pipeline_leaves_raw_origin_session_active_image_unchanged():
    from lumaflow.engine.image_io import load_image

    session = load_image(_FIRST_DECODABLE_RAW_FIXTURE)
    pipeline = Pipeline()
    for _ in range(3):
        pipeline.add_step(PipelineStep())
    result = PipelineEngine().run(pipeline, session.active)
    assert result.succeeded
    assert numpy.array_equal(result.final, session.active)
