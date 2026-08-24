# LumaFlow v1.0 (2026-08-07)
# Suite de tests d'intégration FastAPI (TestClient, sans mock) couvrant le cycle de vie complet
# d'une session : ouverture d'image/RAW, sélection/zoom des vignettes par addon (Film, Light,
# Color Splash, Vignetting, Geometry/Framing), export, préférences, dialogues natifs, sauvegarde/
# chargement de recette (avec diagnostics structurés) et configuration du workflow (activation/
# désactivation des vignettes, import/export sans écriture disque intempestive).

"""Tests for lumaflow/api/ -- Phase 1 of the PySide6 -> Web migration plan
(2026-07-20). Exercises the FastAPI endpoints via TestClient against the
REAL engine/addons/config code (no mocking), the same way app.py's own
wiring tests do for the desktop app -- these are the "new tests per
endpoint" the plan's Phase 1 verification section calls for.
"""
from __future__ import annotations

import io
import json
import os
import pathlib

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import lumaflow.api.app as api_app
import lumaflow.api.session as api_session
from lumaflow.addons.builtin.film import _VELVIA_PRO_GRADE, resolve_zoom_values
from lumaflow.addons.builtin.light import _BALANCE_GRADE, _GRADES, _FIELD_BOUNDS as _LIGHT_FIELD_BOUNDS
from lumaflow.api.app import app
from lumaflow.api.session import (
    WORKFLOW_CONFIG,
    Session,
    cancel_zoom,
    confirm_zoom,
    create_session,
    open_image,
    open_zoom,
    render_full_resolution,
    render_zoom_after,
    render_zoom_before,
    select_vignette,
    set_zoom_parameter,
    zoom_parameter_declarations,
)
from lumaflow.config.workflow import workflow_config_from_dict
from lumaflow.persistence.recipe import SCHEMA_VERSION

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURE_IMAGE = REPO_ROOT / "tests" / "fixtures" / "deterministic_8x8.png"


class _FakeTkRoot:
    """Stands in for a real tkinter.Tk() root in every dialog-endpoint test below -- none of them
    exercise Tk's own behavior (the inner askXxx call is always monkeypatched separately), so a
    real Tcl interpreter was pure overhead. Real Tk() create/destroy cycling at pytest's rapid
    call rate -- all funneled onto app.py's single pinned `_DIALOG_EXECUTOR` thread, by design, to
    prevent the cross-thread crash documented in memory `tkinter-dialog-threadpool-crash` --
    intermittently raised a raw `_tkinter.TclError` ("Can't find a usable init.tcl"/"tk wasn't
    installed properly") on this machine, and got MORE frequent as more dialog endpoints were
    added (2026-08-05: ~2 of 3 full-suite runs failed a random dialog test right before this fix).
    A real, escalating Windows Tcl/tk fragility, unrelated to any endpoint's actual logic --
    removing the real Tk() removes the trigger entirely."""

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


@pytest.fixture
def large_fixture_image(tmp_path) -> pathlib.Path:
    """Bigger than _VIGNETTE_PREVIEW_MAX_DIMENSION_PX (480) on purpose --
    deterministic_8x8.png is already smaller than that, so it can never
    show a real difference between session.working_image and the full-
    resolution original (correctif de performance, 2026-07-21)."""
    array = numpy.zeros((600, 800, 3), dtype=numpy.uint8)
    array[:, :, 0] = numpy.linspace(0, 255, 800, dtype=numpy.uint8)[numpy.newaxis, :]
    array[:, :, 1] = numpy.linspace(0, 255, 600, dtype=numpy.uint8)[:, numpy.newaxis]
    path = tmp_path / "large_fixture.png"
    Image.fromarray(array, mode="RGB").save(path, format="PNG")
    return path


@pytest.fixture
def isolated_preferences_path(tmp_path, monkeypatch):
    """Every preferences test must never touch the real
    %LOCALAPPDATA%/LumaFlow/preferences.json -- that's the user's actual
    desktop-app config, not test fixture data."""
    path = tmp_path / "preferences.json"
    monkeypatch.setattr(api_app, "default_preferences_path", lambda: path)
    return path


@pytest.fixture
def isolated_workflow_config_path(tmp_path, monkeypatch):
    """Every workflow-config test must never touch the real lumaflow/config/config_workflow.json,
    AND must never leak a PUT's/import's real in-process reassignment of session.WORKFLOW_CONFIG/
    WORKFLOW_ROWS/WORKFLOW_CONFIG_SOURCE_PATH into a LATER test in the same pytest process --
    module globals aren't reset between tests otherwise. Registering the CURRENT values with
    monkeypatch (even though the endpoint reassigns them later, mid-test) is enough: pytest
    restores whatever monkeypatch.setattr captured at registration time on teardown, regardless of
    what happens to the attribute afterward.

    PUT /workflow-config itself never writes to disk at all (2026-08-07: Valider is a pure
    in-memory apply -- only "Ouvrir"/"Exporter" may ever touch a workflow config file, per the
    user's explicit instruction) -- default_workflow_config_path is still patched here because
    GET /dialogs/open-workflow-config, GET /dialogs/export-workflow-config, and
    POST /workflow-config/export all default their target/initialdir from it. WORKFLOW_CONFIG_
    SOURCE_PATH is set to THIS FIXTURE'S tmp path (not merely preserved) so a test asserting "PUT
    never creates this file" is actually checking somewhere real writes would land if that
    invariant ever regressed, rather than silently checking a path nothing would ever touch."""
    path = tmp_path / "config_workflow.json"
    monkeypatch.setattr(api_app, "default_workflow_config_path", lambda: path)
    monkeypatch.setattr(api_session, "WORKFLOW_CONFIG", api_session.WORKFLOW_CONFIG)
    monkeypatch.setattr(api_session, "WORKFLOW_ROWS", api_session.WORKFLOW_ROWS)
    monkeypatch.setattr(api_session, "WORKFLOW_CONFIG_SOURCE_PATH", str(path))
    return path


def _open(client: TestClient) -> str:
    session_id = client.post("/sessions").json()["id"]
    response = client.post(f"/sessions/{session_id}/open", json={"path": str(FIXTURE_IMAGE)})
    assert response.status_code == 200, response.text
    return session_id


def _patch_workflow_config_with_addonless_row(monkeypatch) -> int:
    """Appends one extra row to the real default workflow config whose `category` matches no
    known addon, and monkeypatches `lumaflow.api.session`'s module-level `WORKFLOW_CONFIG`/
    `WORKFLOW_ROWS` to use it for the duration of one test. Returns the new row's index (the
    last one). Used to test "a row with no addon at all" regression coverage that used to rely
    on the real "finishing" row (removed 2026-07-31, spec 045 abandoned -- see constitution
    v1.6.0) -- this keeps that coverage independent of whatever the real shipped config happens
    to contain."""
    data = json.loads(api_session.DEFAULT_WORKFLOW_CONFIG_PATH.read_text(encoding="utf-8"))
    data["rows"].append(
        {
            "identifier": "_test_addonless_row",
            "label": "_TestAddonlessRow",
            "category": "_no_such_category",
            "short_description": "",
            "thumbnail_presets": ["neutral"],
        }
    )
    fake_config = workflow_config_from_dict(data)
    monkeypatch.setattr(api_session, "WORKFLOW_CONFIG", fake_config)
    monkeypatch.setattr(api_session, "WORKFLOW_ROWS", api_session.resolve_workflow_rows(fake_config))
    return len(fake_config.rows) - 1


# --- Session lifecycle ---


def test_create_session_returns_a_fresh_unique_id(client):
    first = client.post("/sessions").json()["id"]
    second = client.post("/sessions").json()["id"]
    assert first != second


def test_unknown_session_id_returns_404(client):
    response = client.get("/sessions/does-not-exist/workflow")
    assert response.status_code == 404


# --- Open image / workflow rows ---


def test_open_image_returns_every_workflow_row_with_neutral_selected(client):
    session_id = _open(client)
    rows = client.get(f"/sessions/{session_id}/workflow").json()
    assert len(rows) >= 3
    for row in rows:
        assert row["selected_vignette_identifier"] == "neutral"
        assert "neutral" in row["vignette_labels"]


def test_session_info_reports_source_after_open(client):
    session_id = _open(client)
    info = client.get(f"/sessions/{session_id}").json()
    assert info["source"]["filename"] == FIXTURE_IMAGE.name
    assert info["source"]["width"] == 8
    assert info["source"]["height"] == 8
    assert info["active_step_index"] == 0


def test_session_info_reports_no_source_before_open(client):
    session_id = client.post("/sessions").json()["id"]
    info = client.get(f"/sessions/{session_id}").json()
    assert info["source"] is None


def test_preview_returns_real_png_bytes_after_open(client):
    session_id = _open(client)
    response = client.get(f"/sessions/{session_id}/preview")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_without_image_loaded_returns_400(client):
    session_id = client.post("/sessions").json()["id"]
    response = client.get(f"/sessions/{session_id}/preview")
    assert response.status_code == 400


def test_open_image_with_missing_file_returns_400_not_500(client):
    session_id = client.post("/sessions").json()["id"]
    response = client.post(
        f"/sessions/{session_id}/open", json={"path": str(REPO_ROOT / "does" / "not" / "exist.png")}
    )
    assert response.status_code == 400


# --- RAW candidate detection (051) ---


def test_open_image_with_raw_file_returns_400_with_distinct_raw_message(client):
    session_id = client.post("/sessions").json()["id"]
    raw_path = REPO_ROOT / "tests" / "fixtures" / "raw_candidate.cr2"
    response = client.post(f"/sessions/{session_id}/open", json={"path": str(raw_path)})
    assert response.status_code == 400
    assert "Format d'image non pris en charge" not in response.json()["detail"]


def test_open_image_with_unsupported_bmp_file_returns_unchanged_generic_message(client, tmp_path):
    session_id = client.post("/sessions").json()["id"]
    bmp_path = tmp_path / "photo.bmp"
    Image.new("RGB", (10, 8), color=(50, 100, 200)).save(bmp_path, format="BMP")
    response = client.post(f"/sessions/{session_id}/open", json={"path": str(bmp_path)})
    assert response.status_code == 400
    assert "Format d'image non pris en charge" in response.json()["detail"]


# --- RAW decoding (052) ---

from conftest import CORRUPTED_RAW_FIXTURE, decodable_raw_fixtures

_FIRST_DECODABLE_RAW_FIXTURE = next(iter(decodable_raw_fixtures().values()), None)


@pytest.mark.skipif(
    _FIRST_DECODABLE_RAW_FIXTURE is None,
    reason="No decodable RAW fixture in tests/fixtures/raw/ (see README.md there)",
)
def test_open_image_with_decodable_raw_returns_200_same_shape_as_jpeg(client):
    raw_session_id = client.post("/sessions").json()["id"]
    raw_response = client.post(
        f"/sessions/{raw_session_id}/open", json={"path": str(_FIRST_DECODABLE_RAW_FIXTURE)}
    )
    assert raw_response.status_code == 200

    jpeg_session_id = client.post("/sessions").json()["id"]
    jpeg_response = client.post(
        f"/sessions/{jpeg_session_id}/open", json={"path": str(FIXTURE_IMAGE)}
    )
    assert [set(row.keys()) for row in raw_response.json()] == [
        set(row.keys()) for row in jpeg_response.json()
    ]


@pytest.mark.skipif(
    _FIRST_DECODABLE_RAW_FIXTURE is None,
    reason="No decodable RAW fixture in tests/fixtures/raw/ (see README.md there)",
)
def test_every_workflow_step_activates_on_a_raw_developed_session(client):
    session_id = client.post("/sessions").json()["id"]
    open_response = client.post(
        f"/sessions/{session_id}/open", json={"path": str(_FIRST_DECODABLE_RAW_FIXTURE)}
    )
    assert open_response.status_code == 200

    rows = client.get(f"/sessions/{session_id}/workflow").json()
    for index in range(len(rows)):
        response = client.post(f"/sessions/{session_id}/steps/{index}/activate")
        assert response.status_code == 200, response.text


def test_open_image_with_corrupted_raw_returns_400_raw_not_decodable(client):
    session_id = client.post("/sessions").json()["id"]
    response = client.post(
        f"/sessions/{session_id}/open", json={"path": str(CORRUPTED_RAW_FIXTURE)}
    )
    assert response.status_code == 400
    assert "Format d'image non pris en charge" not in response.json()["detail"]


# --- Two sessions never interfere (the whole point of Phase 1) ---


def test_two_sessions_stay_independent(client):
    session_a = _open(client)
    session_b = _open(client)

    client.post(f"/sessions/{session_a}/steps/1/select", json={"identifier": "16:9"})

    rows_a = client.get(f"/sessions/{session_a}/workflow").json()
    rows_b = client.get(f"/sessions/{session_b}/workflow").json()
    assert rows_a[1]["selected_vignette_identifier"] == "16:9"
    assert rows_b[1]["selected_vignette_identifier"] == "neutral"


# --- Select / activate ---


def test_select_vignette_records_choice_and_activates_that_row(client):
    session_id = _open(client)
    response = client.post(f"/sessions/{session_id}/steps/1/select", json={"identifier": "16:9"})
    assert response.status_code == 200
    rows = response.json()
    assert rows[1]["selected_vignette_identifier"] == "16:9"


def test_select_vignette_out_of_range_step_returns_400(client):
    session_id = _open(client)
    response = client.post(f"/sessions/{session_id}/steps/999/select", json={"identifier": "neutral"})
    assert response.status_code == 400


def test_select_color_splash_vignette_applies_immediately_like_any_other_row(client):
    # Feature 046 (constitution v1.5.0): Color Splash is row index 3 -- geometry(0),
    # framing(1), film(2), color_splash(3). Selecting a preset there goes through the exact
    # same generic single-click select/apply endpoint as every other row -- no Zoom view
    # required (FR-002).
    color_splash_index = [row.identifier for row in WORKFLOW_CONFIG.rows].index("color_splash")
    session_id = _open(client)
    response = client.post(f"/sessions/{session_id}/steps/{color_splash_index}/select", json={"identifier": "Rouge"})
    assert response.status_code == 200
    rows = response.json()
    assert rows[color_splash_index]["selected_vignette_identifier"] == "Rouge"


def test_color_splash_row_has_zoom_and_zoom_open_returns_populated_hue_ranges(client):
    color_splash_index = [row.identifier for row in WORKFLOW_CONFIG.rows].index("color_splash")
    session_id = _open(client)

    rows = client.get(f"/sessions/{session_id}/workflow").json()
    assert rows[color_splash_index]["has_zoom"] is True
    # Film's own row must still report has_zoom too -- non-regression for the row this
    # mechanism was generalized away from (Filmstrip.tsx used to hardcode label == "Film").
    film_index = [row.identifier for row in WORKFLOW_CONFIG.rows].index("film")
    assert rows[film_index]["has_zoom"] is True
    # A row with no addon at all must not falsely report has_zoom -- see the dedicated
    # test_row_without_any_addon_reports_has_zoom_false below ("vignette" moved out of this
    # group in feature 044, vignetting addon, 2 real zoom parameters -- see
    # test_vignette_row_has_zoom_below).

    client.post(f"/sessions/{session_id}/steps/{color_splash_index}/select", json={"identifier": "Rouge"})
    response = client.post(f"/sessions/{session_id}/zoom/{color_splash_index}/open", json={"identifier": "Rouge"})
    assert response.status_code == 200
    zoom_state = response.json()
    assert len(zoom_state["hue_ranges"]) == 3
    range_1 = next(r for r in zoom_state["hue_ranges"] if r["identifier"] == "range_1")
    assert range_1["hue_value"] == 0.0
    assert range_1["hue_minimum"] == 0.0
    assert range_1["hue_maximum"] == 360.0


def test_row_without_any_addon_reports_has_zoom_false(client, monkeypatch):
    # No row in the real shipped config is addon-less anymore since "finishing" (spec 045,
    # never implemented) was removed 2026-07-31 -- synthesize one instead of relying on that
    # coincidence, so this regression stays covered independently of the real config's contents.
    addonless_index = _patch_workflow_config_with_addonless_row(monkeypatch)
    session_id = _open(client)
    rows = client.get(f"/sessions/{session_id}/workflow").json()
    assert rows[addonless_index]["has_zoom"] is False


def test_color_splash_reloaded_malformed_recipe_falls_back_without_failing_project_load(client, tmp_path):
    # Mirrors the established Qt-path precedent (test_film_reloaded_malformed_intensity_falls_
    # back_to_neutral_render in test_filmstrip_wiring.py) for the API/web path: a recipe with
    # corrupted color_splash parameters -- e.g. a hand-edited or partially-truncated JSON file --
    # must never fail the whole project load (FR-017), even though every range_N_enabled flag is
    # lost/unreadable, the exact corruption color_splash.py's own early-return guards against.
    color_splash_identifier = "color_splash"
    session_id = _open(client)
    source = client.get(f"/sessions/{session_id}").json()["source"]
    row_identifiers = [row.identifier for row in WORKFLOW_CONFIG.rows]

    from lumaflow.persistence.recipe import SCHEMA_VERSION

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": {"filename": source["filename"], "width": source["width"], "height": source["height"]},
        "steps": [
            {
                "step_identifier": row_identifier,
                "thumbnail_identifier": "Rouge" if row_identifier == color_splash_identifier else "neutral",
                "parameters": (
                    {"range_1_enabled": "not-a-number", "range_1_hue_center": None}
                    if row_identifier == color_splash_identifier
                    else {}
                ),
            }
            for row_identifier in row_identifiers
        ],
    }
    recipe_path = tmp_path / "corrupted_color_splash.json"
    recipe_path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(recipe_path)})
    assert response.status_code == 200  # malformed color_splash parameters never fail project load
    rows = response.json()["rows"]
    color_splash_row = rows[row_identifiers.index(color_splash_identifier)]
    assert color_splash_row["selected_vignette_identifier"] == "Rouge"


def test_light_reloaded_malformed_recipe_falls_back_per_key_without_failing_project_load(client, tmp_path):
    # Feature 043 (FR-014): a recipe with a malformed value on ONE of exposure/shadows/highlights
    # must never fail the whole project load, and the other two keys still apply -- distinct from
    # color_splash's all-or-nothing fallback above (light.py's per-key independence).
    light_identifier = "light"
    session_id = _open(client)
    source = client.get(f"/sessions/{session_id}").json()["source"]
    row_identifiers = [row.identifier for row in WORKFLOW_CONFIG.rows]

    from lumaflow.persistence.recipe import SCHEMA_VERSION

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": {"filename": source["filename"], "width": source["width"], "height": source["height"]},
        "steps": [
            {
                "step_identifier": row_identifier,
                "thumbnail_identifier": "Balance" if row_identifier == light_identifier else "neutral",
                "parameters": (
                    {"exposure": "not-a-number", "shadows": 0.4, "highlights": -0.3}
                    if row_identifier == light_identifier
                    else {}
                ),
            }
            for row_identifier in row_identifiers
        ],
    }
    recipe_path = tmp_path / "corrupted_light.json"
    recipe_path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(recipe_path)})
    assert response.status_code == 200  # malformed exposure never fails project load
    rows = response.json()["rows"]
    light_row = rows[row_identifiers.index(light_identifier)]
    assert light_row["selected_vignette_identifier"] == "Balance"


def test_manual_light_edit_after_balance_updates_only_that_value(client):
    # Edge Case: manually adjusting one slider (Shadows) after a Balance click updates only that
    # value going forward -- Exposure and Highlights remain at Balance's own values.
    session_id = _open(client)
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Balance"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Balance"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "shadows", "value": 0.9})
    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Balance"}
    ).json()
    values = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    assert values["shadows"] == 0.9
    assert values["exposure"] == _BALANCE_GRADE.exposure
    assert values["highlights"] == _BALANCE_GRADE.highlights


def test_clicking_neutral_after_balance_and_manual_edits_fully_clears_light_values(client):
    session_id = _open(client)
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Balance"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Balance"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "shadows", "value": 0.9})
    client.post(f"/sessions/{session_id}/zoom/confirm")

    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "neutral"})
    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "neutral"}
    ).json()
    values = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    assert values["exposure"] == 0.0
    assert values["shadows"] == 0.0
    assert values["highlights"] == 0.0


def test_confirm_light_values_then_reload_recipe_reproduces_identical_adjusted_pixels(client, tmp_path):
    # SC-007: a reloaded recipe with confirmed exposure/shadows/highlights values reproduces the
    # identical adjusted pixels, not just the stored numbers.
    session_id = _open(client)
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "neutral"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "neutral"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "exposure", "value": 0.7})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "shadows", "value": 0.5})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "highlights", "value": -0.4})
    confirm_response = client.post(f"/sessions/{session_id}/zoom/confirm")
    assert confirm_response.status_code == 200

    original_preview = client.get(f"/sessions/{session_id}/preview").content

    dest = tmp_path / "light_recipe.json"
    save_response = client.post(f"/sessions/{session_id}/recipe/save", json={"dest_path": str(dest)})
    assert save_response.status_code == 200

    session_id_2 = _open(client)
    load_response = client.post(f"/sessions/{session_id_2}/recipe/load", json={"path": str(dest)})
    assert load_response.status_code == 200

    reloaded_preview = client.get(f"/sessions/{session_id_2}/preview").content
    assert reloaded_preview == original_preview

    reopened = client.post(
        f"/sessions/{session_id_2}/zoom/{step_index}/open", json={"identifier": "neutral"}
    ).json()
    values = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    assert values["exposure"] == 0.7
    assert values["shadows"] == 0.5
    assert values["highlights"] == -0.4


# --- Vignetting (feature 044, extended by the "dynamic aids" interactive-shape pass): Round
# Central / Linear Top+Bottom presets, Intensity/Progressivity/Feather Width sliders, and 8
# interactive geometry fields (center/radius/offsets/rotation) -- no more static overlay, the
# shape itself is now user-editable. ---


def _vignette_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "vignette")


def test_select_round_central_vignette_applies_immediately_no_zoom_involved(client):
    session_id = _open(client)
    step_index = _vignette_step_index()
    baseline_preview = client.get(f"/sessions/{session_id}/preview").content

    response = client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Round Central"})
    assert response.status_code == 200
    rows = response.json()
    assert rows[step_index]["selected_vignette_identifier"] == "Round Central"

    updated_preview = client.get(f"/sessions/{session_id}/preview").content
    assert updated_preview != baseline_preview


def test_select_linear_top_bottom_then_neutral_restores_the_unmodified_image(client):
    session_id = _open(client)
    step_index = _vignette_step_index()
    baseline_preview = client.get(f"/sessions/{session_id}/preview").content

    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Linear Top+Bottom"})
    darkened_preview = client.get(f"/sessions/{session_id}/preview").content
    assert darkened_preview != baseline_preview

    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "neutral"})
    restored_preview = client.get(f"/sessions/{session_id}/preview").content
    assert restored_preview == baseline_preview


def test_open_zoom_on_round_central_returns_sliders_and_no_overlay(client):
    session_id = _open(client)
    step_index = _vignette_step_index()
    response = client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Round Central"})
    assert response.status_code == 200, response.text
    body = response.json()

    sliders = {s["identifier"]: s for s in body["sliders"]}
    assert sliders["intensity"]["value"] == 0.35
    assert sliders["progressivity"]["value"] == 0.6
    # The 8 geometry/feather fields always resolve to their own declared defaults for a freshly
    # selected preset (no override yet) -- the static gradient_lines overlay is gone (see
    # vignetting.py's module docstring: it would otherwise show a stale, now-editable position).
    assert sliders["center_x"]["value"] == 0.5
    assert sliders["center_y"]["value"] == 0.5
    assert sliders["radius_x"]["value"] == 0.85
    assert sliders["radius_y"]["value"] == 0.85
    assert sliders["top_offset"]["value"] == 0.6
    assert sliders["bottom_offset"]["value"] == 0.6
    assert sliders["rotation_angle"]["value"] == 0.0
    assert sliders["feather_width"]["value"] == 12.0
    assert body["overlays"] == []


def test_switching_directly_between_vignetting_presets_resets_to_the_new_presets_own_defaults(client):
    session_id = _open(client)
    step_index = _vignette_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Round Central"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Round Central"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "intensity", "value": 0.9})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "progressivity", "value": 0.1})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "radius_x", "value": 1.5})
    client.post(f"/sessions/{session_id}/zoom/confirm")

    # Switching directly to Linear Top+Bottom (without returning to Neutral first) must reset
    # both values to ITS OWN defaults, not carry over Round Central's tuned 0.9/0.1/1.5.
    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Linear Top+Bottom"}
    ).json()
    sliders = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    assert sliders["intensity"] == 0.3
    assert sliders["progressivity"] == 0.6
    assert sliders["top_offset"] == 0.6
    assert sliders["bottom_offset"] == 0.6


def test_dragging_vignetting_sliders_live_updates_the_preview(client):
    session_id = _open(client)
    step_index = _vignette_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Round Central"})
    baseline_after = client.get(f"/sessions/{session_id}/zoom/after").content

    response = client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "intensity", "value": 0.9})
    assert response.status_code == 200
    assert response.content != baseline_after

    after_intensity_change = client.get(f"/sessions/{session_id}/zoom/after").content
    response = client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "progressivity", "value": 0.05})
    assert response.status_code == 200
    assert response.content != after_intensity_change


def test_cancel_zoom_discards_vignetting_parameter_edits(client):
    session_id = _open(client)
    step_index = _vignette_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Round Central"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Round Central"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "intensity", "value": 0.95})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "rotation_angle", "value": 45.0})
    response = client.post(f"/sessions/{session_id}/zoom/cancel")
    assert response.status_code == 200

    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Round Central"}
    ).json()
    sliders = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    assert sliders["intensity"] == 0.35
    assert sliders["progressivity"] == 0.6
    assert sliders["rotation_angle"] == 0.0


def test_confirm_vignetting_values_then_reload_recipe_reproduces_identical_darkened_pixels(client, tmp_path):
    # SC-007: a reloaded recipe with a confirmed preset/intensity/progressivity/geometry
    # reproduces the identical darkened pixels, not just the stored numbers.
    session_id = _open(client)
    step_index = _vignette_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Round Central"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Round Central"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "intensity", "value": 0.7})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "progressivity", "value": 0.2})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "rotation_angle", "value": 30.0})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "center_x", "value": 0.4})
    confirm_response = client.post(f"/sessions/{session_id}/zoom/confirm")
    assert confirm_response.status_code == 200

    original_preview = client.get(f"/sessions/{session_id}/preview").content

    dest = tmp_path / "vignetting_recipe.json"
    save_response = client.post(f"/sessions/{session_id}/recipe/save", json={"dest_path": str(dest)})
    assert save_response.status_code == 200

    session_id_2 = _open(client)
    load_response = client.post(f"/sessions/{session_id_2}/recipe/load", json={"path": str(dest)})
    assert load_response.status_code == 200

    reloaded_preview = client.get(f"/sessions/{session_id_2}/preview").content
    assert reloaded_preview == original_preview

    reopened = client.post(
        f"/sessions/{session_id_2}/zoom/{step_index}/open", json={"identifier": "Round Central"}
    ).json()
    sliders = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    assert sliders["intensity"] == 0.7
    assert sliders["progressivity"] == 0.2
    assert sliders["rotation_angle"] == 30.0
    assert sliders["center_x"] == 0.4


def test_batched_commit_updates_all_eight_geometry_fields_in_one_render(client, monkeypatch):
    session_id = _open(client)
    step_index = _vignette_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Round Central"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Round Central"})

    render_calls = []
    original_render_zoom_after = api_app.render_zoom_after

    def _counting_render_zoom_after(session, **kwargs):
        render_calls.append(1)
        return original_render_zoom_after(session, **kwargs)

    monkeypatch.setattr(api_app, "render_zoom_after", _counting_render_zoom_after)

    response = client.post(
        f"/sessions/{session_id}/zoom/parameters",
        json={"updates": [
            {"identifier": "center_x", "value": 0.3}, {"identifier": "center_y", "value": 0.4},
            {"identifier": "radius_x", "value": 0.5}, {"identifier": "radius_y", "value": 0.6},
            {"identifier": "top_offset", "value": 0.7}, {"identifier": "bottom_offset", "value": 0.8},
            {"identifier": "rotation_angle", "value": 20.0}, {"identifier": "feather_width", "value": 5.0},
        ]},
    )
    assert response.status_code == 200
    assert len(render_calls) == 1

    session = api_app._get_session(session_id)
    step = session.pipeline._steps[step_index]
    assert step.parameters.values["center_x"] == 0.3
    assert step.parameters.values["feather_width"] == 5.0


def test_vignetting_reloaded_malformed_recipe_falls_back_to_neutral_without_failing_project_load(client, tmp_path):
    # FR-014: a recipe with a malformed/unavailable shape, or a malformed/out-of-range intensity
    # or progressivity with an otherwise-valid shape, loads successfully and that step renders as
    # Neutral -- the rest of the project is unaffected (all-or-nothing coupled-triple fallback,
    # Decision 2 -- like Film/Color Splash, unlike Light's per-key one).
    vignette_identifier = "vignette"
    session_id = _open(client)
    source = client.get(f"/sessions/{session_id}").json()["source"]
    row_identifiers = [row.identifier for row in WORKFLOW_CONFIG.rows]

    from lumaflow.persistence.recipe import SCHEMA_VERSION

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": {"filename": source["filename"], "width": source["width"], "height": source["height"]},
        "steps": [
            {
                "step_identifier": row_identifier,
                "thumbnail_identifier": "Round Central" if row_identifier == vignette_identifier else "neutral",
                "parameters": (
                    {"shape": "round_central", "intensity": "not-a-number", "progressivity": 0.6}
                    if row_identifier == vignette_identifier
                    else {}
                ),
            }
            for row_identifier in row_identifiers
        ],
    }
    recipe_path = tmp_path / "corrupted_vignetting.json"
    recipe_path.write_text(json.dumps(payload), encoding="utf-8")

    baseline_session_id = _open(client)
    baseline_preview = client.get(f"/sessions/{baseline_session_id}/preview").content

    response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(recipe_path)})
    assert response.status_code == 200  # malformed vignetting parameters never fail project load
    rows = response.json()["rows"]
    vignette_row = rows[row_identifiers.index(vignette_identifier)]
    assert vignette_row["selected_vignette_identifier"] == "Round Central"

    reloaded_preview = client.get(f"/sessions/{session_id}/preview").content
    assert reloaded_preview == baseline_preview  # renders as Neutral despite the malformed intensity


def test_vignetting_reloaded_malformed_geometry_field_does_not_fall_back_to_neutral(client, tmp_path):
    # Unlike shape/intensity/progressivity above, a malformed GEOMETRY field must NOT collapse the
    # whole step to Neutral -- it falls back per-key (its own default/clamp), and the vignette
    # still renders (distinguishes the two coexisting fallback regimes at the API level too).
    vignette_identifier = "vignette"
    session_id = _open(client)
    source = client.get(f"/sessions/{session_id}").json()["source"]
    row_identifiers = [row.identifier for row in WORKFLOW_CONFIG.rows]

    from lumaflow.persistence.recipe import SCHEMA_VERSION

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": {"filename": source["filename"], "width": source["width"], "height": source["height"]},
        "steps": [
            {
                "step_identifier": row_identifier,
                "thumbnail_identifier": "Round Central" if row_identifier == vignette_identifier else "neutral",
                "parameters": (
                    {
                        "shape": "round_central", "intensity": 0.9, "progressivity": 0.6,
                        "radius_x": "not-a-number", "rotation_angle": 999.0,
                    }
                    if row_identifier == vignette_identifier
                    else {}
                ),
            }
            for row_identifier in row_identifiers
        ],
    }
    recipe_path = tmp_path / "corrupted_vignetting_geometry.json"
    recipe_path.write_text(json.dumps(payload), encoding="utf-8")

    baseline_session_id = _open(client)
    baseline_preview = client.get(f"/sessions/{baseline_session_id}/preview").content

    response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(recipe_path)})
    assert response.status_code == 200
    rows = response.json()["rows"]
    vignette_row = rows[row_identifiers.index(vignette_identifier)]
    assert vignette_row["selected_vignette_identifier"] == "Round Central"

    reloaded_preview = client.get(f"/sessions/{session_id}/preview").content
    assert reloaded_preview != baseline_preview  # still a real, applied vignette -- not Neutral


def test_activate_step_switches_active_row_without_changing_selection(client):
    session_id = _open(client)
    response = client.post(f"/sessions/{session_id}/steps/1/activate")
    assert response.status_code == 200
    rows = response.json()
    assert rows[1]["selected_vignette_identifier"] == "neutral"


def test_activate_step_endpoint_schedules_a_row_before_precompute(client):
    """PERF-ZOOM-RENDER-PLAN.md étape 4 -- activating a row (via HTTP, not the plain session
    function) warms session.step_render_cache for it. step_index=1 ("film") has step 0 strictly
    before it, so this isn't the trivially-skipped step_index==0 case."""
    session_id = _open(client)
    response = client.post(f"/sessions/{session_id}/steps/1/activate")
    assert response.status_code == 200

    session = api_app._get_session(session_id)
    assert session.step_render_cache.get(0) is not None


def test_select_vignette_endpoint_schedules_a_row_before_precompute(client):
    session_id = _open(client)
    response = client.post(f"/sessions/{session_id}/steps/1/select", json={"identifier": "Classic Chrome"})
    assert response.status_code == 200

    session = api_app._get_session(session_id)
    assert session.step_render_cache.get(0) is not None


def test_open_zoom_after_activating_the_row_reuses_the_precomputed_before_image(client):
    """End-to-end: select Film's vignette, then activate the Light row over HTTP -- exactly what
    clicking/arrow-keying onto Light does in the real UI, which is what schedules the "before
    Light" précalcul (keyed by the ACTIVE row, i.e. the one about to be zoomed into, not the one
    just selected). Opening Zoom on Light right after must then reuse it: Film's own processor
    must NOT run a second time to produce Light's "Avant" pane."""
    session_id = _open(client)
    film_index = _film_step_index()
    light_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{film_index}/select", json={"identifier": "Classic Chrome"})
    client.post(f"/sessions/{session_id}/steps/{light_index}/activate")
    session = api_app._get_session(session_id)
    assert session.step_render_cache.get(light_index - 1) is not None

    # open_zoom's own internal select_vignette/refresh_workflow legitimately calls Film's
    # processor to recompute thumbnail/preview states, unrelated to the étape 4 précalcul -- same
    # reasoning as test_row_before_precompute.py. Install the counter AFTER it, then isolate
    # render_zoom_before's own behaviour via the dedicated GET /zoom/before endpoint.
    response = client.post(f"/sessions/{session_id}/zoom/{light_index}/open", json={"identifier": "Dramatique"})
    assert response.status_code == 200

    film_calls = [0]
    original = session.pipeline._steps[film_index].processor

    def _wrapped(image, params):
        film_calls[0] += 1
        return original(image, params)

    session.pipeline._steps[film_index].processor = _wrapped

    before_response = client.get(f"/sessions/{session_id}/zoom/before")
    assert before_response.status_code == 200
    assert film_calls[0] == 0


def test_select_before_open_returns_400_not_500(client):
    session_id = client.post("/sessions").json()["id"]
    response = client.post(f"/sessions/{session_id}/steps/0/select", json={"identifier": "neutral"})
    assert response.status_code == 400


# --- Thumbnails ---


def test_thumbnail_for_unresolved_row_returns_404(client):
    session_id = _open(client)
    # Row far outside the visible 3-row window has no computed states yet.
    response = client.get(f"/sessions/{session_id}/thumbnails/5/neutral")
    assert response.status_code == 404


def test_thumbnail_for_unknown_identifier_returns_404(client):
    session_id = _open(client)
    response = client.get(f"/sessions/{session_id}/thumbnails/0/not-a-real-preset")
    assert response.status_code == 404


# --- Export ---


def test_export_writes_a_real_file(client, tmp_path):
    session_id = _open(client)
    dest = tmp_path / "out.jpg"
    response = client.post(
        f"/sessions/{session_id}/export",
        json={"dest_path": str(dest), "image_format": "JPEG"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert dest.exists()


def test_export_without_image_loaded_returns_400(client, tmp_path):
    session_id = client.post("/sessions").json()["id"]
    response = client.post(
        f"/sessions/{session_id}/export",
        json={"dest_path": str(tmp_path / "out.jpg"), "image_format": "JPEG"},
    )
    assert response.status_code == 400


def test_export_to_a_nonexistent_destination_directory_returns_400_not_500(client, tmp_path):
    # Feature 050 (FR-004/US2): export_image_endpoint never caught ImageIOError at all -- any
    # export I/O failure (here, export_image's tempfile.mkstemp raising FileNotFoundError because
    # dest_path.parent doesn't exist) crashed as an unhandled 500 "Internal Server Error" instead
    # of the same clean, categorized 400 every other endpoint in this module already returns.
    session_id = _open(client)
    dest = tmp_path / "nonexistent-subdir" / "out.png"
    response = client.post(
        f"/sessions/{session_id}/export",
        json={"dest_path": str(dest), "image_format": "PNG"},
    )
    assert response.status_code == 400


def test_export_onto_existing_file_requires_force(client, tmp_path):
    session_id = _open(client)
    dest = tmp_path / "out.jpg"
    dest.write_bytes(b"not a real image, just occupying the path")

    response = client.post(
        f"/sessions/{session_id}/export",
        json={"dest_path": str(dest), "image_format": "JPEG"},
    )
    assert response.status_code == 409

    response = client.post(
        f"/sessions/{session_id}/export",
        json={"dest_path": str(dest), "image_format": "JPEG", "force": True},
    )
    assert response.status_code == 200


def test_unedited_jpeg_export_stays_close_to_source_size(client, tmp_path):
    """Correctif : un export sans aucune modification ne doit plus forcer
    qualité=100/subsampling=0 et gonfler la taille du fichier plusieurs fois
    par rapport à la source (bug signalé par l'utilisateur)."""
    array = numpy.fromfunction(
        lambda y, x, c: (x * 4 + y * 2 + c * 60) % 256,
        (64, 64, 3),
        dtype=numpy.int64,
    ).astype(numpy.uint8)
    source_path = tmp_path / "source.jpg"
    Image.fromarray(array, mode="RGB").save(source_path, format="JPEG", quality=82, subsampling=2)
    source_size = source_path.stat().st_size

    session_id = client.post("/sessions").json()["id"]
    open_response = client.post(f"/sessions/{session_id}/open", json={"path": str(source_path)})
    assert open_response.status_code == 200, open_response.text

    dest = tmp_path / "reexported.jpg"
    export_response = client.post(
        f"/sessions/{session_id}/export",
        json={"dest_path": str(dest), "image_format": "JPEG"},
    )
    assert export_response.status_code == 200, export_response.text
    assert dest.stat().st_size <= source_size * 2


# --- Direct session.py unit coverage (no HTTP layer) ---


def test_session_module_open_image_builds_a_pipeline_step_per_workflow_row():
    session = create_session()
    open_image(session, FIXTURE_IMAGE)
    assert session.pipeline is not None
    from lumaflow.api.session import WORKFLOW_ROWS
    assert len(session.pipeline._steps) == len(WORKFLOW_ROWS)


def test_session_module_select_vignette_resolves_neutral_crop_to_full_frame():
    # Free-form crop only (no aspect-ratio-locked presets) since the crop-frame rework --
    # "neutral" is the only remaining Framing preset, has no preset_parameters of its own (like
    # every other addon's neutral preset), and the effective crop_width/height fall back to their
    # own full-frame defaults via framing.py's resolve_zoom_values.
    session = create_session()
    open_image(session, FIXTURE_IMAGE)
    rows = select_vignette(session, 1, "neutral")
    step = session.pipeline._steps[1]
    assert step.parameters.values == {}
    from lumaflow.addons.builtin.framing import resolve_zoom_values
    effective = resolve_zoom_values(step.parameters.values)
    assert effective == {"crop_x": 0.0, "crop_y": 0.0, "crop_width": 1.0, "crop_height": 1.0}
    assert rows[1].selected_vignette_identifier == "neutral"


# --- Native file dialog (Ouvrir) ---


def test_open_image_dialog_returns_chosen_path(client, monkeypatch):
    monkeypatch.setattr(api_app.filedialog, "askopenfilename", lambda **kwargs: str(FIXTURE_IMAGE))
    response = client.get("/dialogs/open-image")
    assert response.status_code == 200
    assert response.json() == {"path": str(FIXTURE_IMAGE)}


def test_open_image_dialog_returns_null_path_when_cancelled(client, monkeypatch):
    monkeypatch.setattr(api_app.filedialog, "askopenfilename", lambda **kwargs: "")
    response = client.get("/dialogs/open-image")
    assert response.status_code == 200
    assert response.json() == {"path": None}


def test_open_image_dialog_passes_image_filetypes(client, monkeypatch):
    captured = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(api_app.filedialog, "askopenfilename", fake_ask)
    client.get("/dialogs/open-image")
    assert "filetypes" in captured
    assert any("png" in pattern.lower() for _, pattern in captured["filetypes"])


def test_image_file_types_keeps_images_entry_first_and_unchanged(client):
    assert api_app.IMAGE_FILE_TYPES[0] == ("Images", "*.png *.jpg *.jpeg")


def test_image_file_types_includes_a_raw_entry_covering_every_raw_extension():
    from lumaflow.engine import raw_formats

    raw_entries = [pattern for label, pattern in api_app.IMAGE_FILE_TYPES if label == "RAW"]
    assert len(raw_entries) == 1
    for ext in raw_formats.RAW_EXTENSIONS:
        assert f"*{ext}" in raw_entries[0]


def test_open_image_dialog_defaults_to_configured_open_image_directory(client, monkeypatch, isolated_preferences_path, tmp_path):
    open_dir = tmp_path / "open"
    open_dir.mkdir()
    client.put(
        "/preferences",
        json={
            "menu_position": "left", "menu_collapsed": False, "row_spacing_px": 8,
            "vignette_margin_px": 8, "attenuated_opacity_percent": 80, "row_horizontal_margin_px": 8,
            "zoom_min_percent": 20, "zoom_max_percent": 400,
            "export_jpeg_quality": 90, "guide_limit_color": "#E3A75E", "guide_overlay_color": "#FFFFFF",
            "accent_color": "#E3A75E",
            "open_image_directory": str(open_dir),
        },
    )
    captured = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(api_app.filedialog, "askopenfilename", fake_ask)
    client.get("/dialogs/open-image")
    assert captured["initialdir"] == str(open_dir)


def test_open_image_dialog_initialdir_empty_when_no_directory_configured(client, monkeypatch, isolated_preferences_path):
    captured = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(api_app.filedialog, "askopenfilename", fake_ask)
    client.get("/dialogs/open-image")
    assert captured["initialdir"] == ""


# --- Native file dialog (Exporter une image) ---


def test_export_image_dialog_defaults_to_configured_export_image_directory(client, monkeypatch, isolated_preferences_path, tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    client.put(
        "/preferences",
        json={
            "menu_position": "left", "menu_collapsed": False, "row_spacing_px": 8,
            "vignette_margin_px": 8, "attenuated_opacity_percent": 80, "row_horizontal_margin_px": 8,
            "zoom_min_percent": 20, "zoom_max_percent": 400,
            "export_jpeg_quality": 90, "guide_limit_color": "#E3A75E", "guide_overlay_color": "#FFFFFF",
            "accent_color": "#E3A75E",
            "export_image_directory": str(export_dir),
        },
    )
    captured = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(api_app.filedialog, "asksaveasfilename", fake_ask)
    client.get("/dialogs/export-image")
    assert captured["initialdir"] == str(export_dir)


def test_export_image_dialog_initialdir_empty_when_no_directory_configured(client, monkeypatch, isolated_preferences_path):
    captured = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(api_app.filedialog, "asksaveasfilename", fake_ask)
    client.get("/dialogs/export-image")
    assert captured["initialdir"] == ""


# --- Preferences ---


def test_get_preferences_returns_defaults_when_no_file_exists(client, isolated_preferences_path):
    response = client.get("/preferences")
    assert response.status_code == 200
    body = response.json()
    assert body["menu_position"] == "left"
    assert body["menu_collapsed"] is False


def test_put_preferences_persists_and_is_read_back(client, isolated_preferences_path):
    payload = {
        "menu_position": "top",
        "menu_collapsed": True,
        "row_spacing_px": 10,
        "vignette_margin_px": 10,
        "attenuated_opacity_percent": 70,
        "row_horizontal_margin_px": 10,
        "zoom_min_percent": 25,
        "zoom_max_percent": 500,
        "export_jpeg_quality": 75,
        "guide_limit_color": "#123ABC",
        "guide_overlay_color": "#ABCDEF",
        "accent_color": "#123ABC",
        "presets_directory": None,
        "open_image_directory": None,
        "export_image_directory": None,
        "workflow_config_source_path": None,
    }
    put_response = client.put("/preferences", json=payload)
    assert put_response.status_code == 200
    assert put_response.json() == payload
    assert isolated_preferences_path.exists()

    get_response = client.get("/preferences")
    assert get_response.json() == payload


def test_put_preferences_out_of_range_value_falls_back_to_default(client, isolated_preferences_path):
    payload = {
        "menu_position": "top",
        "menu_collapsed": True,
        "row_spacing_px": 9999,  # out of the [0, 40] bound
        "vignette_margin_px": 10,
        "attenuated_opacity_percent": 70,
        "row_horizontal_margin_px": 10,
        "zoom_min_percent": 25,
        "zoom_max_percent": 500,
        "export_jpeg_quality": 75,
        "guide_limit_color": "#123ABC",
        "guide_overlay_color": "#ABCDEF",
        "accent_color": "#123ABC",
        "presets_directory": None,
        "open_image_directory": None,
        "export_image_directory": None,
    }
    response = client.put("/preferences", json=payload)
    assert response.status_code == 200
    assert response.json()["row_spacing_px"] == 8  # DEFAULT_ROW_SPACING_PX


def test_put_preferences_persists_presets_directory(client, isolated_preferences_path, tmp_path):
    payload = {
        "menu_position": "left",
        "menu_collapsed": False,
        "row_spacing_px": 8,
        "vignette_margin_px": 8,
        "attenuated_opacity_percent": 80,
        "row_horizontal_margin_px": 8,
        "zoom_min_percent": 20,
        "zoom_max_percent": 400,
        "export_jpeg_quality": 90,
        "guide_limit_color": "#E3A75E",
        "guide_overlay_color": "#FFFFFF",
        "accent_color": "#E3A75E",
        "presets_directory": str(tmp_path),
    }
    put_response = client.put("/preferences", json=payload)
    assert put_response.status_code == 200
    assert put_response.json()["presets_directory"] == str(tmp_path)

    get_response = client.get("/preferences")
    assert get_response.json()["presets_directory"] == str(tmp_path)


def test_put_preferences_non_string_presets_directory_falls_back_to_none(client, isolated_preferences_path):
    isolated_preferences_path.write_text(
        json.dumps({"version": 1, "presets_directory": 42}), encoding="utf-8"
    )
    response = client.get("/preferences")
    assert response.status_code == 200
    assert response.json()["presets_directory"] is None


def test_put_preferences_persists_open_and_export_image_directories(client, isolated_preferences_path, tmp_path):
    open_dir = tmp_path / "open"
    export_dir = tmp_path / "export"
    payload = {
        "menu_position": "left",
        "menu_collapsed": False,
        "row_spacing_px": 8,
        "vignette_margin_px": 8,
        "attenuated_opacity_percent": 80,
        "row_horizontal_margin_px": 8,
        "zoom_min_percent": 20,
        "zoom_max_percent": 400,
        "export_jpeg_quality": 90,
        "guide_limit_color": "#E3A75E",
        "guide_overlay_color": "#FFFFFF",
        "accent_color": "#E3A75E",
        "open_image_directory": str(open_dir),
        "export_image_directory": str(export_dir),
    }
    put_response = client.put("/preferences", json=payload)
    assert put_response.status_code == 200
    assert put_response.json()["open_image_directory"] == str(open_dir)
    assert put_response.json()["export_image_directory"] == str(export_dir)

    get_response = client.get("/preferences")
    assert get_response.json()["open_image_directory"] == str(open_dir)
    assert get_response.json()["export_image_directory"] == str(export_dir)


# --- Directory picker dialog (Préférences > Général > Dossier des presets) ---


def test_select_presets_directory_dialog_returns_chosen_path(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api_app.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    response = client.get("/dialogs/select-presets-directory")
    assert response.status_code == 200
    assert response.json() == {"path": str(tmp_path)}


def test_select_presets_directory_dialog_returns_null_path_when_cancelled(client, monkeypatch):
    monkeypatch.setattr(api_app.filedialog, "askdirectory", lambda **kwargs: "")
    response = client.get("/dialogs/select-presets-directory")
    assert response.status_code == 200
    assert response.json() == {"path": None}


def test_select_open_image_directory_dialog_returns_chosen_path(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api_app.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    response = client.get("/dialogs/select-open-image-directory")
    assert response.status_code == 200
    assert response.json() == {"path": str(tmp_path)}


def test_select_export_image_directory_dialog_returns_chosen_path(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api_app.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    response = client.get("/dialogs/select-export-image-directory")
    assert response.status_code == 200
    assert response.json() == {"path": str(tmp_path)}


# --- Load/save-recipe dialogs default to the configured presets directory (2026-08-05) ---


def test_load_recipe_dialog_defaults_to_configured_presets_directory(client, monkeypatch, isolated_preferences_path, tmp_path):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    client.put(
        "/preferences",
        json={
            "menu_position": "left", "menu_collapsed": False, "row_spacing_px": 8,
            "vignette_margin_px": 8, "attenuated_opacity_percent": 80, "row_horizontal_margin_px": 8,
            "zoom_min_percent": 20, "zoom_max_percent": 400,
            "export_jpeg_quality": 90, "guide_limit_color": "#E3A75E", "guide_overlay_color": "#FFFFFF",
            "accent_color": "#E3A75E",
            "presets_directory": str(presets_dir),
        },
    )
    captured = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(api_app.filedialog, "askopenfilename", fake_ask)
    client.get("/dialogs/load-recipe")
    assert captured["initialdir"] == str(presets_dir)


def test_load_recipe_dialog_initialdir_empty_when_no_directory_configured(client, monkeypatch, isolated_preferences_path):
    captured = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(api_app.filedialog, "askopenfilename", fake_ask)
    client.get("/dialogs/load-recipe")
    assert captured["initialdir"] == ""


def test_save_recipe_dialog_defaults_to_configured_presets_directory(client, monkeypatch, isolated_preferences_path, tmp_path):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    client.put(
        "/preferences",
        json={
            "menu_position": "left", "menu_collapsed": False, "row_spacing_px": 8,
            "vignette_margin_px": 8, "attenuated_opacity_percent": 80, "row_horizontal_margin_px": 8,
            "zoom_min_percent": 20, "zoom_max_percent": 400,
            "export_jpeg_quality": 90, "guide_limit_color": "#E3A75E", "guide_overlay_color": "#FFFFFF",
            "accent_color": "#E3A75E",
            "presets_directory": str(presets_dir),
        },
    )
    captured = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(api_app.filedialog, "asksaveasfilename", fake_ask)
    client.get("/dialogs/save-recipe")
    assert captured["initialdir"] == str(presets_dir)


def test_save_recipe_dialog_initialdir_empty_when_no_directory_configured(client, monkeypatch, isolated_preferences_path):
    captured = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(api_app.filedialog, "asksaveasfilename", fake_ask)
    client.get("/dialogs/save-recipe")
    assert captured["initialdir"] == ""


def test_save_recipe_dialog_initialdir_empty_when_configured_directory_missing(client, monkeypatch, isolated_preferences_path, tmp_path):
    client.put(
        "/preferences",
        json={
            "menu_position": "left", "menu_collapsed": False, "row_spacing_px": 8,
            "vignette_margin_px": 8, "attenuated_opacity_percent": 80, "row_horizontal_margin_px": 8,
            "zoom_min_percent": 20, "zoom_max_percent": 400,
            "export_jpeg_quality": 90, "guide_limit_color": "#E3A75E", "guide_overlay_color": "#FFFFFF",
            "accent_color": "#E3A75E",
            "presets_directory": str(tmp_path / "does-not-exist"),
        },
    )
    captured = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(api_app.filedialog, "asksaveasfilename", fake_ask)
    client.get("/dialogs/save-recipe")
    assert captured["initialdir"] == ""


# --- Presets listing (header combobox) ---


def test_list_presets_returns_empty_when_no_directory_configured(client, isolated_preferences_path):
    response = client.get("/presets")
    assert response.status_code == 200
    assert response.json() == {"presets": []}


def test_list_presets_returns_empty_when_configured_directory_does_not_exist(client, isolated_preferences_path, tmp_path):
    client.put(
        "/preferences",
        json={
            "menu_position": "left", "menu_collapsed": False, "row_spacing_px": 8,
            "vignette_margin_px": 8, "attenuated_opacity_percent": 80, "row_horizontal_margin_px": 8,
            "zoom_min_percent": 20, "zoom_max_percent": 400,
            "export_jpeg_quality": 90, "guide_limit_color": "#E3A75E", "guide_overlay_color": "#FFFFFF",
            "accent_color": "#E3A75E",
            "presets_directory": str(tmp_path / "does-not-exist"),
        },
    )
    response = client.get("/presets")
    assert response.status_code == 200
    assert response.json() == {"presets": []}


def test_list_presets_returns_json_files_sorted_alphabetically(client, isolated_preferences_path, tmp_path):
    # A dedicated subdirectory -- isolated_preferences_path's own preferences.json also lives
    # under tmp_path, and would otherwise show up as a spurious "preferences" entry in the glob.
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    (presets_dir / "Zebra.json").write_text("{}", encoding="utf-8")
    (presets_dir / "amber.json").write_text("{}", encoding="utf-8")
    (presets_dir / "Bison.json").write_text("{}", encoding="utf-8")
    (presets_dir / "not-a-recipe.txt").write_text("ignored", encoding="utf-8")
    client.put(
        "/preferences",
        json={
            "menu_position": "left", "menu_collapsed": False, "row_spacing_px": 8,
            "vignette_margin_px": 8, "attenuated_opacity_percent": 80, "row_horizontal_margin_px": 8,
            "zoom_min_percent": 20, "zoom_max_percent": 400,
            "export_jpeg_quality": 90, "guide_limit_color": "#E3A75E", "guide_overlay_color": "#FFFFFF",
            "accent_color": "#E3A75E",
            "presets_directory": str(presets_dir),
        },
    )
    response = client.get("/presets")
    assert response.status_code == 200
    presets = response.json()["presets"]
    assert [entry["name"] for entry in presets] == ["amber", "Bison", "Zebra"]
    assert presets[0]["path"] == str(presets_dir / "amber.json")


# --- Session reset (header combobox's "Nouveau" entry) ---


def test_reset_session_clears_selections_back_to_neutral(client):
    session_id = _open(client)
    select_response = client.post(f"/sessions/{session_id}/steps/1/select", json={"identifier": "16:9"})
    assert select_response.status_code == 200, select_response.text
    assert select_response.json()[1]["selected_vignette_identifier"] != api_session.NEUTRAL_PRESET_IDENTIFIER

    reset_response = client.post(f"/sessions/{session_id}/reset")
    assert reset_response.status_code == 200, reset_response.text
    rows = reset_response.json()
    assert all(row["selected_vignette_identifier"] == api_session.NEUTRAL_PRESET_IDENTIFIER for row in rows)
    assert rows == client.get(f"/sessions/{session_id}/workflow").json()


def test_reset_session_without_image_returns_400(client):
    session_id = client.post("/sessions").json()["id"]
    response = client.post(f"/sessions/{session_id}/reset")
    assert response.status_code == 400


# --- Recipes ---


def _open_and_select(client: TestClient) -> str:
    session_id = _open(client)
    response = client.post(f"/sessions/{session_id}/steps/1/select", json={"identifier": "16:9"})
    assert response.status_code == 200, response.text
    return session_id


def test_save_recipe_writes_a_real_file_reflecting_current_selections(client, tmp_path):
    session_id = _open_and_select(client)
    dest = tmp_path / "recipe.json"
    response = client.post(f"/sessions/{session_id}/recipe/save", json={"dest_path": str(dest)})
    assert response.status_code == 200, response.text
    assert dest.exists()
    saved = json.loads(dest.read_text(encoding="utf-8"))
    assert saved["schema_version"] == SCHEMA_VERSION
    # A preset no longer references the file it was authored on (2026-08-24).
    assert "source" not in saved
    steps_by_id = {step["step_identifier"]: step for step in saved["steps"]}
    assert "film" in steps_by_id


def test_save_recipe_never_includes_geometry_or_framing(client, tmp_path):
    # Geometry/Framing corrections are image-specific and near-never portable to a different
    # photo -- excluded from every saved preset regardless of the row's current selection
    # (2026-08-24). `_open_and_select` deliberately selects framing's "16:9" first, so this test
    # fails loudly if that exclusion regresses.
    session_id = _open_and_select(client)
    dest = tmp_path / "recipe.json"
    response = client.post(f"/sessions/{session_id}/recipe/save", json={"dest_path": str(dest)})
    assert response.status_code == 200, response.text
    saved = json.loads(dest.read_text(encoding="utf-8"))
    step_identifiers = {step["step_identifier"] for step in saved["steps"]}
    assert "geometry" not in step_identifiers
    assert "framing" not in step_identifiers


def test_save_recipe_without_image_loaded_returns_400(client, tmp_path):
    session_id = client.post("/sessions").json()["id"]
    response = client.post(
        f"/sessions/{session_id}/recipe/save", json={"dest_path": str(tmp_path / "recipe.json")}
    )
    assert response.status_code == 400


def test_save_recipe_onto_existing_file_requires_force(client, tmp_path):
    session_id = _open_and_select(client)
    dest = tmp_path / "recipe.json"
    dest.write_text("not a real recipe", encoding="utf-8")

    response = client.post(f"/sessions/{session_id}/recipe/save", json={"dest_path": str(dest)})
    assert response.status_code == 409

    response = client.post(
        f"/sessions/{session_id}/recipe/save", json={"dest_path": str(dest), "force": True}
    )
    assert response.status_code == 200


def test_load_recipe_applies_saved_selections_onto_a_fresh_session(client, tmp_path):
    # Film (index 2), not Geometry/Framing (indices 0/1) -- those two are excluded from presets
    # entirely (2026-08-24), so a selection made there would never round-trip through save/load.
    session_a = _open(client)
    select_response = client.post(f"/sessions/{session_a}/steps/2/select", json={"identifier": "Velvia"})
    assert select_response.status_code == 200, select_response.text
    dest = tmp_path / "recipe.json"
    save_response = client.post(f"/sessions/{session_a}/recipe/save", json={"dest_path": str(dest)})
    assert save_response.status_code == 200

    session_b = _open(client)
    load_response = client.post(f"/sessions/{session_b}/recipe/load", json={"path": str(dest)})
    assert load_response.status_code == 200, load_response.text
    rows = load_response.json()["rows"]
    assert rows[2]["selected_vignette_identifier"] == "Velvia"


def test_load_recipe_missing_file_returns_400_not_500(client, tmp_path):
    session_id = _open(client)
    response = client.post(
        f"/sessions/{session_id}/recipe/load", json={"path": str(tmp_path / "does-not-exist.json")}
    )
    assert response.status_code == 400


def test_load_recipe_invalid_json_returns_400_not_500(client, tmp_path):
    session_id = _open(client)
    bad_file = tmp_path / "bad_recipe.json"
    bad_file.write_text("not json at all", encoding="utf-8")
    response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(bad_file)})
    assert response.status_code == 400


# --- Feature 048: structured recipe-load diagnostics ---


def _full_recipe_payload(
    client: TestClient,
    session_id: str,
    step_overrides: dict[str, dict] | None = None,
    schema_version: str | None = None,
) -> dict:
    """One StepEntry per real WORKFLOW_CONFIG row (neutral/no parameters by default), the same
    full-length shape build_recipe (the only real save path) always produces -- required to avoid
    the pre-existing, unrelated IndexError apply_recipe/refresh_workflow raises on a partial
    recipe. `step_overrides` maps a specific step_identifier to a {"thumbnail_identifier":
    ..., "parameters": ...} override."""
    source = client.get(f"/sessions/{session_id}").json()["source"]
    row_identifiers = [row.identifier for row in WORKFLOW_CONFIG.rows]
    step_overrides = step_overrides or {}
    return {
        "schema_version": schema_version or SCHEMA_VERSION,
        "source": {"filename": source["filename"], "width": source["width"], "height": source["height"]},
        "steps": [
            {
                "step_identifier": identifier,
                "thumbnail_identifier": step_overrides.get(identifier, {}).get("thumbnail_identifier", "neutral"),
                "parameters": step_overrides.get(identifier, {}).get("parameters", {}),
            }
            for identifier in row_identifiers
        ],
    }


def test_load_recipe_missing_addon_names_the_missing_step_identifier(client, tmp_path):
    # FR-001/AC-048-01: a recipe referencing a row identifier absent from the current
    # WORKFLOW_CONFIG is refused, naming the missing identifier -- not a real addon's own
    # identifier, a *row* identifier (recipe.steps[].step_identifier), per apply_recipe's own
    # rows_by_identifier lookup.
    session_id = _open(client)
    payload = _full_recipe_payload(client, session_id)
    payload["steps"].append(
        {"step_identifier": "_no_such_row", "thumbnail_identifier": "neutral", "parameters": {}}
    )
    recipe_path = tmp_path / "missing_addon.json"
    recipe_path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(recipe_path)})

    assert response.status_code == 400
    body = response.json()["detail"]
    assert body["category"] == "missing_addon"
    assert "_no_such_row" in body["details"]["missing_addon_ids"]


def test_load_recipe_unsupported_schema_version_returns_distinct_category(client, tmp_path):
    # FR-002/AC-048-02: distinct category+message from unreadable_file, names the received version.
    session_id = _open(client)
    payload = _full_recipe_payload(client, session_id, schema_version="999")
    recipe_path = tmp_path / "future_version.json"
    recipe_path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(recipe_path)})

    assert response.status_code == 400
    body = response.json()["detail"]
    assert body["category"] == "unsupported_schema_version"
    assert body["details"]["schema_version"] == "999"


def test_load_recipe_invalid_json_returns_unreadable_file_category_without_raw_parser_text(client, tmp_path):
    # FR-003/AC-048-03: distinct category+message from unsupported_schema_version, and the raw
    # json.JSONDecodeError text is never the user-facing message.
    session_id = _open(client)
    bad_file = tmp_path / "bad_recipe.json"
    bad_file.write_text("not json at all", encoding="utf-8")

    response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(bad_file)})

    assert response.status_code == 400
    body = response.json()["detail"]
    assert body["category"] == "unreadable_file"
    assert "Expecting value" not in body["message"]


def test_load_recipe_missing_file_returns_unreadable_file_category(client, tmp_path):
    session_id = _open(client)
    response = client.post(
        f"/sessions/{session_id}/recipe/load", json={"path": str(tmp_path / "does-not-exist.json")}
    )
    assert response.status_code == 400
    body = response.json()["detail"]
    assert body["category"] == "unreadable_file"


def test_blocking_recipe_load_categories_all_have_distinct_messages(client, tmp_path):
    # SC-001: "no two categories ever share the same message" -- verified across all three
    # blocking categories reachable through the real endpoint (a fourth, application_error, only
    # fires when a step's processor raises during execution; not independently reproducible here
    # without reaching into engine internals, so it's covered structurally instead in
    # test_load_recipe_out_of_bounds_parameter_is_corrected_and_signaled_without_blocking below).
    session_id = _open(client)

    missing_addon_payload = _full_recipe_payload(client, session_id)
    missing_addon_payload["steps"].append(
        {"step_identifier": "_no_such_row", "thumbnail_identifier": "neutral", "parameters": {}}
    )
    missing_addon_path = tmp_path / "missing_addon.json"
    missing_addon_path.write_text(json.dumps(missing_addon_payload), encoding="utf-8")

    version_path = tmp_path / "future_version.json"
    version_path.write_text(
        json.dumps(_full_recipe_payload(client, session_id, schema_version="999")), encoding="utf-8"
    )

    unreadable_path = tmp_path / "unreadable.json"
    unreadable_path.write_text("not json at all", encoding="utf-8")

    messages = set()
    for path in (missing_addon_path, version_path, unreadable_path):
        response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(path)})
        assert response.status_code == 400
        messages.add(response.json()["detail"]["message"])
    assert len(messages) == 3


def test_blocking_recipe_load_failure_leaves_active_session_strictly_unchanged(client, tmp_path):
    # FR-006/FR-008: after each of the three blocking failure categories, the active session
    # (image + selections) is strictly unchanged -- guaranteed structurally by apply_recipe/
    # load_recipe's ordering; this is the missing explicit test at the API
    # boundary.
    session_id = _open_and_select(client)
    baseline = client.get(f"/sessions/{session_id}").json()
    baseline_workflow = client.get(f"/sessions/{session_id}/workflow").json()

    missing_addon_payload = _full_recipe_payload(client, session_id)
    missing_addon_payload["steps"].append(
        {"step_identifier": "_no_such_row", "thumbnail_identifier": "neutral", "parameters": {}}
    )
    missing_addon_path = tmp_path / "missing_addon.json"
    missing_addon_path.write_text(json.dumps(missing_addon_payload), encoding="utf-8")

    version_path = tmp_path / "future_version.json"
    version_path.write_text(
        json.dumps(_full_recipe_payload(client, session_id, schema_version="999")), encoding="utf-8"
    )

    unreadable_path = tmp_path / "unreadable.json"
    unreadable_path.write_text("not json at all", encoding="utf-8")

    for path in (missing_addon_path, version_path, unreadable_path):
        response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(path)})
        assert response.status_code == 400
        assert client.get(f"/sessions/{session_id}").json() == baseline
        assert client.get(f"/sessions/{session_id}/workflow").json() == baseline_workflow


def test_load_recipe_out_of_bounds_parameter_is_corrected_and_signaled_without_blocking(client, tmp_path):
    # US3/FR-004: an out-of-bounds parameter is corrected (not blocked), the correction is
    # signaled, and the recipe's other steps are unaffected (Acceptance Scenarios 1-2).
    # "light"/intensity is bounded [0, 1] (light.py::resolve_zoom_values) -- stands in for the old
    # "framing"/crop_width case, which no longer applies now that Geometry/Framing are excluded
    # from presets entirely (2026-08-24, CLAUDE.md).
    session_a = _open(client)
    payload = _full_recipe_payload(
        client,
        session_a,
        step_overrides={
            "light": {"parameters": {"intensity": 5.0}},
            "vignette": {"thumbnail_identifier": "Round Central"},
        },
    )
    recipe_path = tmp_path / "out_of_bounds.json"
    recipe_path.write_text(json.dumps(payload), encoding="utf-8")

    session_b = _open(client)
    response = client.post(f"/sessions/{session_b}/recipe/load", json={"path": str(recipe_path)})

    assert response.status_code == 200, response.text
    body = response.json()
    corrections = body["parameter_corrections"]
    assert len(corrections) == 1
    assert corrections[0] == {
        "step_identifier": "light",
        "parameter": "intensity",
        "requested": 5.0,
        "applied": 1.0,
    }
    # The unrelated correction ("vignette") and every other step remain exactly as the recipe
    # specified -- no side effect from the light correction.
    row_identifiers = [row.identifier for row in WORKFLOW_CONFIG.rows]
    vignette_row = body["rows"][row_identifiers.index("vignette")]
    assert vignette_row["selected_vignette_identifier"] == "Round Central"


def test_load_recipe_v1_file_with_source_and_geometry_framing_is_ignored_without_error(client, tmp_path):
    # Requirement (2026-08-24): a v1 preset file -- the shape written before `source` and
    # Geometry/Framing step entries were dropped from the schema -- must keep loading with no
    # error and no warning; the now-obsolete elements are simply disregarded.
    session_a = _open(client)
    row_identifiers = [row.identifier for row in WORKFLOW_CONFIG.rows]
    payload = {
        "schema_version": "1",
        "source": {"filename": "old-photo.jpg", "width": 4032, "height": 3024, "checksum": None},
        "steps": [
            {
                "step_identifier": identifier,
                "thumbnail_identifier": "neutral",
                "parameters": {"angle": 12.0} if identifier == "geometry" else {},
            }
            for identifier in row_identifiers
        ],
    }
    recipe_path = tmp_path / "legacy_v1.json"
    recipe_path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/sessions/{session_a}/recipe/load", json={"path": str(recipe_path)})

    assert response.status_code == 200, response.text
    assert response.json()["parameter_corrections"] == []


# --- Correctif de performance (2026-07-21): working_image vs full resolution ---


def test_open_image_populates_a_downscaled_working_image(large_fixture_image):
    session = create_session()
    open_image(session, large_fixture_image)
    assert session.working_image is not None
    assert max(session.working_image.shape[0], session.working_image.shape[1]) <= 480
    # And it really is a reduction, not an accidental copy of the original.
    assert session.working_image.shape != session.image_session.original.shape


def test_open_image_working_image_equals_original_for_an_already_small_image(client):
    session_id = _open(client)  # deterministic_8x8.png -- already <=480px
    session = api_app._sessions[session_id]
    assert session.working_image.shape == session.image_session.original.shape


def test_preview_endpoint_returns_the_downscaled_working_resolution(client, large_fixture_image):
    session_id = client.post("/sessions").json()["id"]
    response = client.post(f"/sessions/{session_id}/open", json={"path": str(large_fixture_image)})
    assert response.status_code == 200, response.text
    preview = client.get(f"/sessions/{session_id}/preview")
    assert preview.status_code == 200
    preview_image = Image.open(io.BytesIO(preview.content))
    assert max(preview_image.size) <= 480
    assert preview_image.size != (800, 600)


def test_export_still_produces_a_full_resolution_file(client, large_fixture_image, tmp_path):
    session_id = client.post("/sessions").json()["id"]
    response = client.post(f"/sessions/{session_id}/open", json={"path": str(large_fixture_image)})
    assert response.status_code == 200, response.text
    dest = tmp_path / "export.png"
    export_response = client.post(
        f"/sessions/{session_id}/export", json={"dest_path": str(dest), "image_format": "PNG"},
    )
    assert export_response.status_code == 200, export_response.text
    with Image.open(dest) as exported:
        assert exported.size == (800, 600), "export must stay full resolution regardless of the interactive preview"


def test_render_full_resolution_matches_original_dimensions(large_fixture_image):
    session = create_session()
    open_image(session, large_fixture_image)
    result = render_full_resolution(session)
    assert result.shape == session.image_session.original.shape


def test_render_full_resolution_upto_exclusive_stops_before_the_last_step(large_fixture_image):
    session = create_session()
    open_image(session, large_fixture_image)
    total_steps = len(session.pipeline._steps)
    assert total_steps > 1, "fixture workflow must have more than one step for this test to mean anything"

    partial = render_full_resolution(session, upto_exclusive=1)
    full = render_full_resolution(session)
    # Both are full-resolution outputs of the SAME source, but at different
    # pipeline depths -- proving upto_exclusive genuinely limits how many
    # steps ran (this is what the future Zoom mode's before/after view will
    # rely on).
    assert partial.shape[:2] == full.shape[:2]


def test_render_full_resolution_without_image_raises():
    session = create_session()
    with pytest.raises(ValueError):
        render_full_resolution(session)


# --- Zoom overlay (2026-07-22): before/after split-compare + "Réglages
# manuels" sliders. Film is the only row with any real zoom_parameters today
# (intensity + 20 grade-override sliders, see lumaflow/addons/builtin/film.py;
# 3 more -- Color Chrome Effect/Blue, Dynamic Range -- added 2026-07-25; 2 more
# -- Mono Colour WC/MG -- added 2026-07-26; 2 more -- filter_color/
# filter_intensity, the "B&W" row's colored-filter selector, backend-shared
# by the whole film_look addon regardless of row -- added 2026-08-04). ---


def _film_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "film")


def _color_splash_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "color_splash")


def _light_step_index() -> int:
    return next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "light")


_FILM_SLIDER_IDENTIFIERS = {
    "intensity",
    "contrast",
    "highlights",
    "shadows",
    "black_clip",
    "global_saturation",
    "hsl_saturation_scale",
    "hsl_luminance_scale",
    "temperature",
    "tint",
    "split_tone_scale",
    "clarity",
    "sharpness",
    "grain_std",
    "color_chrome_effect",
    "color_chrome_blue",
    "dynamic_range",
    "mono_color_wc",
    "mono_color_mg",
    "filter_color",
    "filter_intensity",
}


def test_open_zoom_endpoint_returns_declared_sliders(client):
    session_id = _open(client)
    step_index = _film_step_index()
    response = client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["step_index"] == step_index
    assert body["identifier"] == "Velvia"
    identifiers = {slider["identifier"] for slider in body["sliders"]}
    assert identifiers == _FILM_SLIDER_IDENTIFIERS
    intensity = next(s for s in body["sliders"] if s["identifier"] == "intensity")
    assert intensity["value"] == 1.0


def test_open_zoom_seeds_sliders_with_the_selected_looks_real_calibrated_values(client):
    """Regression test for the exact bug reported 2026-07-22: opening Zoom on
    a freshly-selected (never manually adjusted) look must show each slider's
    REAL value for that look (e.g. Velvia's own calibrated contrast), not a
    generic neutral/default value."""
    session_id = _open(client)
    step_index = _film_step_index()
    body = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"}
    ).json()
    by_identifier = {s["identifier"]: s for s in body["sliders"]}
    assert by_identifier["contrast"]["value"] == _VELVIA_PRO_GRADE.contrast
    assert by_identifier["highlights"]["value"] == _VELVIA_PRO_GRADE.highlights
    assert by_identifier["shadows"]["value"] == _VELVIA_PRO_GRADE.shadows
    assert by_identifier["global_saturation"]["value"] == _VELVIA_PRO_GRADE.global_saturation
    assert by_identifier["temperature"]["value"] == _VELVIA_PRO_GRADE.temperature
    # "default" (the Reset target) must match too, since no override exists yet.
    assert by_identifier["contrast"]["default"] == _VELVIA_PRO_GRADE.contrast


def test_open_zoom_selects_the_candidate_row(client):
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Astia"})
    rows = client.get(f"/sessions/{session_id}/workflow").json()
    assert rows[step_index]["selected_vignette_identifier"] == "Astia"


def test_open_zoom_unknown_step_returns_400(client):
    session_id = _open(client)
    response = client.post(f"/sessions/{session_id}/zoom/999/open", json={"identifier": "Velvia"})
    assert response.status_code == 400


def test_open_zoom_without_image_returns_400(client):
    session_id = client.post("/sessions").json()["id"]
    response = client.post(f"/sessions/{session_id}/zoom/0/open", json={"identifier": "neutral"})
    assert response.status_code == 400


def test_zoom_before_and_after_differ_for_a_non_neutral_look(client):
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"})
    before = client.get(f"/sessions/{session_id}/zoom/before").content
    after = client.get(f"/sessions/{session_id}/zoom/after").content
    assert before != after


def test_zoom_before_and_after_are_identical_for_neutral(client):
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "neutral"})
    before = client.get(f"/sessions/{session_id}/zoom/before").content
    after = client.get(f"/sessions/{session_id}/zoom/after").content
    assert before == after


def test_zoom_before_without_open_zoom_returns_400(client):
    session_id = _open(client)
    response = client.get(f"/sessions/{session_id}/zoom/before")
    assert response.status_code == 400


def test_set_zoom_parameter_changes_the_after_render(client):
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"})
    baseline_after = client.get(f"/sessions/{session_id}/zoom/after").content
    response = client.post(
        f"/sessions/{session_id}/zoom/parameter", json={"identifier": "contrast", "value": 90.0}
    )
    assert response.status_code == 200
    assert response.content != baseline_after


def test_set_zoom_parameter_changes_the_after_render_for_neutral(client):
    # Bug fix 2026-07-23: editing a manual slider on the Film row's "Neutral"
    # vignette had no visible effect at all -- reproduces the reported bug at
    # the API level, not just film_look() in isolation.
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "neutral"})
    baseline_after = client.get(f"/sessions/{session_id}/zoom/after").content
    response = client.post(
        f"/sessions/{session_id}/zoom/parameter", json={"identifier": "contrast", "value": 90.0}
    )
    assert response.status_code == 200
    assert response.content != baseline_after


def test_set_zoom_parameters_batched_writes_all_values_and_renders_once(client, monkeypatch):
    # Foundational (T003): the batched endpoint must write every update and trigger exactly one
    # render_zoom_after call, regardless of how many updates are batched together.
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"})

    render_calls = []
    original_render_zoom_after = api_app.render_zoom_after

    def _counting_render_zoom_after(session, **kwargs):
        render_calls.append(1)
        return original_render_zoom_after(session, **kwargs)

    monkeypatch.setattr(api_app, "render_zoom_after", _counting_render_zoom_after)

    response = client.post(
        f"/sessions/{session_id}/zoom/parameters",
        json={"updates": [
            {"identifier": "contrast", "value": 90.0},
            {"identifier": "highlights", "value": -50.0},
            {"identifier": "shadows", "value": 40.0},
        ]},
    )
    assert response.status_code == 200
    assert len(render_calls) == 1

    session = api_app._get_session(session_id)
    step = session.pipeline._steps[step_index]
    assert step.parameters.values["contrast"] == 90.0
    assert step.parameters.values["highlights"] == -50.0
    assert step.parameters.values["shadows"] == 40.0


def test_set_zoom_parameters_empty_updates_is_a_valid_noop(client):
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"})
    baseline_after = client.get(f"/sessions/{session_id}/zoom/after").content

    response = client.post(f"/sessions/{session_id}/zoom/parameters", json={"updates": []})
    assert response.status_code == 200
    assert response.content == baseline_after


def test_set_zoom_parameters_without_open_zoom_returns_400(client):
    session_id = _open(client)
    response = client.post(
        f"/sessions/{session_id}/zoom/parameters",
        json={"updates": [{"identifier": "contrast", "value": 90.0}]},
    )
    assert response.status_code == 400


def test_set_zoom_parameters_last_write_wins_for_duplicate_identifier(client):
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"})
    client.post(
        f"/sessions/{session_id}/zoom/parameters",
        json={"updates": [
            {"identifier": "contrast", "value": 10.0},
            {"identifier": "contrast", "value": 90.0},
        ]},
    )
    session = api_app._get_session(session_id)
    step = session.pipeline._steps[step_index]
    assert step.parameters.values["contrast"] == 90.0


def test_confirm_zoom_persists_parameter_edits(client):
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "contrast", "value": 90.0})
    response = client.post(f"/sessions/{session_id}/zoom/confirm")
    assert response.status_code == 200

    # session.zoom is now closed -- a further parameter edit must 400.
    response = client.post(
        f"/sessions/{session_id}/zoom/parameter", json={"identifier": "contrast", "value": 0.0}
    )
    assert response.status_code == 400

    # Reopening the SAME already-selected candidate must reflect the
    # confirmed edit as `value`, not silently reset it back to the look's
    # bare calibration -- but `default` (the Reset target) must still be the
    # look's TRUE calibrated value, distinct from the confirmed override.
    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"}
    ).json()
    contrast_slider = next(s for s in reopened["sliders"] if s["identifier"] == "contrast")
    assert contrast_slider["value"] == 90.0
    assert contrast_slider["default"] == _VELVIA_PRO_GRADE.contrast


def test_cancel_zoom_discards_parameter_edits(client):
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "contrast", "value": 90.0})
    response = client.post(f"/sessions/{session_id}/zoom/cancel")
    assert response.status_code == 200

    # After a cancel, reopening must show the look's own real calibrated
    # value again -- not 0.0 (the old, now-removed generic delta default).
    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"}
    ).json()
    contrast_slider = next(s for s in reopened["sliders"] if s["identifier"] == "contrast")
    assert contrast_slider["value"] == _VELVIA_PRO_GRADE.contrast


def test_cancel_zoom_discards_light_parameter_edits(client):
    # US3: with confirmed Exposure/Shadows/Highlights values already set, opening Zoom, changing
    # them, and canceling restores the previously confirmed values.
    session_id = _open(client)
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Balance"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Balance"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "exposure", "value": -1.8})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "shadows", "value": -0.9})
    response = client.post(f"/sessions/{session_id}/zoom/cancel")
    assert response.status_code == 200

    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Balance"}
    ).json()
    values = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    assert values["exposure"] == _BALANCE_GRADE.exposure
    assert values["shadows"] == _BALANCE_GRADE.shadows
    assert values["highlights"] == _BALANCE_GRADE.highlights


@pytest.mark.parametrize("preset_identifier,look", [
    ("Low Key", "low_key"), ("High Key", "high_key"), ("Dramatique", "dramatique"), ("Soft", "soft"),
])
def test_opening_zoom_on_an_elaborate_preset_seeds_every_slider_at_its_real_calibrated_value(client, preset_identifier, look):
    # US2 (T021): every base-grade slider must seed from the preset's REAL calibration, never a
    # generic declared default -- the direct API-level guard for the exact bug already fixed once
    # on this same addon in F-043.
    session_id = _open(client)
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": preset_identifier})
    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": preset_identifier}
    ).json()
    values = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    grade = _GRADES[look]
    for field_name in _LIGHT_FIELD_BOUNDS:
        assert values[field_name] == getattr(grade, field_name), field_name


def test_changing_one_slider_on_an_elaborate_preset_updates_only_that_value(client):
    session_id = _open(client)
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Dramatique"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Dramatique"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "contrast", "value": 77.0})

    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Dramatique"}
    ).json()
    values = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    grade = _GRADES["dramatique"]
    assert values["contrast"] == 77.0
    for field_name in _LIGHT_FIELD_BOUNDS:
        if field_name == "contrast":
            continue
        assert values[field_name] == getattr(grade, field_name), field_name


_RECTANGLE_MASK_UPDATES = [
    {"identifier": "mask_point_count", "value": 4.0},
    {"identifier": "mask_point_00_x", "value": 0.25}, {"identifier": "mask_point_00_y", "value": 0.25},
    {"identifier": "mask_point_01_x", "value": 0.75}, {"identifier": "mask_point_01_y", "value": 0.25},
    {"identifier": "mask_point_02_x", "value": 0.75}, {"identifier": "mask_point_02_y", "value": 0.75},
    {"identifier": "mask_point_03_x", "value": 0.25}, {"identifier": "mask_point_03_y", "value": 0.75},
    {"identifier": "mask_feather", "value": 0.5},
]


def test_drawing_the_default_rectangle_and_setting_differing_region_exposure_produces_a_measurably_different_result(client, large_fixture_image):
    # US3 Independent Test: apply a preset, draw the default rectangle, raise subject exposure and
    # lower background exposure, then verify the result differs from the plain (no-region) render.
    session_id = client.post("/sessions").json()["id"]
    open_response = client.post(f"/sessions/{session_id}/open", json={"path": str(large_fixture_image)})
    assert open_response.status_code == 200, open_response.text
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Low Key"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Low Key"})

    plain_after = client.get(f"/sessions/{session_id}/zoom/after").content

    batched_response = client.post(
        f"/sessions/{session_id}/zoom/parameters",
        json={"updates": _RECTANGLE_MASK_UPDATES + [
            {"identifier": "subject_exposure", "value": 60.0},
            {"identifier": "background_exposure", "value": -60.0},
        ]},
    )
    assert batched_response.status_code == 200
    assert batched_response.content != plain_after


def test_batched_mask_vertex_commit_writes_all_keys_and_renders_once(client, monkeypatch):
    session_id = _open(client)
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Low Key"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Low Key"})

    render_calls = []
    original_render_zoom_after = api_app.render_zoom_after

    def _counting_render_zoom_after(session, **kwargs):
        render_calls.append(1)
        return original_render_zoom_after(session, **kwargs)

    monkeypatch.setattr(api_app, "render_zoom_after", _counting_render_zoom_after)

    response = client.post(f"/sessions/{session_id}/zoom/parameters", json={"updates": _RECTANGLE_MASK_UPDATES})
    assert response.status_code == 200
    assert len(render_calls) == 1

    session = api_app._get_session(session_id)
    step = session.pipeline._steps[step_index]
    assert step.parameters.values["mask_point_count"] == 4.0
    assert step.parameters.values["mask_point_02_x"] == 0.75
    assert step.parameters.values["mask_feather"] == 0.5


def test_reselecting_an_already_selected_vignette_preserves_confirmed_mask_and_region_deltas(client):
    # Regression test for the bug reported 2026-07-28: a plain click on an already-selected
    # vignette (which ALWAYS fires before a dblclick, per browser event order -- VignetteCard.tsx
    # wires both to the same button) used to silently wipe every confirmed Zoom-only override for
    # that vignette via select_vignette's unconditional parameter rewrite, including Light's
    # subject-mask contour -- open_zoom's own same-identifier guard couldn't prevent this by
    # itself, since it runs AFTER the preceding click had already done the damage.
    session_id = _open(client)
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Balance"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Balance"})
    client.post(
        f"/sessions/{session_id}/zoom/parameters",
        json={"updates": _RECTANGLE_MASK_UPDATES + [{"identifier": "subject_exposure", "value": 40.0}]},
    )
    confirm_response = client.post(f"/sessions/{session_id}/zoom/confirm")
    assert confirm_response.status_code == 200

    # Mirrors the plain click that always precedes a dblclick reopening an already-selected card.
    reselect_response = client.post(
        f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Balance"}
    )
    assert reselect_response.status_code == 200

    reopened = client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Balance"}).json()
    by_identifier = {s["identifier"]: s for s in reopened["sliders"]}
    assert by_identifier["mask_point_count"]["value"] == 4.0
    assert by_identifier["mask_point_02_x"]["value"] == 0.75
    assert by_identifier["subject_exposure"]["value"] == 40.0


def test_reselecting_an_already_selected_vignette_preserves_confirmed_slider_on_any_row(client):
    # Same fix, a non-Light row -- confirms this isn't specific to Light/masks: select_vignette's
    # idempotence guard applies generically to every row with a vignette card.
    session_id = _open(client)
    step_index = _film_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Velvia"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "contrast", "value": 77.0})
    confirm_response = client.post(f"/sessions/{session_id}/zoom/confirm")
    assert confirm_response.status_code == 200

    reselect_response = client.post(
        f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Velvia"}
    )
    assert reselect_response.status_code == 200

    reopened = client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Velvia"}).json()
    contrast = next(s for s in reopened["sliders"] if s["identifier"] == "contrast")
    assert contrast["value"] == 77.0


def test_cancel_zoom_discards_color_splash_multi_range_edits(client):
    session_id = _open(client)
    step_index = _color_splash_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Rouge"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Rouge"})
    # Move range_1's hue away from its preset value AND enable a 2nd range -- an in-progress
    # multi-range adjustment (US3), not just a single scalar edit.
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "range_1_hue_center", "value": 99.0})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "range_2_enabled", "value": 1.0})

    response = client.post(f"/sessions/{session_id}/zoom/cancel")
    assert response.status_code == 200

    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Rouge"}
    ).json()
    range_1 = next(r for r in reopened["hue_ranges"] if r["identifier"] == "range_1")
    assert range_1["hue_value"] == 0.0  # back to the "Rouge" preset's own value, not 99.0
    range_2_enabled = next(s for s in reopened["sliders"] if s["identifier"] == "range_2_enabled")
    assert range_2_enabled["value"] == 0.0  # back to disabled


def test_confirm_color_splash_multi_range_then_reload_recipe_reproduces_exact_configuration(client, tmp_path):
    session_id = _open(client)
    step_index = _color_splash_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Rouge"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Rouge"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "range_1_feather", "value": 55.0})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "range_2_enabled", "value": 1.0})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "range_2_hue_center", "value": 60.0})
    confirm_response = client.post(f"/sessions/{session_id}/zoom/confirm")
    assert confirm_response.status_code == 200

    dest = tmp_path / "color_splash_recipe.json"
    save_response = client.post(f"/sessions/{session_id}/recipe/save", json={"dest_path": str(dest)})
    assert save_response.status_code == 200

    # Reload into a FRESH session -- proves persistence round-trips through disk, not just
    # in-memory session state.
    session_id_2 = _open(client)
    load_response = client.post(f"/sessions/{session_id_2}/recipe/load", json={"path": str(dest)})
    assert load_response.status_code == 200

    reopened = client.post(
        f"/sessions/{session_id_2}/zoom/{step_index}/open", json={"identifier": "Rouge"}
    ).json()
    range_1 = next(r for r in reopened["hue_ranges"] if r["identifier"] == "range_1")
    range_2 = next(r for r in reopened["hue_ranges"] if r["identifier"] == "range_2")
    assert range_1["feather_value"] == 55.0
    assert range_2["hue_value"] == 60.0
    range_2_enabled = next(s for s in reopened["sliders"] if s["identifier"] == "range_2_enabled")
    assert range_2_enabled["value"] == 1.0


def test_reopening_zoom_on_the_same_selection_preserves_prior_confirmed_edits(large_fixture_image):
    """Direct session.py-level test of the exact regression open_zoom's own
    docstring calls out: re-selecting an ALREADY-selected candidate must not
    silently wipe a previously confirmed manual adjustment (select_vignette
    always re-resolves parameter values from the preset's bare defaults)."""
    session = create_session()
    open_image(session, large_fixture_image)
    step_index = _film_step_index()
    open_zoom(session, step_index, "Velvia")
    set_zoom_parameter(session, "contrast", 90.0)
    confirm_zoom(session)

    open_zoom(session, step_index, "Velvia")
    step = session.pipeline._steps[step_index]
    assert step.parameters.values.get("contrast") == 90.0


def test_session_module_zoom_lifecycle(large_fixture_image):
    session = create_session()
    open_image(session, large_fixture_image)
    step_index = _film_step_index()

    open_zoom(session, step_index, "Velvia")
    declarations = zoom_parameter_declarations(session)
    assert {d.identifier for d in declarations} == _FILM_SLIDER_IDENTIFIERS

    before = render_zoom_before(session)
    after = render_zoom_after(session)
    assert before.shape == after.shape == session.image_session.original.shape
    assert not numpy.array_equal(before, after)

    set_zoom_parameter(session, "contrast", 90.0)
    tweaked_after = render_zoom_after(session)
    assert not numpy.array_equal(after, tweaked_after)

    cancel_zoom(session)
    assert session.zoom is None
    step = session.pipeline._steps[step_index]
    # No override survives a cancel -- the key is simply absent (not a
    # generic 0.0 default), so resolve_zoom_values falls back to the look's
    # own real calibration again.
    assert step.parameters.values.get("contrast") is None
    assert resolve_zoom_values(step.parameters.values)["contrast"] == _VELVIA_PRO_GRADE.contrast


def test_zoom_parameter_declarations_empty_for_a_row_without_any(large_fixture_image, monkeypatch):
    # No row in the real shipped config is addon-less anymore since "finishing" (spec 045,
    # never implemented) was removed 2026-07-31 -- synthesize one instead of relying on that
    # coincidence, so this regression stays covered independently of the real config's
    # contents. Unlike geometry (rotation_angle) and framing (crop_x/y/width/height), which
    # already have real zoom parameters from earlier features. "light" moved out of this group
    # in feature 043 (light_adjustments addon, three real zoom parameters) -- see
    # test_zoom_parameter_declarations_light_addon below. "vignette" moved out of this group in
    # feature 044 (vignetting addon) -- see test_zoom_parameter_declarations_vignetting_addon.
    addonless_index = _patch_workflow_config_with_addonless_row(monkeypatch)
    session = create_session()
    open_image(session, large_fixture_image)
    open_zoom(session, addonless_index, "neutral")
    assert zoom_parameter_declarations(session) == ()


def test_zoom_parameter_declarations_vignetting_addon(large_fixture_image):
    # Feature 044 (extended by the dynamic-aids pass): vignetting declares `intensity` +
    # `progressivity` + 8 geometry/feather fields (10 total zoom_parameters, no overlay anymore),
    # shown regardless of which candidate (neutral or either preset) is open.
    session = create_session()
    open_image(session, large_fixture_image)
    vignette_index = next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "vignette")
    open_zoom(session, vignette_index, "neutral")
    identifiers = {decl.identifier for decl in zoom_parameter_declarations(session)}
    assert identifiers == {
        "intensity", "progressivity", "center_x", "center_y", "radius_x", "radius_y",
        "top_offset", "bottom_offset", "rotation_angle", "feather_width",
    }


def test_zoom_parameter_declarations_light_addon(large_fixture_image):
    # Feature 047: light_adjustments declares `intensity` + 31 base-grade + 38 region-delta + 67
    # mask zoom parameters (137 total), all shown regardless of which candidate (neutral or any
    # preset) is open -- unlike Film's intensity, no neutral gating.
    session = create_session()
    open_image(session, large_fixture_image)
    light_index = next(i for i, row in enumerate(WORKFLOW_CONFIG.rows) if row.identifier == "light")
    open_zoom(session, light_index, "neutral")
    identifiers = {decl.identifier for decl in zoom_parameter_declarations(session)}
    assert len(identifiers) == 137
    assert {"intensity"} | set(_LIGHT_FIELD_BOUNDS) <= identifiers
    assert "subject_exposure" in identifiers
    assert "background_saturation" in identifiers
    assert "mask_point_count" in identifiers
    assert "mask_point_31_y" in identifiers


# --- User Story 6: cancel/save/reload confidence, including the mask contour ---

_SUBDIVIDED_MASK_UPDATES = [
    {"identifier": "mask_point_count", "value": 5.0},
    {"identifier": "mask_point_00_x", "value": 0.20}, {"identifier": "mask_point_00_y", "value": 0.20},
    {"identifier": "mask_point_01_x", "value": 0.50}, {"identifier": "mask_point_01_y", "value": 0.10},
    {"identifier": "mask_point_02_x", "value": 0.80}, {"identifier": "mask_point_02_y", "value": 0.20},
    {"identifier": "mask_point_03_x", "value": 0.80}, {"identifier": "mask_point_03_y", "value": 0.80},
    {"identifier": "mask_point_04_x", "value": 0.20}, {"identifier": "mask_point_04_y", "value": 0.80},
    {"identifier": "mask_feather", "value": 1.0},
]


def test_cancel_after_reopening_a_confirmed_mask_restores_settings_and_contour_exactly(client):
    session_id = _open(client)
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Low Key"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Low Key"})
    client.post(
        f"/sessions/{session_id}/zoom/parameters",
        json={"updates": _SUBDIVIDED_MASK_UPDATES + [
            {"identifier": "subject_exposure", "value": 35.0},
            {"identifier": "background_exposure", "value": -35.0},
        ]},
    )
    confirm_response = client.post(f"/sessions/{session_id}/zoom/confirm")
    assert confirm_response.status_code == 200

    # Reopen, change everything (settings AND contour), then cancel.
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Low Key"})
    client.post(
        f"/sessions/{session_id}/zoom/parameters",
        json={"updates": [
            {"identifier": "subject_exposure", "value": -80.0},
            {"identifier": "background_exposure", "value": 80.0},
            {"identifier": "mask_point_count", "value": 4.0},
            {"identifier": "mask_point_00_x", "value": 0.0}, {"identifier": "mask_point_00_y", "value": 0.0},
            {"identifier": "mask_point_01_x", "value": 1.0}, {"identifier": "mask_point_01_y", "value": 0.0},
            {"identifier": "mask_point_02_x", "value": 1.0}, {"identifier": "mask_point_02_y", "value": 1.0},
            {"identifier": "mask_point_03_x", "value": 0.0}, {"identifier": "mask_point_03_y", "value": 1.0},
        ]},
    )
    cancel_response = client.post(f"/sessions/{session_id}/zoom/cancel")
    assert cancel_response.status_code == 200

    reopened = client.post(
        f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Low Key"}
    ).json()
    values = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    assert values["subject_exposure"] == 35.0
    assert values["background_exposure"] == -35.0
    assert values["mask_point_count"] == 5.0
    assert values["mask_point_01_x"] == 0.50
    assert values["mask_point_01_y"] == 0.10
    assert values["mask_point_04_x"] == 0.20
    assert values["mask_feather"] == 1.0


def test_save_and_reload_a_preset_with_overrides_region_deltas_and_mask_reproduces_identical_pixels(client, tmp_path):
    session_id = _open(client)
    step_index = _light_step_index()
    client.post(f"/sessions/{session_id}/steps/{step_index}/select", json={"identifier": "Dramatique"})
    client.post(f"/sessions/{session_id}/zoom/{step_index}/open", json={"identifier": "Dramatique"})
    client.post(f"/sessions/{session_id}/zoom/parameter", json={"identifier": "contrast", "value": 55.0})
    client.post(
        f"/sessions/{session_id}/zoom/parameters",
        json={"updates": _SUBDIVIDED_MASK_UPDATES + [
            {"identifier": "subject_clarity", "value": 40.0},
            {"identifier": "background_clarity", "value": -20.0},
        ]},
    )
    confirm_response = client.post(f"/sessions/{session_id}/zoom/confirm")
    assert confirm_response.status_code == 200

    original_preview = client.get(f"/sessions/{session_id}/preview").content

    dest = tmp_path / "light_region_mask_recipe.json"
    save_response = client.post(f"/sessions/{session_id}/recipe/save", json={"dest_path": str(dest)})
    assert save_response.status_code == 200

    session_id_2 = _open(client)
    load_response = client.post(f"/sessions/{session_id_2}/recipe/load", json={"path": str(dest)})
    assert load_response.status_code == 200

    reloaded_preview = client.get(f"/sessions/{session_id_2}/preview").content
    assert reloaded_preview == original_preview

    reopened = client.post(
        f"/sessions/{session_id_2}/zoom/{step_index}/open", json={"identifier": "Dramatique"}
    ).json()
    values = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    assert values["contrast"] == 55.0
    assert values["subject_clarity"] == 40.0
    assert values["background_clarity"] == -20.0
    assert values["mask_point_count"] == 5.0
    assert values["mask_point_02_x"] == 0.80
    assert values["mask_point_02_y"] == 0.20


def test_reload_with_one_malformed_key_among_137_falls_back_alone_rest_of_project_still_loads(client, tmp_path):
    light_identifier = "light"
    session_id = _open(client)
    source = client.get(f"/sessions/{session_id}").json()["source"]
    row_identifiers = [row.identifier for row in WORKFLOW_CONFIG.rows]

    from lumaflow.persistence.recipe import SCHEMA_VERSION

    light_params = {
        "look": "high_key",
        "intensity": 1.0,
        "contrast": 33.0,
        "subject_exposure": 12.0,
        "mask_point_count": 4.0,
        "mask_point_00_x": 0.25, "mask_point_00_y": 0.25,
        "mask_point_01_x": 0.75, "mask_point_01_y": 0.25,
        "mask_point_02_x": "corrupted-not-a-number",  # the ONE malformed key among ~137
        "mask_point_02_y": 0.75,
        "mask_point_03_x": 0.25, "mask_point_03_y": 0.75,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": {"filename": source["filename"], "width": source["width"], "height": source["height"]},
        "steps": [
            {
                "step_identifier": row_identifier,
                "thumbnail_identifier": "High Key" if row_identifier == light_identifier else "neutral",
                "parameters": light_params if row_identifier == light_identifier else {},
            }
            for row_identifier in row_identifiers
        ],
    }
    recipe_path = tmp_path / "one_corrupted_mask_key.json"
    recipe_path.write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(recipe_path)})
    assert response.status_code == 200  # one corrupted key never fails the whole project load
    rows = response.json()["rows"]
    light_row = rows[row_identifiers.index(light_identifier)]
    assert light_row["selected_vignette_identifier"] == "High Key"

    light_index = row_identifiers.index(light_identifier)
    reopened = client.post(
        f"/sessions/{session_id}/zoom/{light_index}/open", json={"identifier": "High Key"}
    ).json()
    values = {s["identifier"]: s["value"] for s in reopened["sliders"]}
    # The corrupted key falls back to ITS OWN default alone -- every other key, including the
    # other 3 mask vertices, still applies exactly as saved.
    assert values["mask_point_02_x"] == 0.75  # light.py's _DEFAULT_MASK_POINTS[2] == (0.75, 0.75)
    assert values["contrast"] == 33.0
    assert values["subject_exposure"] == 12.0
    assert values["mask_point_count"] == 4.0
    assert values["mask_point_00_x"] == 0.25
    assert values["mask_point_02_y"] == 0.75
    assert values["mask_point_03_x"] == 0.25


# --- Préférences > Workflow (2026-08-06): GET/PUT /workflow-config, import/export, and the
# "a disabled vignette must never render" coherence guarantee (select_vignette + apply_recipe).
# 2026-08-07: PUT /workflow-config (Valider) never writes to disk -- only Ouvrir (import, a read)
# and Exporter (an explicit, user-chosen write) may ever touch a workflow config file. ---


# --- Startup loading (2026-08-06, second follow-up): WORKFLOW_CONFIG must load from whichever
# file preferences.json remembers as active, not unconditionally the canonical default -- since
# PUT /workflow-config now saves to that same active file (see put_workflow_config_endpoint's
# docstring for the bug this fixes). _resolve_initial_workflow_config is a pure function, tested
# directly rather than via a real process restart (this test process stays up the whole run). ---


def test_resolve_initial_workflow_config_uses_canonical_default_when_nothing_remembered(monkeypatch, tmp_path):
    empty_prefs_path = tmp_path / "preferences.json"  # doesn't exist -- load_preferences defaults
    monkeypatch.setattr(api_session, "default_preferences_path", lambda: empty_prefs_path)

    config, path = api_session._resolve_initial_workflow_config()

    assert path == api_session.DEFAULT_WORKFLOW_CONFIG_PATH
    assert len(config.rows) > 0


def test_resolve_initial_workflow_config_follows_remembered_path(monkeypatch, tmp_path):
    other_dict = json.loads(api_session.DEFAULT_WORKFLOW_CONFIG_PATH.read_text(encoding="utf-8"))
    for row in other_dict["rows"]:
        if row["identifier"] == "film":
            row["thumbnail_presets"] = [p for p in row["thumbnail_presets"] if p != "Velvia"]
    other_path = tmp_path / "config_workflow-new1.json"
    other_path.write_text(json.dumps(other_dict), encoding="utf-8")

    prefs_path = tmp_path / "preferences.json"
    prefs_path.write_text(
        json.dumps({"version": 1, "workflow_config_source_path": str(other_path)}), encoding="utf-8"
    )
    monkeypatch.setattr(api_session, "default_preferences_path", lambda: prefs_path)

    config, path = api_session._resolve_initial_workflow_config()

    assert path == other_path
    film_row = next(r for r in config.rows if r.identifier == "film")
    assert "Velvia" not in film_row.thumbnail_presets


def test_resolve_initial_workflow_config_falls_back_when_remembered_file_is_gone(monkeypatch, tmp_path):
    missing_path = tmp_path / "deleted_workflow.json"  # never written
    prefs_path = tmp_path / "preferences.json"
    prefs_path.write_text(
        json.dumps({"version": 1, "workflow_config_source_path": str(missing_path)}), encoding="utf-8"
    )
    monkeypatch.setattr(api_session, "default_preferences_path", lambda: prefs_path)

    config, path = api_session._resolve_initial_workflow_config()

    # Self-heals to the canonical default -- a stale/moved/deleted remembered file must never
    # degrade the whole app to zero workflow rows.
    assert path == api_session.DEFAULT_WORKFLOW_CONFIG_PATH
    assert len(config.rows) > 0


def test_get_workflow_config_returns_unified_vignette_list_with_enabled_flags(client):
    response = client.get("/workflow-config")
    assert response.status_code == 200
    body = response.json()

    film_config_row = next(row for row in WORKFLOW_CONFIG.rows if row.identifier == "film")
    film_row = next(row for row in body["rows"] if row["identifier"] == "film")

    enabled_identifiers = [v["identifier"] for v in film_row["vignettes"] if v["enabled"]]
    assert enabled_identifiers == list(film_config_row.thumbnail_presets)
    assert film_row["vignettes"][0]["identifier"] == "neutral"
    assert film_row["vignettes"][0]["enabled"] is True

    disabled_identifiers = {v["identifier"] for v in film_row["vignettes"] if not v["enabled"]}
    assert disabled_identifiers.isdisjoint(film_config_row.thumbnail_presets)


def test_put_workflow_config_disables_a_vignette_in_memory_without_any_disk_write(
    client, isolated_workflow_config_path
):
    """2026-08-07 (user's explicit, repeated instruction): Valider must NEVER write a workflow
    config file, under any circumstance -- only "Ouvrir" (read) and "Exporter" (an explicit,
    user-chosen write) may ever touch one. Valider is a pure in-memory apply: an already-open
    session's filmstrip reflects it immediately, but nothing lands on disk."""
    baseline = client.get("/workflow-config").json()
    edited = json.loads(json.dumps(baseline))
    film_row = next(r for r in edited["rows"] if r["identifier"] == "film")
    for vignette in film_row["vignettes"]:
        if vignette["identifier"] == "Velvia":
            vignette["enabled"] = False

    put_response = client.put("/workflow-config", json=edited)
    assert put_response.status_code == 200

    reloaded = client.get("/workflow-config").json()
    film_row_after = next(r for r in reloaded["rows"] if r["identifier"] == "film")
    enabled_after = {v["identifier"] for v in film_row_after["vignettes"] if v["enabled"]}
    assert "Velvia" not in enabled_after

    # THE bug: PUT must never create/write this (or any) file.
    assert not isolated_workflow_config_path.exists()

    # A brand-new session reflects the in-memory change immediately, no restart needed.
    session_id = _open(client)
    workflow = client.get(f"/sessions/{session_id}/workflow").json()
    film_row_session = next(r for r in workflow if r["label"] == "Film")
    assert "Velvia" not in film_row_session["vignette_labels"]


def test_put_workflow_config_row_set_mismatch_rejected(client, isolated_workflow_config_path):
    baseline = client.get("/workflow-config").json()
    mismatched = {"rows": list(reversed(baseline["rows"]))}

    response = client.put("/workflow-config", json=mismatched)
    assert response.status_code == 400
    assert response.json()["detail"]["category"] == "row_set_mismatch"

    unchanged = client.get("/workflow-config").json()
    assert unchanged == baseline


def test_put_workflow_config_tracks_source_path_in_memory_without_writing_the_imported_file(
    client, isolated_workflow_config_path, tmp_path
):
    """Ouvrir a file, Valider, then reopen Préférences -- source_path (a pure in-memory/GET
    concept, tracking what's currently active) must keep showing the opened file, WITHOUT that
    file (or the canonical default) ever being written to disk (2026-08-07)."""
    foreign_dict = json.loads(api_session.DEFAULT_WORKFLOW_CONFIG_PATH.read_text(encoding="utf-8"))
    for row in foreign_dict["rows"]:
        if row["identifier"] == "film":
            row["thumbnail_presets"] = [p for p in row["thumbnail_presets"] if p != "Velvia"]
    foreign_path = tmp_path / "foreign_workflow.json"
    foreign_bytes = json.dumps(foreign_dict).encode("utf-8")
    foreign_path.write_bytes(foreign_bytes)

    imported = client.post("/workflow-config/import", json={"path": str(foreign_path)}).json()
    assert imported["source_path"] == str(foreign_path)

    put_response = client.put("/workflow-config", json=imported)
    assert put_response.status_code == 200
    assert put_response.json()["source_path"] == str(foreign_path)

    # Neither the canonical config nor the just-opened file was ever written to.
    assert not isolated_workflow_config_path.exists()
    assert foreign_path.read_bytes() == foreign_bytes

    # Simulates closing and reopening the Préférences dialog -- a fresh GET, no Ouvrir this time.
    reopened = client.get("/workflow-config").json()
    assert reopened["source_path"] == str(foreign_path)
    film_row = next(r for r in reopened["rows"] if r["identifier"] == "film")
    assert "Velvia" not in [v["identifier"] for v in film_row["vignettes"] if v["enabled"]]


def test_put_workflow_config_never_writes_any_file_across_multiple_opens(
    client, isolated_workflow_config_path, tmp_path
):
    """The exact bug report (2026-08-06, then hardened 2026-08-07 after the first fix still wrote
    to whichever file was active): Ouvrir config_workflow.json itself, Valider, open a photo,
    reopen Préférences, Ouvrir a DIFFERENT file (config_workflow-new1.json equivalent), Valider
    again -- NEITHER file may ever be written, no matter which one was "active" when Valider was
    clicked. Only Ouvrir/Exporter may touch a workflow config file."""
    canonical_path = isolated_workflow_config_path
    canonical_dict = json.loads(api_session.DEFAULT_WORKFLOW_CONFIG_PATH.read_text(encoding="utf-8"))
    canonical_bytes = json.dumps(canonical_dict).encode("utf-8")
    canonical_path.write_bytes(canonical_bytes)

    # Step 1-3: Ouvrir the canonical file itself, Valider.
    imported_canonical = client.post("/workflow-config/import", json={"path": str(canonical_path)}).json()
    assert imported_canonical["source_path"] == str(canonical_path)
    put1 = client.put("/workflow-config", json=imported_canonical)
    assert put1.status_code == 200
    assert canonical_path.read_bytes() == canonical_bytes

    # Step 5-7: Ouvrir a SECOND, different file (fewer Film presets), Valider.
    other_dict = json.loads(json.dumps(canonical_dict))
    for row in other_dict["rows"]:
        if row["identifier"] == "film":
            row["thumbnail_presets"] = [p for p in row["thumbnail_presets"] if p != "Velvia"]
    other_path = tmp_path / "config_workflow-new1.json"
    other_bytes = json.dumps(other_dict).encode("utf-8")
    other_path.write_bytes(other_bytes)

    imported_other = client.post("/workflow-config/import", json={"path": str(other_path)}).json()
    put2 = client.put("/workflow-config", json=imported_other)
    assert put2.status_code == 200

    # THE bug: NEITHER file may have been written by either Valider click.
    assert canonical_path.read_bytes() == canonical_bytes
    assert other_path.read_bytes() == other_bytes

    # The in-memory/GET view still correctly reflects the second file's content as active.
    active = client.get("/workflow-config").json()
    assert active["source_path"] == str(other_path)
    active_film = next(r for r in active["rows"] if r["identifier"] == "film")
    assert "Velvia" not in [v["identifier"] for v in active_film["vignettes"] if v["enabled"]]


def test_put_workflow_config_without_reimport_keeps_source_path_unchanged(client, isolated_workflow_config_path):
    """A Valider that never went through "Ouvrir…" this session (plain checkbox edits on whatever
    was already loaded) must round-trip source_path unchanged -- only an actual import should ever
    change what's shown as "loaded"."""
    baseline = client.get("/workflow-config").json()
    original_source_path = baseline["source_path"]
    edited = json.loads(json.dumps(baseline))
    film_row = next(r for r in edited["rows"] if r["identifier"] == "film")
    for vignette in film_row["vignettes"]:
        if vignette["identifier"] == "Velvia":
            vignette["enabled"] = False

    put_response = client.put("/workflow-config", json=edited)
    assert put_response.json()["source_path"] == original_source_path
    assert client.get("/workflow-config").json()["source_path"] == original_source_path


def test_select_vignette_on_disabled_vignette_falls_back_to_neutral(client, isolated_workflow_config_path):
    baseline = client.get("/workflow-config").json()
    edited = json.loads(json.dumps(baseline))
    film_row = next(r for r in edited["rows"] if r["identifier"] == "film")
    for vignette in film_row["vignettes"]:
        if vignette["identifier"] == "Velvia":
            vignette["enabled"] = False
    client.put("/workflow-config", json=edited)

    session_id = _open(client)
    workflow = client.get(f"/sessions/{session_id}/workflow").json()
    film_index = next(i for i, row in enumerate(workflow) if row["label"] == "Film")

    response = client.post(f"/sessions/{session_id}/steps/{film_index}/select", json={"identifier": "Velvia"})
    assert response.status_code == 200
    assert response.json()[film_index]["selected_vignette_identifier"] == "neutral"


def test_apply_recipe_disabled_vignette_falls_back_to_neutral_and_is_reported(
    client, isolated_workflow_config_path, tmp_path
):
    session_id = _open(client)
    recipe_payload = _full_recipe_payload(
        client,
        session_id,
        step_overrides={"film": {"thumbnail_identifier": "Velvia", "parameters": {"look": "velvia", "intensity": 1.0}}},
    )
    recipe_path = tmp_path / "recipe_with_velvia.json"
    recipe_path.write_text(json.dumps(recipe_payload), encoding="utf-8")

    baseline = client.get("/workflow-config").json()
    edited = json.loads(json.dumps(baseline))
    film_row = next(r for r in edited["rows"] if r["identifier"] == "film")
    for vignette in film_row["vignettes"]:
        if vignette["identifier"] == "Velvia":
            vignette["enabled"] = False
    assert client.put("/workflow-config", json=edited).status_code == 200

    new_session_id = _open(client)
    response = client.post(f"/sessions/{new_session_id}/recipe/load", json={"path": str(recipe_path)})
    assert response.status_code == 200
    body = response.json()

    film_index = next(i for i, row in enumerate(body["rows"]) if row["label"] == "Film")
    assert body["rows"][film_index]["selected_vignette_identifier"] == "neutral"
    assert body["disabled_vignette_corrections"] == [
        {"step_identifier": "film", "requested_identifier": "Velvia"}
    ]


def test_apply_recipe_still_applies_a_vignette_that_remains_enabled(client, isolated_workflow_config_path, tmp_path):
    session_id = _open(client)
    recipe_payload = _full_recipe_payload(
        client,
        session_id,
        step_overrides={"film": {"thumbnail_identifier": "Velvia", "parameters": {"look": "velvia", "intensity": 1.0}}},
    )
    recipe_path = tmp_path / "recipe_with_velvia.json"
    recipe_path.write_text(json.dumps(recipe_payload), encoding="utf-8")

    response = client.post(f"/sessions/{session_id}/recipe/load", json={"path": str(recipe_path)})
    assert response.status_code == 200
    body = response.json()

    film_index = next(i for i, row in enumerate(body["rows"]) if row["label"] == "Film")
    assert body["rows"][film_index]["selected_vignette_identifier"] == "Velvia"
    assert body["disabled_vignette_corrections"] == []


def test_refresh_workflow_falls_back_to_neutral_when_open_sessions_selection_becomes_disabled(
    client, isolated_workflow_config_path
):
    """Bug report (2026-08-06 follow-up): Valider must update an already-open photo's filmstrip
    immediately, not just the next photo opened. That immediacy makes a new scenario reachable
    that couldn't happen before: a vignette the open session currently has SELECTED gets disabled
    via Préférences > Workflow while that session stays open. The same "never render a disabled
    vignette" guarantee apply_recipe/select_vignette already enforce must also hold here."""
    session_id = _open(client)
    workflow = client.get(f"/sessions/{session_id}/workflow").json()
    film_index = next(i for i, row in enumerate(workflow) if row["label"] == "Film")

    select_response = client.post(f"/sessions/{session_id}/steps/{film_index}/select", json={"identifier": "Velvia"})
    assert select_response.json()[film_index]["selected_vignette_identifier"] == "Velvia"

    baseline = client.get("/workflow-config").json()
    edited = json.loads(json.dumps(baseline))
    film_row = next(r for r in edited["rows"] if r["identifier"] == "film")
    for vignette in film_row["vignettes"]:
        if vignette["identifier"] == "Velvia":
            vignette["enabled"] = False
    assert client.put("/workflow-config", json=edited).status_code == 200

    # No reopen -- the SAME open session's next filmstrip refresh must self-heal immediately.
    refreshed = client.get(f"/sessions/{session_id}/workflow").json()
    assert refreshed[film_index]["selected_vignette_identifier"] == "neutral"


def test_workflow_config_import_does_not_persist_or_reload(client, isolated_workflow_config_path, tmp_path):
    baseline = client.get("/workflow-config").json()

    foreign_dict = json.loads(api_session.DEFAULT_WORKFLOW_CONFIG_PATH.read_text(encoding="utf-8"))
    for row in foreign_dict["rows"]:
        if row["identifier"] == "film":
            row["thumbnail_presets"] = [p for p in row["thumbnail_presets"] if p != "Velvia"]
    foreign_path = tmp_path / "foreign_workflow.json"
    foreign_path.write_text(json.dumps(foreign_dict), encoding="utf-8")

    response = client.post("/workflow-config/import", json={"path": str(foreign_path)})
    assert response.status_code == 200
    imported = response.json()
    film_row = next(r for r in imported["rows"] if r["identifier"] == "film")
    assert "Velvia" not in [v["identifier"] for v in film_row["vignettes"] if v["enabled"]]

    unchanged = client.get("/workflow-config").json()
    assert unchanged == baseline


def test_workflow_config_import_row_set_mismatch_rejected(client, isolated_workflow_config_path, tmp_path):
    foreign_dict = json.loads(api_session.DEFAULT_WORKFLOW_CONFIG_PATH.read_text(encoding="utf-8"))
    foreign_dict["rows"] = foreign_dict["rows"][:-1]  # drop the last row -- a different row set
    foreign_path = tmp_path / "foreign_workflow.json"
    foreign_path.write_text(json.dumps(foreign_dict), encoding="utf-8")

    response = client.post("/workflow-config/import", json={"path": str(foreign_path)})
    assert response.status_code == 400
    assert response.json()["detail"]["category"] == "row_set_mismatch"


def test_workflow_config_export_pure_file_write_no_reload(client, isolated_workflow_config_path, tmp_path):
    baseline = client.get("/workflow-config").json()
    edited = json.loads(json.dumps(baseline))
    film_row = next(r for r in edited["rows"] if r["identifier"] == "film")
    for vignette in film_row["vignettes"]:
        if vignette["identifier"] == "Velvia":
            vignette["enabled"] = False

    dest = tmp_path / "exported_workflow.json"
    response = client.post("/workflow-config/export", json={"path": str(dest), "rows": edited["rows"]})
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    on_disk = json.loads(dest.read_text(encoding="utf-8"))
    film_on_disk = next(r for r in on_disk["rows"] if r["identifier"] == "film")
    assert "Velvia" not in film_on_disk["thumbnail_presets"]

    unchanged = client.get("/workflow-config").json()
    assert unchanged == baseline
