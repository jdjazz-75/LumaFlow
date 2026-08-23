# LumaFlow v1.0 (2026-08-23)
# Vérifie le cache de rendu par étape en RÉSOLUTION DE TRAVAIL (working_render_cache /
# _compute_applied_pipeline_cached) : non-recalcul d'une ligne amont inchangée lors d'un clic sur une
# ligne aval, recalcul limité au plus petit suffixe invalide après une édition amont, purge à
# l'ouverture d'une nouvelle image, et identité bit à bit de l'aperçu ET des vignettes avec un
# replay complet non mis en cache.

"""Correctness + effectiveness tests for the working-resolution render cache (2026-08-23).

Motivation, measured before the change: clicking a Bleach Bypass vignette re-rendered the unchanged
Film row above it -- three times over, since `_working_row_input`, `refresh_workflow` and
`_compute_vignette_states` each replayed the whole pipeline independently. This is the interactive
counterpart of the full-resolution cache already covered by tests/test_step_render_cache.py, and
follows the same discipline: call counting rather than wall-clock timing (a timing assertion would
be slower and flakier under CI load), plus bit-identity against a manually-assembled uncached
reference.
"""
from __future__ import annotations

import pathlib

import numpy
import pytest
from PIL import Image

from lumaflow.api.session import (
    WORKFLOW_CONFIG,
    VignetteStatus,
    _compute_applied_pipeline,
    _render_vignette,
    create_session,
    open_image,
    select_vignette,
)


def _step_index(identifier: str) -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == identifier)


@pytest.fixture
def cache_fixture_image(tmp_path) -> pathlib.Path:
    """Same linear-gradient recipe as tests/test_step_render_cache.py's own fixture, so the two
    cache suites exercise comparable pixels."""
    array = numpy.zeros((300, 400, 3), dtype=numpy.uint8)
    array[:, :, 0] = numpy.linspace(0, 255, 400, dtype=numpy.uint8)[numpy.newaxis, :]
    array[:, :, 1] = numpy.linspace(0, 255, 300, dtype=numpy.uint8)[:, numpy.newaxis]
    array[:, :, 2] = 128
    path = tmp_path / "working_render_cache_fixture.png"
    Image.fromarray(array, mode="RGB").save(path, format="PNG")
    return path


@pytest.fixture
def second_fixture_image(tmp_path) -> pathlib.Path:
    """Deliberately DIFFERENT pixels from cache_fixture_image, same shape -- used to prove
    open_image drops the previous image's cached rows instead of serving them on."""
    array = numpy.zeros((300, 400, 3), dtype=numpy.uint8)
    array[:, :, 0] = 200
    array[:, :, 1] = numpy.linspace(255, 0, 300, dtype=numpy.uint8)[:, numpy.newaxis]
    array[:, :, 2] = numpy.linspace(255, 0, 400, dtype=numpy.uint8)[numpy.newaxis, :]
    path = tmp_path / "working_render_cache_fixture_2.png"
    Image.fromarray(array, mode="RGB").save(path, format="PNG")
    return path


def _count_calls(step):
    """Wraps `step.processor` in place with a call counter; returns a 1-element list acting as a
    mutable counter (`counter[0]`). Same helper as tests/test_step_render_cache.py."""
    counter = [0]
    original = step.processor

    def _wrapped(image, params):
        counter[0] += 1
        return original(image, params)

    step.processor = _wrapped
    return counter


def _uncached_outputs(session):
    """The reference: a plain, cache-free replay of the whole pipeline over the working copy."""
    outputs, error = _compute_applied_pipeline(
        session.pipeline,
        session.working_image,
        session.thumbnail_selections,
        render_vignette=_render_vignette,
    )
    assert error is None
    return outputs


def test_selecting_a_downstream_row_does_not_recompute_an_unchanged_upstream_row(cache_fixture_image):
    """The exact scenario that motivated the cache: pick a Film look, then work in Bleach Bypass.
    The Film row is settled and must not be rendered again."""
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _step_index("film"), "Velvia")

    film_calls = _count_calls(session.pipeline._steps[_step_index("film")])

    select_vignette(session, _step_index("bleach_bypass"), "Titanium")
    assert film_calls[0] == 0

    select_vignette(session, _step_index("bleach_bypass"), "Loki")
    assert film_calls[0] == 0


def test_changing_an_upstream_row_does_recompute_the_downstream_rows(cache_fixture_image):
    """The other half of the contract -- the cache must not go stale when it genuinely should."""
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _step_index("film"), "Velvia")
    select_vignette(session, _step_index("bleach_bypass"), "Titanium")

    bleach_calls = _count_calls(session.pipeline._steps[_step_index("bleach_bypass")])

    select_vignette(session, _step_index("film"), "Astia")
    assert bleach_calls[0] >= 1


def test_preview_stays_bit_identical_to_an_uncached_replay(cache_fixture_image):
    """Direct precedent: tests/test_zoom_before_cache.py's
    test_render_zoom_before_and_after_stay_bit_identical_to_an_uncached_full_replay -- the cache is
    only legitimate if the pixels it serves are the ones the naive path would have produced."""
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _step_index("film"), "Velvia")
    select_vignette(session, _step_index("bleach_bypass"), "Titanium")
    select_vignette(session, _step_index("light"), "Soft")

    reference = _uncached_outputs(session)
    expected = reference[session.pipeline._steps[-1].identifier]

    assert numpy.array_equal(session.image_session.active, expected)


def test_vignette_pixels_stay_bit_identical_to_an_uncached_replay(cache_fixture_image):
    """The cached row outputs feed every vignette's own input, so a stale entry would corrupt the
    filmstrip without touching the main preview."""
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _step_index("film"), "Velvia")
    select_vignette(session, _step_index("bleach_bypass"), "Titanium")

    reference = _uncached_outputs(session)

    from lumaflow.api.session import (
        ADDON_INDEX,
        _downscaled_for_preview,
        _effective_parameters_for_vignette,
        _resolve_addon_for_row,
    )

    checked = 0
    for row_index, row_states in session.vignette_states.items():
        step = session.pipeline._steps[row_index]
        # The real code resolves each row's descriptor, which is what lets a NON-selected
        # identifier resolve its own preset parameters -- passing None here would silently compare
        # against an identity render for every vignette but the selected one.
        descriptor = _resolve_addon_for_row(WORKFLOW_CONFIG.rows[row_index], ADDON_INDEX)
        row_input = (
            session.working_image
            if row_index == 0
            else reference[session.pipeline._steps[row_index - 1].identifier]
        )
        preview_input = _downscaled_for_preview(row_input)
        for identifier, state in row_states.items():
            if state.status is not VignetteStatus.READY:
                continue
            parameters = _effective_parameters_for_vignette(
                step, descriptor, identifier, preview_input.shape, session.thumbnail_selections
            )
            expected = step.processor(preview_input, parameters)
            assert numpy.array_equal(state.pixels, expected), f"row {row_index} / {identifier}"
            checked += 1
    assert checked > 0


def test_opening_a_new_image_does_not_serve_the_previous_images_cached_rows(
    cache_fixture_image, second_fixture_image
):
    """A freshly-opened image starts with no selections -- i.e. exactly the ancestry signatures the
    previous image may have ended on. Without an explicit purge in open_image, position 0's entry
    (often signature ()) would match and the old pixels would be served."""
    session = create_session()
    open_image(session, cache_fixture_image)
    select_vignette(session, _step_index("film"), "Velvia")
    first_preview = session.image_session.active.copy()

    open_image(session, second_fixture_image)
    # open_image purges the cache and then immediately refills it through its own refresh_workflow,
    # so "empty" is the wrong invariant -- what matters is that every entry now describes the NEW
    # image. Position 0 is the telling one: its signature is often () for both images.
    assert numpy.array_equal(
        session.working_render_cache[0][1],
        _uncached_outputs(session)[session.pipeline._steps[0].identifier],
    )

    select_vignette(session, _step_index("film"), "Velvia")
    assert not numpy.array_equal(session.image_session.active, first_preview)
    assert numpy.array_equal(
        session.image_session.active,
        _uncached_outputs(session)[session.pipeline._steps[-1].identifier],
    )
