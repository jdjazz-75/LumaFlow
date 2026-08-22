# LumaFlow v1.0 (2026-08-07)
# Teste UIPreferences/load_preferences/save_preferences : aller-retour, version, repli sur défauts
# (fichier manquant/vide/malformé/version incompatible), clés inconnues ignorées, préférences de
# mise en page, bornes de zoom, et chemin de config workflow mémorisé — sans jamais créer de fichier
# image sur disque.

import json

from lumaflow.persistence.preferences import UIPreferences, load_preferences, save_preferences


def test_load_round_trip(tmp_path):
    prefs = UIPreferences(menu_position="top", menu_collapsed=True)
    path = tmp_path / "prefs.json"
    save_preferences(prefs, path)
    loaded = load_preferences(path)
    assert loaded.menu_position == "top"
    assert loaded.menu_collapsed is True


def test_saved_file_includes_version(tmp_path):
    path = tmp_path / "prefs.json"
    save_preferences(UIPreferences(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "version" in data
    assert data["version"] == 1


def test_load_missing_file_returns_defaults(tmp_path):
    loaded = load_preferences(tmp_path / "nonexistent.json")
    assert loaded.menu_position == "left"
    assert loaded.menu_collapsed is False


def test_load_empty_file_returns_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("", encoding="utf-8")
    loaded = load_preferences(path)
    assert loaded.menu_position == "left"
    assert loaded.menu_collapsed is False


def test_load_malformed_json_returns_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{ this is not json", encoding="utf-8")
    loaded = load_preferences(path)
    assert loaded.menu_position == "left"
    assert loaded.menu_collapsed is False


def test_load_version_incompatible_returns_all_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(
        json.dumps({"version": 999, "menu_position": "top", "menu_collapsed": True}),
        encoding="utf-8",
    )
    loaded = load_preferences(path)
    assert loaded.menu_position == "left"
    assert loaded.menu_collapsed is False


def test_load_does_not_raise_on_any_bad_input(tmp_path):
    # missing file
    load_preferences(tmp_path / "nope.json")

    # empty file
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    load_preferences(empty)

    # malformed JSON
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    load_preferences(bad)

    # version-999
    v999 = tmp_path / "v999.json"
    v999.write_text(json.dumps({"version": 999}), encoding="utf-8")
    load_preferences(v999)


def test_load_unknown_keys_ignored(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(
        json.dumps({"version": 1, "menu_position": "left", "menu_collapsed": False, "future_pref": "hello"}),
        encoding="utf-8",
    )
    loaded = load_preferences(path)
    assert loaded.menu_position == "left"
    assert loaded.menu_collapsed is False


def test_load_missing_known_key_falls_back_to_individual_default(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"version": 1, "menu_position": "top"}), encoding="utf-8")
    loaded = load_preferences(path)
    assert loaded.menu_position == "top"
    assert loaded.menu_collapsed is False


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "sub" / "prefs.json"
    save_preferences(UIPreferences(), path)
    assert path.exists()


# ---------------------------------------------------------------------------
# Layout preferences (row ratio / spacing / vignette margin)
# ---------------------------------------------------------------------------

def test_layout_preferences_round_trip(tmp_path):
    prefs = UIPreferences(
        row_spacing_px=12, vignette_margin_px=4,
        attenuated_opacity_percent=45, row_horizontal_margin_px=22,
    )
    path = tmp_path / "prefs.json"
    save_preferences(prefs, path)
    loaded = load_preferences(path)
    assert loaded.row_spacing_px == 12
    assert loaded.vignette_margin_px == 4
    assert loaded.attenuated_opacity_percent == 45
    assert loaded.row_horizontal_margin_px == 22


def test_layout_preferences_default_when_missing(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"version": 1, "menu_position": "left"}), encoding="utf-8")
    loaded = load_preferences(path)
    assert loaded.row_spacing_px == 8
    assert loaded.vignette_margin_px == 8
    assert loaded.attenuated_opacity_percent == 80
    assert loaded.row_horizontal_margin_px == 8


def test_layout_preferences_out_of_range_falls_back_to_default(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "row_spacing_px": -5,
                "vignette_margin_px": "not a number",
                "attenuated_opacity_percent": 500,
                "row_horizontal_margin_px": -5,
            }
        ),
        encoding="utf-8",
    )
    loaded = load_preferences(path)
    assert loaded.row_spacing_px == 8
    assert loaded.vignette_margin_px == 8
    assert loaded.attenuated_opacity_percent == 80
    assert loaded.row_horizontal_margin_px == 8


def test_active_row_ratio_percent_key_from_old_file_is_ignored(tmp_path):
    # 2026-07-13 ergonomics correction: a preferences.json saved by an older
    # build may still carry this now-removed key. It must be silently
    # ignored, exactly like any other unknown key (test_load_unknown_keys_ignored).
    path = tmp_path / "prefs.json"
    path.write_text(
        json.dumps({"version": 1, "menu_position": "left", "active_row_ratio_percent": 70}),
        encoding="utf-8",
    )
    loaded = load_preferences(path)
    assert loaded.menu_position == "left"
    assert not hasattr(loaded, "active_row_ratio_percent")


# ---------------------------------------------------------------------------
# Zoom bounds (Préférences > Général > Zoom)
# ---------------------------------------------------------------------------

def test_zoom_bounds_default_when_missing(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"version": 1, "menu_position": "left"}), encoding="utf-8")
    loaded = load_preferences(path)
    assert loaded.zoom_min_percent == 20
    assert loaded.zoom_max_percent == 400


def test_zoom_bounds_round_trip(tmp_path):
    prefs = UIPreferences(zoom_min_percent=30, zoom_max_percent=500)
    path = tmp_path / "prefs.json"
    save_preferences(prefs, path)
    loaded = load_preferences(path)
    assert loaded.zoom_min_percent == 30
    assert loaded.zoom_max_percent == 500


def test_zoom_bounds_out_of_range_falls_back_to_default(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(
        json.dumps({"version": 1, "zoom_min_percent": 0, "zoom_max_percent": 5000}),
        encoding="utf-8",
    )
    loaded = load_preferences(path)
    assert loaded.zoom_min_percent == 20
    assert loaded.zoom_max_percent == 400


def test_zoom_bounds_disjoint_ranges_cannot_invert(tmp_path):
    # zoom_min_percent's own valid range (1-100) and zoom_max_percent's
    # (100-2000) never overlap into an inverted pair: an individually-valid
    # max (e.g. 80 is below ZOOM_MAX_PERCENT_MIN) falls back to its own
    # default independently of whatever zoom_min_percent was given.
    path = tmp_path / "prefs.json"
    path.write_text(
        json.dumps({"version": 1, "zoom_min_percent": 90, "zoom_max_percent": 80}),
        encoding="utf-8",
    )
    loaded = load_preferences(path)
    assert loaded.zoom_min_percent == 90
    assert loaded.zoom_max_percent == 400


# ---------------------------------------------------------------------------
# Préférences > Workflow's remembered source file (2026-08-06 follow-up: must
# survive an app restart, mirrors presets_directory/open_image_directory's shape).
# ---------------------------------------------------------------------------

def test_workflow_config_source_path_round_trip(tmp_path):
    foreign = tmp_path / "foreign_workflow.json"
    prefs = UIPreferences(workflow_config_source_path=str(foreign))
    path = tmp_path / "prefs.json"
    save_preferences(prefs, path)
    loaded = load_preferences(path)
    assert loaded.workflow_config_source_path == str(foreign)


def test_workflow_config_source_path_default_when_missing(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"version": 1, "menu_position": "left"}), encoding="utf-8")
    loaded = load_preferences(path)
    assert loaded.workflow_config_source_path is None


def test_workflow_config_source_path_non_string_falls_back_to_none(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"version": 1, "workflow_config_source_path": 42}), encoding="utf-8")
    loaded = load_preferences(path)
    assert loaded.workflow_config_source_path is None


def test_no_image_file_created_during_save_or_load(tmp_path):
    path = tmp_path / "prefs.json"
    save_preferences(UIPreferences(), path)
    load_preferences(path)
    image_suffixes = {".jpg", ".png", ".tiff", ".raw", ".nef", ".cr2", ".dng"}
    for f in tmp_path.rglob("*"):
        assert f.suffix.lower() not in image_suffixes, f"Image file found: {f}"
