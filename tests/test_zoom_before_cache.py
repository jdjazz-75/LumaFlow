# LumaFlow v1.0 (2026-08-07)
# Vérifie l'efficacité et la correction du cache d'image "avant" pour render_zoom_before/after :
# non-recalcul sur une simple édition de curseur, invalidation correcte sur une édition auxiliaire
# en amont, et identité bit à bit avec un rendu complet non mis en cache.

"""Correctness + effectiveness tests for the "before" image cache added to render_zoom_before/
render_zoom_after (PERF-ZOOM-RENDER-PLAN.md étape 1).

Uses a call-counting wrapper around an upstream step's own `processor`, not wall-clock timing, to
prove the cache is actually skipping recomputation -- a timing-based assertion would be both
slower and flakier under CI load. tests/test_zoom_render_performance.py (étape 0) already covers
the wall-clock regression-guard angle; this file covers "does the cache actually engage, and does
it invalidate at the right moments" instead.
"""
from __future__ import annotations

import pathlib

import numpy
import pytest
from PIL import Image

from lumaflow.api.session import (
    WORKFLOW_CONFIG,
    create_session,
    open_image,
    open_zoom,
    render_zoom_after,
    select_vignette,
    set_auxiliary_zoom_parameter,
    set_zoom_parameter,
)


def _film_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "film")


def _light_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "light")


@pytest.fixture
def cache_fixture_image(tmp_path) -> pathlib.Path:
    array = numpy.zeros((300, 400, 3), dtype=numpy.uint8)
    array[:, :, 0] = numpy.linspace(0, 255, 400, dtype=numpy.uint8)[numpy.newaxis, :]
    array[:, :, 1] = numpy.linspace(0, 255, 300, dtype=numpy.uint8)[:, numpy.newaxis]
    array[:, :, 2] = 128
    path = tmp_path / "cache_fixture.png"
    Image.fromarray(array, mode="RGB").save(path, format="PNG")
    return path


def _count_calls(step):
    """Wraps `step.processor` in place with a call counter; returns a 0-element list acting as a
    mutable counter (`counter[0]`)."""
    counter = [0]
    original = step.processor

    def _wrapped(image, params):
        counter[0] += 1
        return original(image, params)

    step.processor = _wrapped
    return counter


def test_render_zoom_after_does_not_recompute_upstream_film_step_on_a_plain_slider_edit(cache_fixture_image):
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    open_zoom(session, _light_step_index(), "Dramatique")

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])

    set_zoom_parameter(session, "contrast", 20.0)
    first = render_zoom_after(session)
    assert film_calls[0] == 1  # cache miss: computes and caches the "before" image once

    set_zoom_parameter(session, "contrast", 60.0)
    second = render_zoom_after(session)
    assert film_calls[0] == 1  # cache hit: Film's own step was NOT recomputed a second time

    # The cache reuse must not accidentally freeze the OUTPUT too -- Light's own slider change
    # still has to be reflected.
    assert not numpy.array_equal(first, second)


def test_render_zoom_after_recomputes_upstream_after_an_auxiliary_edit(cache_fixture_image):
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    open_zoom(session, _light_step_index(), "Dramatique")

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])

    set_zoom_parameter(session, "contrast", 20.0)
    render_zoom_after(session)
    assert film_calls[0] == 1

    # Geometry sits upstream of both Film and Light -- editing it through the auxiliary path
    # (Geometry/Cadrage edited from within another row's Zoom) must invalidate the cached "before"
    # image, since that image was rendered with the OLD rotation.
    set_auxiliary_zoom_parameter(session, "geometry", "rotation_angle", 12.0)
    render_zoom_after(session)
    assert film_calls[0] == 2  # cache correctly invalidated and recomputed


def test_render_zoom_before_and_after_stay_bit_identical_to_an_uncached_full_replay(cache_fixture_image):
    """Direct precedent: the 2026-07-17 film.py perf remediation required numpy.array_equal proof
    of no behavior change -- same discipline applied here against a manually-assembled uncached
    reference."""
    from lumaflow.api.session import _compute_applied_pipeline, _render_vignette

    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    open_zoom(session, _light_step_index(), "Dramatique")
    set_zoom_parameter(session, "contrast", 37.0)

    step_index = session.zoom.step_index
    outputs, error = _compute_applied_pipeline(
        session.pipeline, session.image_session.original, session.thumbnail_selections,
        render_vignette=_render_vignette, upto_exclusive=step_index + 1,
    )
    assert error is None
    reference = outputs[session.pipeline._steps[step_index].identifier]

    cached_result = render_zoom_after(session)
    assert numpy.array_equal(reference, cached_result)
