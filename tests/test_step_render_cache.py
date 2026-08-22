# LumaFlow v1.0 (2026-08-07)
# Vérifie le cache de rendu par étape (step_render_cache/_render_pipeline_prefix) : non-recalcul
# d'une étape dont les paramètres n'ont pas changé entre deux appels, recalcul limité au plus petit
# suffixe invalide après une édition amont, réutilisation entre deux frontières différentes
# (changement de ligne), identité bit à bit avec un rendu complet non mis en cache, et écriture par
# render_zoom_after de la sortie de l'étape zoomée elle-même (jamais en aperçu réduit).

"""Correctness + effectiveness tests for the per-step render cache added to render_full_resolution
via _render_pipeline_prefix (PERF-ZOOM-RENDER-PLAN.md étape 5).

Uses a call-counting wrapper around a step's own `processor`, not wall-clock timing, to prove the
cache is actually skipping recomputation -- same discipline as tests/test_zoom_before_cache.py
(étape 1) and tests/test_row_before_precompute.py (étape 4).
"""
from __future__ import annotations

import pathlib

import numpy
import pytest
from PIL import Image

from lumaflow.api.session import (
    WORKFLOW_CONFIG,
    _compute_applied_pipeline,
    confirm_zoom,
    create_session,
    open_image,
    open_zoom,
    render_full_resolution,
    render_zoom_after,
    render_zoom_before,
    select_vignette,
    set_zoom_parameter,
)


def _film_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "film")


def _light_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "light")


def _vignette_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "vignette")


@pytest.fixture
def cache_fixture_image(tmp_path) -> pathlib.Path:
    array = numpy.zeros((300, 400, 3), dtype=numpy.uint8)
    array[:, :, 0] = numpy.linspace(0, 255, 400, dtype=numpy.uint8)[numpy.newaxis, :]
    array[:, :, 1] = numpy.linspace(0, 255, 300, dtype=numpy.uint8)[:, numpy.newaxis]
    array[:, :, 2] = 128
    path = tmp_path / "step_render_cache_fixture.png"
    Image.fromarray(array, mode="RGB").save(path, format="PNG")
    return path


def _count_calls(step):
    """Same helper as tests/test_zoom_before_cache.py -- wraps `step.processor` in place with a
    call counter; returns a 0-element list acting as a mutable counter (`counter[0]`)."""
    counter = [0]
    original = step.processor

    def _wrapped(image, params):
        counter[0] += 1
        return original(image, params)

    step.processor = _wrapped
    return counter


def test_render_full_resolution_does_not_recompute_an_unchanged_step_across_two_calls(cache_fixture_image):
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])

    first = render_full_resolution(session, upto_exclusive=_light_step_index())
    assert film_calls[0] == 1  # cache miss: computed and cached once

    second = render_full_resolution(session, upto_exclusive=_light_step_index())
    assert film_calls[0] == 1  # cache hit: not recomputed
    assert numpy.array_equal(first, second)


def test_render_full_resolution_recomputes_only_the_invalid_suffix_after_an_upstream_edit(cache_fixture_image):
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])
    light_calls = _count_calls(session.pipeline._steps[_light_step_index()])

    render_full_resolution(session, upto_exclusive=_light_step_index() + 1)
    assert film_calls[0] == 1
    assert light_calls[0] == 1

    # select_vignette itself also drives the SEPARATE, unrelated working-image vignette-state
    # refresh (refresh_workflow -> _compute_vignette_states, session.working_image) -- it shares
    # the same step objects, so it moves both counters by however many candidate previews that
    # path renders. Irrelevant here: what this test isolates is the DELTA caused specifically by
    # the next render_full_resolution call, not the absolute count.
    select_vignette(session, _film_step_index(), "Velvia")
    film_after_select = film_calls[0]
    light_after_select = light_calls[0]

    render_full_resolution(session, upto_exclusive=_light_step_index() + 1)
    # Film's own cached position was invalidated by the new selection -- recomputed exactly once
    # more. Light sits downstream of Film, so it's also invalidated and recomputed exactly once.
    assert film_calls[0] == film_after_select + 1
    assert light_calls[0] == light_after_select + 1


def test_render_full_resolution_reuses_shared_upstream_steps_across_two_different_boundaries(cache_fixture_image):
    """The core scenario this cache exists for: rendering up to Light, then up to Vignettage
    (further downstream, with Bleach Bypass/Color Splash/Monochrome/B&W in between), must NOT
    recompute Film a second time -- its own selection/parameters never changed between the two
    calls. This is the exact gap the single-slot "before" caches (étapes 1/4) could not close,
    since each only remembers ONE boundary's worth of result at a time."""
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])

    render_full_resolution(session, upto_exclusive=_light_step_index() + 1)
    assert film_calls[0] == 1

    render_full_resolution(session, upto_exclusive=_vignette_step_index() + 1)
    assert film_calls[0] == 1  # still 1 -- Film's cached output was reused, not recomputed


def test_render_full_resolution_bit_identical_to_an_uncached_full_replay(cache_fixture_image):
    """Same discipline as tests/test_zoom_before_cache.py's own bit-exactness test: prove the
    cached path produces exactly the same pixels as a manually-assembled uncached reference."""
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")

    upto_exclusive = _light_step_index() + 1
    outputs, error = _compute_applied_pipeline(
        session.pipeline, session.image_session.original, session.thumbnail_selections,
        upto_exclusive=upto_exclusive,
    )
    assert error is None
    reference = outputs[session.pipeline._steps[upto_exclusive - 1].identifier]

    cached_result = render_full_resolution(session, upto_exclusive=upto_exclusive)
    assert numpy.array_equal(reference, cached_result)


def test_open_image_clears_the_step_render_cache(cache_fixture_image, tmp_path):
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    render_full_resolution(session, upto_exclusive=_light_step_index() + 1)
    assert session.step_render_cache  # populated

    second_path = tmp_path / "second.png"
    Image.fromarray(numpy.full((10, 10, 3), 64, dtype=numpy.uint8), mode="RGB").save(second_path, format="PNG")
    open_image(session, second_path)
    assert session.step_render_cache == {}


def test_render_zoom_after_full_resolution_caches_the_zoomed_steps_own_output(cache_fixture_image):
    """PERF-ZOOM-RENDER-PLAN.md étape 5's last gap: only the steps strictly BEFORE the zoomed one
    used to be cached (étapes 1/4/2) -- the zoomed step's own output, including a live edit, never
    was. A full-resolution render_zoom_after call must now populate step_render_cache[step_index]
    too, with pixels matching what it returned."""
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    open_zoom(session, _light_step_index(), "Dramatique")
    set_zoom_parameter(session, "contrast", 30.0)

    result = render_zoom_after(session)

    cached = session.step_render_cache.get(_light_step_index())
    assert cached is not None
    assert numpy.array_equal(cached[1], result)


def test_render_zoom_after_with_max_dimension_never_writes_into_the_cache(cache_fixture_image):
    """The reduced-preview invariant (étape 2) extended to the new cache write: a `max_dimension`
    call must never leave a degraded/downscaled array in step_render_cache, or a later full-
    resolution read (e.g. opening Zoom on a downstream row) would silently serve it."""
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    open_zoom(session, _light_step_index(), "Dramatique")
    set_zoom_parameter(session, "contrast", 30.0)

    render_zoom_after(session, max_dimension=50)

    assert session.step_render_cache.get(_light_step_index()) is None


def test_opening_a_downstream_zoom_reuses_a_previously_edited_and_confirmed_steps_cached_output(cache_fixture_image):
    """End-to-end scenario étape 3 exists for: edit Light via its Zoom, confirm, then open Zoom on
    Vignettage (downstream of Light) -- neither Film nor Light's processor should run again, since
    Vignettage's own "before" render (render_zoom_before -> render_full_resolution's prefix scan)
    can now reuse Light's cached, edited output directly instead of replaying it."""
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")

    open_zoom(session, _light_step_index(), "Dramatique")
    set_zoom_parameter(session, "contrast", 30.0)
    edited_after = render_zoom_after(session)
    confirm_zoom(session)

    # open_zoom's own internal select_vignette/refresh_workflow legitimately touches Film/Light's
    # processors to recompute thumbnail/preview states, unrelated to the caches under test here --
    # same reasoning as tests/test_row_before_precompute.py. Install the counters AFTER it.
    open_zoom(session, _vignette_step_index(), "Round Central")
    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])
    light_calls = _count_calls(session.pipeline._steps[_light_step_index()])

    result = render_zoom_before(session)

    assert film_calls[0] == 0
    assert light_calls[0] == 0
    assert numpy.array_equal(result, edited_after)
