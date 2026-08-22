# LumaFlow v1.0 (2026-08-07)
# Teste le préchauffage en arrière-plan du cache "avant" à l'activation/sélection d'une ligne
# (precompute_row_before) : réutilisation par render_zoom_before, invalidation sur signature
# périmée, attente d'un précalcul en cours plutôt que doublon, repli après timeout, cas où le
# précalcul est ignoré (index 0, ligne déjà quittée) ou invalidé par une nouvelle ouverture d'image,
# et réutilisation d'une étape amont partagée en changeant de ligne zoomée (étape 5).

"""Tests for the background "Avant" precompute added on row activation/selection
(PERF-ZOOM-RENDER-PLAN.md étape 4).

Same call-counting-wrapper discipline as tests/test_zoom_before_cache.py (étape 1) -- proves
whether an upstream step was recomputed, never relies on wall-clock timing except where the whole
point of the test IS timing behaviour (the wait/timeout tests), and those use short, deterministic
sleeps. The module-level `_no_row_before_precompute_delay` autouse fixture (tests/conftest.py)
already zeroes _ROW_BEFORE_PRECOMPUTE_DELAY_S for every test in the suite, so precompute_row_before
runs its recheck/render immediately here without needing a per-test patch.
"""
from __future__ import annotations

import pathlib
import threading
import time

import numpy
import pytest
from PIL import Image

from lumaflow.api import session as session_module
from lumaflow.api.session import (
    WORKFLOW_CONFIG,
    _PendingRowBefore,
    cancel_zoom,
    create_session,
    open_image,
    open_zoom,
    precompute_row_before,
    render_full_resolution,
    render_zoom_before,
    select_vignette,
)


def _film_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "film")


def _light_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "light")


def _vignette_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "vignette")


@pytest.fixture
def precompute_fixture_image(tmp_path) -> pathlib.Path:
    array = numpy.zeros((300, 400, 3), dtype=numpy.uint8)
    array[:, :, 0] = numpy.linspace(0, 255, 400, dtype=numpy.uint8)[numpy.newaxis, :]
    array[:, :, 1] = numpy.linspace(0, 255, 300, dtype=numpy.uint8)[:, numpy.newaxis]
    array[:, :, 2] = 128
    path = tmp_path / "precompute_fixture.png"
    Image.fromarray(array, mode="RGB").save(path, format="PNG")
    return path


def _count_calls(step):
    counter = [0]
    original = step.processor

    def _wrapped(image, params):
        counter[0] += 1
        return original(image, params)

    step.processor = _wrapped
    return counter


def test_precompute_row_before_warms_the_session_cache(precompute_fixture_image):
    session = create_session()
    open_image(session, precompute_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    session.active_step_index = _light_step_index()

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])
    precompute_row_before(session, _light_step_index())

    assert film_calls[0] == 1
    assert session.step_render_cache.get(_light_step_index() - 1) is not None


def test_render_zoom_before_reuses_a_completed_precompute_without_recomputing(precompute_fixture_image):
    """Point 2 of the user's 3 explicit questions: the Zoom cache must be FED from the session
    cache (a copy), never recomputed independently once the session cache already has it."""
    session = create_session()
    open_image(session, precompute_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    session.active_step_index = _light_step_index()
    precompute_row_before(session, _light_step_index())

    # open_zoom's own internal select_vignette/refresh_workflow legitimately calls Film's
    # processor to recompute thumbnail/preview states -- unrelated to render_zoom_before's own
    # cache. Install the counter AFTER it, like test_zoom_before_cache.py's étape 1 tests, so it
    # measures only what render_zoom_before itself does.
    open_zoom(session, _light_step_index(), "Dramatique")
    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])

    result = render_zoom_before(session)

    assert film_calls[0] == 0  # never recomputed -- fed straight from session.step_render_cache
    reference = render_full_resolution(session, upto_exclusive=_light_step_index())
    assert numpy.array_equal(result, reference)


def test_precompute_ignored_once_its_signature_is_stale(precompute_fixture_image):
    """A precompute finished for an old signature must never be served once an upstream (auxiliary)
    edit has changed what the real "before" should look like -- falls back to a cold render."""
    session = create_session()
    open_image(session, precompute_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    session.active_step_index = _light_step_index()
    precompute_row_before(session, _light_step_index())

    stale_cache = session.step_render_cache.get(_light_step_index() - 1)
    assert stale_cache is not None

    # An auxiliary edit upstream of Light changes the real ancestry signature.
    open_zoom(session, _light_step_index(), "Dramatique")
    from lumaflow.api.session import set_auxiliary_zoom_parameter

    set_auxiliary_zoom_parameter(session, "geometry", "rotation_angle", 12.0)

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])
    result = render_zoom_before(session)

    assert film_calls[0] == 1  # cold recompute -- the stale precompute was correctly ignored
    assert not numpy.array_equal(result, stale_cache[1])


def test_render_zoom_before_waits_for_an_in_flight_precompute_instead_of_duplicating_it(precompute_fixture_image):
    """Point 1 and 3 of the user's 3 explicit questions: render_zoom_before must WAIT on a
    matching in-flight precompute rather than starting a second, redundant render."""
    session = create_session()
    open_image(session, precompute_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    open_zoom(session, _light_step_index(), "Dramatique")

    step_index = session.zoom.step_index
    signature = session_module._zoom_before_signature(session)
    reference = render_full_resolution(session, upto_exclusive=step_index)

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])

    pending = _PendingRowBefore(step_index, signature)
    session._active_row_before_pending = pending

    def _finish_precompute_after_a_short_delay():
        time.sleep(0.3)
        with session._row_before_lock:
            session.step_render_cache[step_index - 1] = (signature, reference)
            pending.result = reference
            session._active_row_before_pending = None
        pending.event.set()

    thread = threading.Thread(target=_finish_precompute_after_a_short_delay)
    thread.start()
    try:
        result = render_zoom_before(session)
    finally:
        thread.join()

    assert film_calls[0] == 0  # waited for the precompute -- never triggered its own render
    assert numpy.array_equal(result, reference)


def test_render_zoom_before_falls_back_to_a_cold_render_if_the_precompute_times_out(precompute_fixture_image, monkeypatch):
    """A stuck/never-resolving precompute must never block Zoom from opening indefinitely."""
    session = create_session()
    open_image(session, precompute_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    open_zoom(session, _light_step_index(), "Dramatique")

    step_index = session.zoom.step_index
    signature = session_module._zoom_before_signature(session)

    pending = _PendingRowBefore(step_index, signature)  # event never set -- simulates a stuck task
    session._active_row_before_pending = pending

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])

    monkeypatch.setattr(session_module, "_ROW_BEFORE_WAIT_TIMEOUT_S", 0.2)
    result = render_zoom_before(session)

    assert film_calls[0] == 1  # fell through to a cold render after the timeout
    reference = render_full_resolution(session, upto_exclusive=step_index)
    assert numpy.array_equal(result, reference)


def test_precompute_row_before_skipped_for_step_index_zero(precompute_fixture_image):
    session = create_session()
    open_image(session, precompute_fixture_image)
    session.active_step_index = 0

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])
    precompute_row_before(session, 0)

    assert film_calls[0] == 0
    assert session.step_render_cache == {}


def test_precompute_row_before_skipped_if_the_active_row_already_moved_on(precompute_fixture_image):
    """The debounce + recheck: a row only briefly passed through (e.g. arrow-key navigation) must
    not trigger a wasted render, even once the delay has elapsed."""
    session = create_session()
    open_image(session, precompute_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    session.active_step_index = _light_step_index()

    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])

    # By the time the (real, un-mocked in production) delay would have elapsed, the user already
    # moved to another row.
    session.active_step_index = _film_step_index()
    precompute_row_before(session, _light_step_index())

    assert film_calls[0] == 0
    assert session.step_render_cache.get(_light_step_index() - 1) is None


def test_open_image_clears_the_row_before_cache(precompute_fixture_image, tmp_path):
    session = create_session()
    open_image(session, precompute_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    session.active_step_index = _light_step_index()
    precompute_row_before(session, _light_step_index())
    assert session.step_render_cache.get(_light_step_index() - 1) is not None

    session._active_row_before_pending = _PendingRowBefore(_light_step_index(), ())

    other_array = numpy.full((50, 60, 3), 200, dtype=numpy.uint8)
    other_path = tmp_path / "other.png"
    Image.fromarray(other_array, mode="RGB").save(other_path, format="PNG")
    open_image(session, other_path)

    assert session.step_render_cache == {}
    assert session._active_row_before_pending is None


def test_switching_the_zoomed_row_reuses_a_shared_upstream_steps_cached_before(precompute_fixture_image):
    """PERF-ZOOM-RENDER-PLAN.md étape 5's actual point: opening Zoom on Film, closing it, then
    opening Zoom on Vignettage (further downstream, Film's selection never touched in between)
    must NOT recompute Film's "Avant" a second time -- exercises the real Zoom-opening path
    (open_zoom + render_zoom_before), not render_full_resolution directly (already covered by
    tests/test_step_render_cache.py)."""
    session = create_session()
    open_image(session, precompute_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")

    open_zoom(session, _light_step_index(), "Dramatique")
    render_zoom_before(session)
    cancel_zoom(session)

    # open_zoom's own internal select_vignette/refresh_workflow legitimately calls Film's
    # processor to recompute thumbnail/preview states -- unrelated to render_zoom_before's own
    # cache. Install the counter AFTER it, same reasoning as the tests above.
    open_zoom(session, _vignette_step_index(), "Round Central")
    film_calls = _count_calls(session.pipeline._steps[_film_step_index()])

    result = render_zoom_before(session)

    assert film_calls[0] == 0  # still 0 -- Film's cached output was reused, not recomputed
    reference = render_full_resolution(session, upto_exclusive=_vignette_step_index())
    assert numpy.array_equal(result, reference)
