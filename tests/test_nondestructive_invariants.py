# LumaFlow v1.0 (2026-08-07)
# Vérifie les invariants de non-destructivité sur la fixture image déterministe : l'image source
# n'est jamais mutée par le pipeline (vide, neutre, multi-étapes), la sortie est pixel-identique en
# l'absence de traitement, l'ordre des étapes non commutatives est respecté, et l'invalidation
# reste cohérente sur ces mêmes scénarios.

from __future__ import annotations

import numpy
import pytest

from lumaflow.engine.pipeline import Pipeline, PipelineEngine, PipelineStep
from lumaflow.engine.invalidation import PipelineStateTracker, StepValidityState as V


class AddStep(PipelineStep):
    def __init__(self, k: int, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.k = k

    def apply(self, image: numpy.ndarray) -> numpy.ndarray:
        return numpy.clip(image.astype(numpy.int16) + self.k, 0, 255).astype(numpy.uint8)


# ---------------------------------------------------------------------------
# US1 — Source Integrity Invariant
# ---------------------------------------------------------------------------

def test_source_unchanged_after_empty_pipeline(deterministic_session):
    session = deterministic_session
    before = session.original.copy()
    PipelineEngine().run(Pipeline(), session.original)
    assert numpy.array_equal(session.original, before)


def test_source_unchanged_after_neutral_pipeline(deterministic_session):
    session = deterministic_session
    before = session.original.copy()
    pipe = Pipeline()
    for i in range(3):
        pipe.add_step(PipelineStep(identifier=f"n{i}"))
    PipelineEngine().run(pipe, session.original)
    assert numpy.array_equal(session.original, before)


def test_source_unchanged_after_multi_step_pipeline(deterministic_session):
    session = deterministic_session
    before = session.original.copy()
    pipe = Pipeline()
    for i in range(4):
        pipe.add_step(AddStep(20, identifier=f"a{i}"))
    PipelineEngine().run(pipe, session.original)
    assert numpy.array_equal(session.original, before)


def test_controlled_breach_detects_mutation(deterministic_session):
    session = deterministic_session
    before = session.original.copy()
    breached = before.copy()
    breached[0, 0, 0] = (int(breached[0, 0, 0]) + 1) % 256
    assert not numpy.array_equal(before, breached)


# ---------------------------------------------------------------------------
# US2 — Pipeline Coherence Verification
# ---------------------------------------------------------------------------

def test_empty_pipeline_output_pixel_identical_to_source(deterministic_session):
    source = deterministic_session.original
    result = PipelineEngine().run(Pipeline(), source)
    assert numpy.array_equal(result.final, source)


def test_neutral_pipeline_output_pixel_identical_to_source(deterministic_session):
    source = deterministic_session.original
    pipe = Pipeline()
    for i in range(4):
        pipe.add_step(PipelineStep(identifier=f"n{i}"))
    result = PipelineEngine().run(pipe, source)
    assert numpy.array_equal(result.final, source)


def test_multi_step_non_commutative_order_respected(deterministic_session):
    source = deterministic_session.original

    class ScaleStep(PipelineStep):
        def __init__(self, factor: float, **kwargs: object) -> None:
            super().__init__(**kwargs)
            self.factor = factor

        def apply(self, image: numpy.ndarray) -> numpy.ndarray:
            return numpy.clip(
                image.astype(numpy.float32) * self.factor, 0, 255
            ).astype(numpy.uint8)

    pipe_ab = Pipeline()
    pipe_ab.add_step(AddStep(30, identifier="add"))
    pipe_ab.add_step(ScaleStep(0.5, identifier="scale"))

    pipe_ba = Pipeline()
    pipe_ba.add_step(ScaleStep(0.5, identifier="scale"))
    pipe_ba.add_step(AddStep(30, identifier="add"))

    ab_out = PipelineEngine().run(pipe_ab, source).final
    ba_out = PipelineEngine().run(pipe_ba, source).final

    assert not numpy.array_equal(ab_out, source)
    assert not numpy.array_equal(ab_out, ba_out)


# ---------------------------------------------------------------------------
# US3 — Invalidation Invariant Verification
# ---------------------------------------------------------------------------

def _fresh_tracker(n: int = 6) -> tuple[Pipeline, PipelineStateTracker]:
    pipe = Pipeline()
    for i in range(n):
        pipe.add_step(AddStep(1, identifier=f"s{i}"))
    return pipe, PipelineStateTracker(pipe)


def test_validity_map_at_first_middle_last(deterministic_session):
    src = deterministic_session.original
    for key in ("s0", "s3", "s5"):
        pipe, tracker = _fresh_tracker(6)
        tracker.recompute(src)
        tracker.invalidate(key)
        vm = tracker.validity_map()
        key_pos = int(key[1:])
        for i in range(6):
            expected = V.VALID if i < key_pos else V.INVALID
            assert vm[f"s{i}"] is expected, f"s{i} wrong after invalidate({key!r})"


def test_all_valid_after_full_recompute(deterministic_session):
    src = deterministic_session.original
    pipe, tracker = _fresh_tracker(6)
    tracker.recompute(src)
    tracker.invalidate("s2")
    tracker.recompute(src)
    assert all(s is V.VALID for s in tracker.validity_map().values())


def test_two_modifications_earliest_governs(deterministic_session):
    src = deterministic_session.original
    pipe, tracker = _fresh_tracker(6)
    tracker.recompute(src)
    tracker.invalidate("s5")
    tracker.invalidate("s2")
    vm = tracker.validity_map()
    assert vm["s0"] is V.VALID
    assert vm["s1"] is V.VALID
    for i in range(2, 6):
        assert vm[f"s{i}"] is V.INVALID, f"s{i} should be INVALID"


def test_initial_validity_observable_before_execution(deterministic_session):
    pipe, tracker = _fresh_tracker(6)
    vm = tracker.validity_map()
    assert isinstance(vm, dict)
    assert len(vm) == 6
    assert all(isinstance(v, V) for v in vm.values())
