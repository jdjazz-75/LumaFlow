# LumaFlow v1.0 (2026-08-07)
# Teste la vérification de compatibilité bloquante et l'application de pipeline au niveau moteur
# (check_compatibility/apply_recipe_pipeline) : exécution sur données d'origine (pas actives),
# sorties par étape, et rapport d'étapes incompatibles/en échec sans altérer la session.

from __future__ import annotations

import numpy

from lumaflow.engine.compatibility import (
    ApplicationResult,
    CompatibilityIssue,
    CompatibilityReport,
    apply_recipe_pipeline,
    check_compatibility,
)
from lumaflow.engine.image_session import ImageSession, ImageSource
from lumaflow.engine.pipeline import Pipeline, PipelineStep


def _src(val: int = 10, height: int = 8, width: int = 8) -> numpy.ndarray:
    return numpy.full((height, width, 3), val, dtype=numpy.uint8)


def _session(val: int = 10, height: int = 8, width: int = 8) -> ImageSession:
    pixels = _src(val, height, width)
    source = ImageSource(
        identifier="test-id",
        path=None,
        name="test",
        width=width,
        height=height,
        image_format="PNG",
    )
    return ImageSession.create(pixels=pixels, source=source)


class AddStep(PipelineStep):
    def __init__(self, k: int, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._k = k

    def apply(self, image: numpy.ndarray) -> numpy.ndarray:
        return numpy.clip(image.astype(numpy.int32) + self._k, 0, 255).astype(numpy.uint8)


class FailStep(PipelineStep):
    def apply(self, image: numpy.ndarray) -> numpy.ndarray:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# US1 — compatibility-gated apply
# ---------------------------------------------------------------------------


def test_compatible_pipeline_executes_and_updates_session():
    pipeline = Pipeline()
    pipeline.add_step(PipelineStep(identifier="crop"))
    session = _session()

    result = apply_recipe_pipeline(pipeline, session)

    assert result.succeeded is True
    assert numpy.array_equal(session.pixels, result.execution.final)


def test_rules_none_always_compatible():
    pipeline = Pipeline()
    pipeline.add_step(PipelineStep(identifier="crop"))
    report = check_compatibility(pipeline, (8, 8, 3), rules=None)
    assert report.compatible is True


def test_apply_recipe_pipeline_uses_original_not_active():
    pipeline = Pipeline()
    pipeline.add_step(AddStep(k=5, identifier="brighten"))
    session = _session(val=10)
    original_snapshot = session.original.copy()

    session.replace_active(_src(val=200))

    result = apply_recipe_pipeline(pipeline, session)

    expected = numpy.clip(original_snapshot.astype(numpy.int32) + 5, 0, 255).astype(numpy.uint8)
    assert numpy.array_equal(result.execution.final, expected)


# ---------------------------------------------------------------------------
# US2 — per-step output data available in workflow order
# ---------------------------------------------------------------------------


def test_successful_application_outputs_per_step_data():
    pipeline = Pipeline()
    pipeline.add_step(PipelineStep(identifier="neutral"))
    pipeline.add_step(AddStep(k=10, identifier="brighten"))
    session = _session(val=10)

    result = apply_recipe_pipeline(pipeline, session)

    assert list(result.execution.outputs.keys()) == ["neutral", "brighten"]
    assert numpy.array_equal(result.execution.outputs["neutral"], _src(val=10))
    assert numpy.array_equal(result.execution.outputs["brighten"], _src(val=20))


# ---------------------------------------------------------------------------
# US3 — incompatible recipe operations handled gracefully
# ---------------------------------------------------------------------------


def _reject_crop_if_short(step: PipelineStep, shape: tuple[int, int, int]) -> str | None:
    if step.identifier == "crop" and shape[0] < 50:
        return "image too short for crop"
    return None


def test_incompatible_step_reported_by_name():
    pipeline = Pipeline()
    pipeline.add_step(PipelineStep(identifier="crop"))
    session = _session(height=10, width=10)

    result = apply_recipe_pipeline(pipeline, session, rules=[_reject_crop_if_short])

    assert result.compatibility.issues == [
        CompatibilityIssue(step_identifier="crop", reason="image too short for crop")
    ]
    assert result.execution is None


def test_incompatibility_leaves_session_untouched():
    pipeline = Pipeline()
    pipeline.add_step(PipelineStep(identifier="crop"))
    session = _session(height=10, width=10)
    snapshot = session.pixels.copy()

    apply_recipe_pipeline(pipeline, session, rules=[_reject_crop_if_short])

    assert numpy.array_equal(session.pixels, snapshot)


def test_partial_incompatibility_names_only_the_bad_step():
    pipeline = Pipeline()
    pipeline.add_step(PipelineStep(identifier="crop"))
    pipeline.add_step(PipelineStep(identifier="exposure"))
    session = _session(height=10, width=10)

    result = apply_recipe_pipeline(pipeline, session, rules=[_reject_crop_if_short])

    identifiers = [issue.step_identifier for issue in result.compatibility.issues]
    assert identifiers == ["crop"]


def test_execution_failure_leaves_session_untouched():
    pipeline = Pipeline()
    pipeline.add_step(FailStep(identifier="broken"))
    session = _session()
    original_snapshot = session.original.copy()
    active_snapshot = session.active.copy()

    result = apply_recipe_pipeline(pipeline, session)

    assert result.execution.error is not None
    assert numpy.array_equal(session.original, original_snapshot)
    assert numpy.array_equal(session.active, active_snapshot)


def test_no_crash_on_incompatible_or_failed():
    pipeline_incompatible = Pipeline()
    pipeline_incompatible.add_step(PipelineStep(identifier="crop"))
    session_a = _session(height=10, width=10)
    result_a = apply_recipe_pipeline(pipeline_incompatible, session_a, rules=[_reject_crop_if_short])
    assert isinstance(result_a, ApplicationResult)

    pipeline_failing = Pipeline()
    pipeline_failing.add_step(FailStep(identifier="broken"))
    session_b = _session()
    result_b = apply_recipe_pipeline(pipeline_failing, session_b)
    assert isinstance(result_b, ApplicationResult)
