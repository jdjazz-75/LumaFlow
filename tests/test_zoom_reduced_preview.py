# LumaFlow v1.0 (2026-08-07)
# Teste le paramètre optionnel `max_dimension` (rendu réduit) au niveau module et via les endpoints
# HTTP réels, et vérifie qu'une demande de rendu réduit ne corrompt jamais le cache "avant" en
# pleine résolution.

"""Tests for the optional `max_dimension` reduced-resolution render (PERF-ZOOM-RENDER-PLAN.md
étape 2) -- both at the lumaflow.api.session module level and through the real HTTP endpoints, and
specifically that requesting a reduced render never poisons the full-resolution "before" cache
added in étape 1.
"""
from __future__ import annotations

import io
import pathlib

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import lumaflow.api.app as api_app
from lumaflow.api.app import app
from lumaflow.api.session import (
    WORKFLOW_CONFIG,
    create_session,
    open_zoom,
    render_zoom_after,
    select_vignette,
    set_zoom_parameter,
)
from lumaflow.api.session import open_image as session_open_image


class _FakeTkRoot:
    def withdraw(self) -> None:
        pass

    def attributes(self, *args, **kwargs) -> None:
        pass

    def destroy(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _fake_tk(monkeypatch):
    monkeypatch.setattr(api_app, "Tk", _FakeTkRoot)


@pytest.fixture
def client():
    return TestClient(app)


def _film_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "film")


def _light_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "light")


@pytest.fixture
def reduced_preview_fixture_image(tmp_path) -> pathlib.Path:
    array = numpy.zeros((300, 400, 3), dtype=numpy.uint8)
    array[:, :, 0] = numpy.linspace(0, 255, 400, dtype=numpy.uint8)[numpy.newaxis, :]
    array[:, :, 1] = numpy.linspace(0, 255, 300, dtype=numpy.uint8)[:, numpy.newaxis]
    array[:, :, 2] = 128
    path = tmp_path / "reduced_preview_fixture.png"
    Image.fromarray(array, mode="RGB").save(path, format="PNG")
    return path


def _open(client: TestClient, path: pathlib.Path) -> str:
    session_id = client.post("/sessions").json()["id"]
    client.post(f"/sessions/{session_id}/open", json={"path": str(path)})
    return session_id


def test_render_zoom_after_with_max_dimension_returns_a_smaller_image(reduced_preview_fixture_image):
    session = create_session()
    session_open_image(session, reduced_preview_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    open_zoom(session, _light_step_index(), "Dramatique")
    set_zoom_parameter(session, "contrast", 30.0)

    full = render_zoom_after(session)
    reduced = render_zoom_after(session, max_dimension=100)

    assert max(full.shape[0], full.shape[1]) == 400  # original size, unaffected
    assert max(reduced.shape[0], reduced.shape[1]) == 100


def test_reduced_render_does_not_poison_the_before_cache(reduced_preview_fixture_image):
    """The whole point of keeping the cache full-resolution-only (session.py's render_zoom_after
    docstring) -- a reduced call must never leave session.step_render_cache holding a downscaled
    array, or a LATER full-resolution call would silently stay degraded."""
    session = create_session()
    session_open_image(session, reduced_preview_fixture_image)
    select_vignette(session, _film_step_index(), "Classic Chrome")
    open_zoom(session, _light_step_index(), "Dramatique")
    set_zoom_parameter(session, "contrast", 30.0)

    # Reduced call FIRST (as the drag-time preview path would do), before any full-resolution call.
    render_zoom_after(session, max_dimension=50)
    cached_before_entry = session.step_render_cache.get(_light_step_index() - 1)
    assert cached_before_entry is not None
    cached_before = cached_before_entry[1]
    assert max(cached_before.shape[0], cached_before.shape[1]) == 400  # still full resolution

    full_after_reduced = render_zoom_after(session)
    assert max(full_after_reduced.shape[0], full_after_reduced.shape[1]) == 400

    # Cross-check against a second, completely fresh session that only ever renders full-res --
    # must be bit-identical, proving the reduced call left no trace on the full-res result.
    reference_session = create_session()
    session_open_image(reference_session, reduced_preview_fixture_image)
    select_vignette(reference_session, _film_step_index(), "Classic Chrome")
    open_zoom(reference_session, _light_step_index(), "Dramatique")
    set_zoom_parameter(reference_session, "contrast", 30.0)
    reference_full = render_zoom_after(reference_session)

    assert numpy.array_equal(full_after_reduced, reference_full)


def test_set_zoom_parameter_endpoint_with_max_dimension_returns_smaller_png(client, reduced_preview_fixture_image):
    session_id = _open(client, reduced_preview_fixture_image)
    film_index = _film_step_index()
    client.post(f"/sessions/{session_id}/steps/{film_index}/select", json={"identifier": "Classic Chrome"})
    light_index = _light_step_index()
    client.post(f"/sessions/{session_id}/zoom/{light_index}/open", json={"identifier": "Dramatique"})

    full_response = client.post(
        f"/sessions/{session_id}/zoom/parameter", json={"identifier": "contrast", "value": 25.0}
    )
    assert full_response.status_code == 200
    full_image = Image.open(io.BytesIO(full_response.content))
    assert max(full_image.size) == 400

    reduced_response = client.post(
        f"/sessions/{session_id}/zoom/parameter",
        json={"identifier": "contrast", "value": 55.0, "max_dimension": 80},
    )
    assert reduced_response.status_code == 200
    reduced_image = Image.open(io.BytesIO(reduced_response.content))
    assert max(reduced_image.size) == 80


def test_set_zoom_parameters_endpoint_with_max_dimension_returns_smaller_png(client, reduced_preview_fixture_image):
    session_id = _open(client, reduced_preview_fixture_image)
    film_index = _film_step_index()
    client.post(f"/sessions/{session_id}/steps/{film_index}/select", json={"identifier": "Classic Chrome"})
    light_index = _light_step_index()
    client.post(f"/sessions/{session_id}/zoom/{light_index}/open", json={"identifier": "Dramatique"})

    response = client.post(
        f"/sessions/{session_id}/zoom/parameters",
        json={"updates": [{"identifier": "contrast", "value": 40.0}], "max_dimension": 64},
    )
    assert response.status_code == 200
    image = Image.open(io.BytesIO(response.content))
    assert max(image.size) == 64
