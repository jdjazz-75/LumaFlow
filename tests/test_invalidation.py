# LumaFlow v1.0 (2026-08-07)
# Teste PipelineStateTracker (invalidation.py) : recalcul incrémental identique à un recalcul
# complet, non-recalcul des étapes valides, propagation de l'invalidation en aval d'une étape
# modifiée, gestion de plusieurs invalidations, et observabilité de l'état de validité par étape.

from __future__ import annotations

import numpy
import pytest

from lumaflow.engine.pipeline import Pipeline, PipelineStep
from lumaflow.engine.invalidation import InvalidationEvent, PipelineStateTracker, StepValidityState
from lumaflow.engine.image_session import ImageSession, ImageSource


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _src(val: int = 0) -> numpy.ndarray:
    return numpy.full((4, 4, 3), val, dtype=numpy.uint8)


def _session(val: int = 10) -> ImageSession:
    pixels = _src(val)
    source = ImageSource(
        identifier="test-id",
        path=None,
        name="test",
        width=4,
        height=4,
        image_format="PNG",
    )
    return ImageSession.create(pixels=pixels, source=source)


class AddStep(PipelineStep):
    def __init__(self, k: int, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.k = k

    def apply(self, image: numpy.ndarray) -> numpy.ndarray:
        return numpy.clip(image.astype(numpy.int16) + self.k, 0, 255).astype(numpy.uint8)


class FailStep(PipelineStep):
    def apply(self, image: numpy.ndarray) -> numpy.ndarray:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# US1 — Coherent Result After Step Modification
# ---------------------------------------------------------------------------

def test_recompute_incremental_equals_fresh_full_run():
    src = _src(10)
    steps = [AddStep(1, identifier=f"s{i}") for i in range(4)]
    pipe = Pipeline()
    for s in steps:
        pipe.add_step(s)
    tracker = PipelineStateTracker(pipe)
    tracker.recompute(src)

    steps[2].k = 50
    tracker.invalidate("s2")
    incremental = tracker.recompute(src)

    ref_pipe = Pipeline()
    for i, k in enumerate([1, 1, 50, 1]):
        ref_pipe.add_step(AddStep(k, identifier=f"s{i}"))
    fresh = PipelineStateTracker(ref_pipe).recompute(src)

    assert incremental.succeeded
    assert numpy.array_equal(incremental.final, fresh.final)


def test_valid_steps_not_recomputed_only_suffix_called():
    calls: list[str] = []

    class CountingAdd(AddStep):
        def apply(self, image: numpy.ndarray) -> numpy.ndarray:
            calls.append(self.identifier)
            return super().apply(image)

    pipe = Pipeline()
    for i in range(4):
        pipe.add_step(CountingAdd(1, identifier=f"s{i}"))
    tracker = PipelineStateTracker(pipe)
    tracker.recompute(_src())
    calls.clear()

    tracker.invalidate("s2")
    tracker.recompute(_src())
    assert calls == ["s2", "s3"]


def test_all_valid_after_recompute_on_1_3_6_steps():
    for n in (1, 3, 6):
        pipe = Pipeline()
        for i in range(n):
            pipe.add_step(AddStep(1, identifier=f"s{i}"))
        tracker = PipelineStateTracker(pipe)
        tracker.recompute(_src())
        assert all(s is StepValidityState.VALID for s in tracker.validity_map().values())


def test_recompute_failure_leaves_validity_unchanged():
    pipe = Pipeline()
    pipe.add_step(FailStep(identifier="fail"))
    tracker = PipelineStateTracker(pipe)
    result = tracker.recompute(_src())
    assert result.error is not None
    assert tracker.validity_map()["fail"] is StepValidityState.INVALID


# ---------------------------------------------------------------------------
# US2 — Upstream Results Preserved After Modification
# ---------------------------------------------------------------------------

def test_invalidate_middle_step_upstream_valid_downstream_invalid():
    pipe = Pipeline()
    for i in range(6):
        pipe.add_step(AddStep(1, identifier=f"s{i}"))
    tracker = PipelineStateTracker(pipe)
    tracker.recompute(_src())

    tracker.invalidate("s3")
    vm = tracker.validity_map()
    assert all(vm[f"s{i}"] is StepValidityState.VALID for i in (0, 1, 2))
    assert all(vm[f"s{i}"] is StepValidityState.INVALID for i in (3, 4, 5))


def test_invalidate_first_step_all_invalid():
    pipe = Pipeline()
    for i in range(6):
        pipe.add_step(AddStep(1, identifier=f"s{i}"))
    tracker = PipelineStateTracker(pipe)
    tracker.recompute(_src())

    tracker.invalidate("s0")
    assert all(v is StepValidityState.INVALID for v in tracker.validity_map().values())


def test_invalidate_last_step_only_it_invalid():
    pipe = Pipeline()
    for i in range(6):
        pipe.add_step(AddStep(1, identifier=f"s{i}"))
    tracker = PipelineStateTracker(pipe)
    tracker.recompute(_src())

    tracker.invalidate("s5")
    vm = tracker.validity_map()
    assert all(vm[f"s{i}"] is StepValidityState.VALID for i in range(5))
    assert vm["s5"] is StepValidityState.INVALID


def test_two_modifications_earliest_governs():
    pipe = Pipeline()
    for i in range(4):
        pipe.add_step(AddStep(1, identifier=f"s{i}"))
    tracker = PipelineStateTracker(pipe)
    tracker.recompute(_src())

    tracker.invalidate("s3")
    tracker.invalidate("s1")
    vm = tracker.validity_map()
    assert vm["s0"] is StepValidityState.VALID
    assert all(vm[f"s{i}"] is StepValidityState.INVALID for i in (1, 2, 3))


def test_invalid_persists_until_recompute():
    pipe = Pipeline()
    for i in range(4):
        pipe.add_step(AddStep(1, identifier=f"s{i}"))
    tracker = PipelineStateTracker(pipe)
    tracker.recompute(_src())

    tracker.invalidate("s2")
    vm = tracker.validity_map()
    assert all(vm[f"s{i}"] is StepValidityState.INVALID for i in (2, 3))
    assert all(vm[f"s{i}"] is StepValidityState.VALID for i in (0, 1))


def test_recompute_on_session_source_intact_and_active_written():
    pipe = Pipeline()
    pipe.add_step(AddStep(5, identifier="s0"))
    tracker = PipelineStateTracker(pipe)

    session = _session(10)
    original_before = session.original.copy()
    result = tracker.recompute_on_session(session)

    assert result.succeeded
    assert numpy.array_equal(session.original, original_before)
    assert numpy.array_equal(session.active, tracker._cache["s0"])


# ---------------------------------------------------------------------------
# US3 — Invalidation State Is Observable for Verification
# ---------------------------------------------------------------------------

def test_validity_readable_before_any_recompute():
    pipe = Pipeline()
    for i in range(3):
        pipe.add_step(AddStep(1, identifier=f"s{i}"))
    tracker = PipelineStateTracker(pipe)
    assert all(s is StepValidityState.INVALID for s in tracker.validity_map().values())


def test_validity_map_returns_snapshot_not_reference():
    pipe = Pipeline()
    pipe.add_step(AddStep(1, identifier="s0"))
    tracker = PipelineStateTracker(pipe)

    snap = tracker.validity_map()
    snap["s0"] = StepValidityState.VALID  # mutate the snapshot
    assert tracker.validity_map()["s0"] is StepValidityState.INVALID


def test_per_step_validity_via_validity_method():
    pipe = Pipeline()
    for i in range(3):
        pipe.add_step(AddStep(1, identifier=f"s{i}"))
    tracker = PipelineStateTracker(pipe)
    tracker.recompute(_src())

    tracker.invalidate("s2")
    assert tracker.validity("s0") is StepValidityState.VALID
    assert tracker.validity("s1") is StepValidityState.VALID
    assert tracker.validity("s2") is StepValidityState.INVALID


def test_no_modification_since_recompute_all_remain_valid():
    pipe = Pipeline()
    for i in range(3):
        pipe.add_step(AddStep(1, identifier=f"s{i}"))
    tracker = PipelineStateTracker(pipe)
    tracker.recompute(_src())
    assert all(s is StepValidityState.VALID for s in tracker.validity_map().values())
