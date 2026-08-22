# LumaFlow v1.0 (2026-08-07)
# Garde-fou de performance pour le rendu Zoom "après" : vérifie qu'un rendu multi-étapes (Film +
# Light) sur une image non triviale reste sous un plafond de temps généreux, pour détecter une
# régression grossière (relecture complète du pipeline) plutôt qu'imposer un budget serré. Inclut
# aussi (étape 5) un garde-fou dédié au changement de ligne zoomée.

"""Perf regression guard for the Zoom "après" render path (PERF-ZOOM-RENDER-PLAN.md, étape 0) and
for the row-switch cache reuse added in étape 5.

Exists so a future change (any refactor touching render_zoom_after/render_zoom_before/
_render_pipeline_prefix/_compute_applied_pipeline) that accidentally reintroduces a full, uncached
pipeline replay on every render is caught by a failing assertion instead of "feels slower" in
manual testing -- the situation the plan's own history section documents happening once already
(2026-08-04, forcing render_full_resolution on every interaction, only caught after the fact).

Deliberately timed at the lumaflow.api.session module level (render_zoom_after/render_zoom_before
called directly), not via TestClient/HTTP -- isolates pipeline compute time from FastAPI/PNG-
encoding overhead, the same "compute vs. encode" split the originating performance analysis used.
"""
from __future__ import annotations

import pathlib
import time

import numpy
import pytest
from PIL import Image

from lumaflow.api.session import (
    WORKFLOW_CONFIG,
    confirm_zoom,
    create_session,
    open_image,
    open_zoom,
    render_zoom_after,
    render_zoom_before,
    select_vignette,
    set_zoom_parameter,
)

# 1600x1200 (1.92 MP) -- big enough to make a full pipeline replay clearly visible (regression of
# 5-10x would take this from ~1-2s to 10s+), small enough to stay a fraction of a second to a few
# seconds so this test doesn't dominate a routine `pytest` run.
_PERF_IMAGE_WIDTH = 1600
_PERF_IMAGE_HEIGHT = 1200

# Generous margin over the observed local baseline (~1.5-2s for Film+Light combined at this size,
# see PERF-ZOOM-RENDER-PLAN.md's benchmark table for the 6MP reference point this scales down
# from) -- meant to catch a gross regression (an accidental extra full-pipeline replay, an O(n^2)
# blowup), not to enforce a tight perf budget that would flake on slower CI hardware.
_AFTER_RENDER_CEILING_SECONDS = 12.0

# Row-switch guard (étape 5): a warm switch is a handful of dict lookups, no pixel computation at
# all -- measured locally at ~0.0001s on a 3000x2000 image (see PERF-ZOOM-RENDER-PLAN.md's étape 5
# benchmark). 2s is still ~4 orders of magnitude of margin over that, but stays a small fraction of
# _AFTER_RENDER_CEILING_SECONDS/a cold replay's actual cost (12s+ at this resolution) -- comfortably
# generous for slow CI hardware while still catching a regression back to a full replay.
_ROW_SWITCH_CEILING_SECONDS = 2.0


def _film_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "film")


def _light_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "light")


def _vignette_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "vignette")


@pytest.fixture
def perf_fixture_image(tmp_path) -> pathlib.Path:
    width, height = _PERF_IMAGE_WIDTH, _PERF_IMAGE_HEIGHT
    array = numpy.zeros((height, width, 3), dtype=numpy.uint8)
    array[:, :, 0] = numpy.linspace(0, 255, width, dtype=numpy.uint8)[numpy.newaxis, :]
    array[:, :, 1] = numpy.linspace(0, 255, height, dtype=numpy.uint8)[:, numpy.newaxis]
    array[:, :, 2] = 128
    path = tmp_path / "perf_fixture.png"
    Image.fromarray(array, mode="RGB").save(path, format="PNG")
    return path


@pytest.mark.perf
def test_render_zoom_after_with_upstream_look_stays_under_ceiling(perf_fixture_image):
    """Baseline guard, NOT a caching-effectiveness test (see test_zoom_before_cache.py for that,
    once étape 1 lands) -- a single render_zoom_after call, on a non-trivial image, with a real
    upstream look selected (Film "Classic Chrome") and Zoom open on a later row (Light
    "Dramatique") so the render actually replays a multi-step pipeline, not a no-op passthrough."""
    session = create_session()
    open_image(session, perf_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    open_zoom(session, _light_step_index(), "Dramatique")
    set_zoom_parameter(session, "contrast", 30.0)

    start = time.perf_counter()
    render_zoom_after(session)
    elapsed = time.perf_counter() - start
    print(f"\nrender_zoom_after elapsed: {elapsed:.3f}s (ceiling {_AFTER_RENDER_CEILING_SECONDS}s)")

    assert elapsed < _AFTER_RENDER_CEILING_SECONDS, (
        f"render_zoom_after took {elapsed:.2f}s on a {_PERF_IMAGE_WIDTH}x{_PERF_IMAGE_HEIGHT} "
        f"image with Film+Light active -- exceeds the {_AFTER_RENDER_CEILING_SECONDS}s regression "
        "ceiling (see PERF-ZOOM-RENDER-PLAN.md)"
    )


@pytest.mark.perf
def test_switching_the_zoomed_row_stays_far_under_a_cold_replays_cost(perf_fixture_image):
    """Row-switch guard (PERF-ZOOM-RENDER-PLAN.md étape 5) -- distinct from the baseline guard
    above: this one exists to catch a regression back to per-row recomputation specifically, not
    just a general slowdown. Uses Film's Zoom first (warms step_render_cache through Light,
    inclusive, via a real edit that's then CONFIRMED -- confirm_zoom, not cancel_zoom: cancelling
    would restore the pre-edit parameter values and correctly invalidate the cache entry by
    signature mismatch, which is the right behaviour but would defeat the point of this test), then
    opens Zoom on Vignettage -- further downstream, with Bleach Bypass/Color Splash/Monochrome/B&W
    in between -- and times only the row-switch's own "before" render. A regression that drops the
    per-step cache back to a per-boundary one (or removes it) would push this well past
    _ROW_SWITCH_CEILING_SECONDS, since it would then replay Film+Light (and the look steps between
    them) from scratch."""
    session = create_session()
    open_image(session, perf_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")

    open_zoom(session, _light_step_index(), "Dramatique")
    set_zoom_parameter(session, "contrast", 30.0)
    render_zoom_after(session)
    confirm_zoom(session)

    open_zoom(session, _vignette_step_index(), "Round Central")
    start = time.perf_counter()
    render_zoom_before(session)
    elapsed = time.perf_counter() - start
    print(f"\nrow-switch render_zoom_before elapsed: {elapsed:.4f}s (ceiling {_ROW_SWITCH_CEILING_SECONDS}s)")

    assert elapsed < _ROW_SWITCH_CEILING_SECONDS, (
        f"row-switch render_zoom_before took {elapsed:.2f}s on a "
        f"{_PERF_IMAGE_WIDTH}x{_PERF_IMAGE_HEIGHT} image after Film+Light were already rendered "
        f"once -- exceeds the {_ROW_SWITCH_CEILING_SECONDS}s regression ceiling, suggesting the "
        "shared upstream steps were recomputed instead of reused (see PERF-ZOOM-RENDER-PLAN.md "
        "étape 5)"
    )
