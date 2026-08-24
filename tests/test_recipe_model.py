# LumaFlow v1.0 (2026-08-07)
# Teste le modèle de recette (persistence/recipe.py) : sérialisation/désérialisation fidèle, version
# de schéma (1.1 -- plus de bloc `source`, Geometry/Framing exclus), sauvegarde/chargement
# atomiques, détection d'addons manquants, rejet de version de schéma non reconnue, compatibilité
# ascendante silencieuse avec un fichier v1 (bloc `source` + steps Geometry/Framing), et absence
# d'import moteur/Qt dans le module.

import json
import os
from pathlib import Path

import pytest

from lumaflow.persistence.recipe import (
    EXCLUDED_STEP_IDENTIFIERS,
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    MissingAddonReport,
    Recipe,
    RecipeIOError,
    RecipeIOErrorCategory,
    RecipeValidationError,
    StepEntry,
    check_addon_availability,
    check_schema_version,
    example_recipe,
    load_recipe,
    recipe_from_dict,
    recipe_to_dict,
    save_recipe,
    validate_session_completeness,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _build_recipe() -> Recipe:
    return Recipe(
        schema_version=SCHEMA_VERSION,
        steps=[
            StepEntry("crop", "crop_neutral", {}),
            StepEntry("exposure", "exposure_plus1", {"ev": 1.0}),
        ],
    )


# --- US1: Editing Session Captured as a Replayable Recipe ---


def test_recipe_represents_full_step_order_and_fidelity():
    recipe = _build_recipe()
    restored = recipe_from_dict(recipe_to_dict(recipe))

    assert len(restored.steps) == len(recipe.steps) == 2
    for original, round_tripped in zip(recipe.steps, restored.steps):
        assert round_tripped.step_identifier == original.step_identifier
        assert round_tripped.thumbnail_identifier == original.thumbnail_identifier
        assert round_tripped.parameters == original.parameters


def test_neutral_step_present_with_empty_parameters():
    recipe = _build_recipe()
    neutral_step = recipe.steps[0]
    assert neutral_step in recipe.steps
    assert neutral_step.parameters == {}


def test_enriched_step_preserves_parameter_values_exactly():
    recipe = _build_recipe()
    restored = recipe_from_dict(recipe_to_dict(recipe))
    assert restored.steps[1].parameters["ev"] == 1.0


def test_recipe_to_dict_only_json_compatible_types():
    recipe = _build_recipe()
    data = recipe_to_dict(recipe)

    def _walk(value):
        assert isinstance(value, (str, int, float, bool, dict, list, type(None)))
        if isinstance(value, dict):
            for v in value.values():
                _walk(v)
        elif isinstance(value, list):
            for v in value:
                _walk(v)

    _walk(data)


def test_recipe_to_dict_never_carries_a_source_block():
    # The preset no longer references the file it was authored on (CLAUDE.md, 2026-08-24).
    data = recipe_to_dict(_build_recipe())
    assert "source" not in data


# --- US2: Recipe Identified by Schema Version ---


def test_schema_version_present_and_nonempty():
    recipe = _build_recipe()
    assert recipe.schema_version == SCHEMA_VERSION
    assert recipe.schema_version


def test_schema_version_is_1_1():
    assert SCHEMA_VERSION == "1.1"


def test_missing_schema_version_rejected():
    data = recipe_to_dict(_build_recipe())
    del data["schema_version"]
    try:
        recipe_from_dict(data)
        assert False, "expected RecipeValidationError"
    except RecipeValidationError as exc:
        assert exc.reason == "missing_field"


def test_empty_schema_version_rejected():
    data = recipe_to_dict(_build_recipe())
    data["schema_version"] = ""
    try:
        recipe_from_dict(data)
        assert False, "expected RecipeValidationError"
    except RecipeValidationError as exc:
        assert exc.reason == "empty_schema_version"


# --- Geometry/Framing excluded from every recipe (2026-08-24) ---


def test_geometry_and_framing_step_entries_are_dropped_on_load():
    # A recipe file that still lists Geometry/Framing (hand-crafted, or a v1 file authored before
    # this exclusion existed) must load without error or warning -- those two entries are simply
    # absent from the resulting Recipe.steps, same as if the file never mentioned them.
    data = {
        "schema_version": SCHEMA_VERSION,
        "steps": [
            {"step_identifier": "geometry", "thumbnail_identifier": "neutral", "parameters": {"angle": 12.0}},
            {"step_identifier": "framing", "thumbnail_identifier": "neutral", "parameters": {"crop_x": 0.1}},
            {"step_identifier": "film", "thumbnail_identifier": "neutral", "parameters": {}},
        ],
    }
    recipe = recipe_from_dict(data)
    assert [s.step_identifier for s in recipe.steps] == ["film"]


def test_excluded_step_identifiers_is_geometry_and_framing():
    assert EXCLUDED_STEP_IDENTIFIERS == frozenset({"geometry", "framing"})


# --- US3 (legacy): backward compatibility with a v1 file (source block + no exclusion) ---


def test_load_recipe_v1_fixture_drops_source_and_keeps_its_steps(tmp_path):
    # tests/fixtures/recipe_example_v1.json is a genuine pre-1.1 file: it still carries the
    # `source` block. Loading it must not error or warn -- the block is simply never read.
    loaded = load_recipe(FIXTURES_DIR / "recipe_example_v1.json")
    assert [s.step_identifier for s in loaded.steps] == ["crop", "exposure"]
    assert not hasattr(loaded, "source")


def test_load_recipe_v1_fixture_with_unrelated_source_still_loads(tmp_path):
    original = json.loads((FIXTURES_DIR / "recipe_example_v1.json").read_text(encoding="utf-8"))
    assert original["schema_version"] == "1"
    assert "source" in original  # sanity: this fixture predates 1.1's schema

    recipe = recipe_from_dict(original)
    # Re-serializing never reintroduces the now-obsolete `source` block.
    assert recipe_to_dict(recipe) == {"schema_version": "1", "steps": original["steps"]}


# --- F-015 US1: Save Current Editing Choices to a Recipe File ---


def test_save_recipe_writes_valid_indented_json(tmp_path):
    recipe = _build_recipe()
    dest = tmp_path / "recipe.json"
    save_recipe(recipe, dest)

    assert dest.exists()
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert recipe_from_dict(data) == recipe


def test_validate_session_completeness_rejects_empty_steps():
    with pytest.raises(RecipeValidationError) as exc_info:
        validate_session_completeness([])
    assert exc_info.value.reason == "empty_session"

    validate_session_completeness([StepEntry("crop", "crop_neutral", {})])


def test_save_recipe_atomic_no_partial_file_on_failure(tmp_path, monkeypatch):
    recipe = _build_recipe()
    dest = tmp_path / "recipe.json"

    monkeypatch.setattr(os, "replace", lambda *a, **kw: (_ for _ in ()).throw(OSError("boom")))

    with pytest.raises(RecipeIOError):
        save_recipe(recipe, dest)

    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


# --- F-016 US1: Resume a Previous Editing Session from a Recipe File ---


def test_load_recipe_round_trips_saved_session(tmp_path):
    recipe = _build_recipe()
    dest = tmp_path / "recipe.json"
    save_recipe(recipe, dest)

    loaded = load_recipe(dest)
    assert loaded == recipe


def test_load_recipe_round_trips_neutral_thumbnail_identifier(tmp_path):
    # F-026 §5.1: the reserved "neutral" identifier is an ordinary StepEntry
    # value to this layer -- no special-casing required in recipe.py.
    recipe = Recipe(
        schema_version=SCHEMA_VERSION,
        steps=[StepEntry("crop", "neutral", {})],
    )
    dest = tmp_path / "recipe.json"
    save_recipe(recipe, dest)

    loaded = load_recipe(dest)
    assert loaded.steps[0].thumbnail_identifier == "neutral"
    assert loaded.steps[0] == recipe.steps[0]


def test_load_recipe_accepts_committed_f014_fixture():
    loaded = load_recipe(FIXTURES_DIR / "recipe_example_v1.json")
    assert [s.step_identifier for s in loaded.steps] == ["crop", "exposure"]


# --- F-016 US2: Reject Invalid or Malformed Recipe Files Clearly ---


def test_load_recipe_missing_file(tmp_path):
    with pytest.raises(RecipeIOError) as exc_info:
        load_recipe(tmp_path / "does_not_exist.json")
    assert exc_info.value.category == RecipeIOErrorCategory.MISSING_FILE


def test_load_recipe_malformed_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RecipeValidationError) as exc_info:
        load_recipe(bad)
    assert exc_info.value.reason == "invalid_json"


def test_load_recipe_missing_required_field(tmp_path):
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"steps": []}), encoding="utf-8")
    with pytest.raises(RecipeValidationError) as exc_info:
        load_recipe(incomplete)
    assert exc_info.value.reason == "missing_field"


def test_three_failure_reasons_are_distinguishable(tmp_path):
    with pytest.raises(RecipeIOError) as missing_exc:
        load_recipe(tmp_path / "ghost.json")

    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RecipeValidationError) as json_exc:
        load_recipe(bad)

    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"steps": []}), encoding="utf-8")
    with pytest.raises(RecipeValidationError) as field_exc:
        load_recipe(incomplete)

    assert missing_exc.value.category == RecipeIOErrorCategory.MISSING_FILE
    assert json_exc.value.reason == "invalid_json"
    assert field_exc.value.reason == "missing_field"
    assert json_exc.value.reason != field_exc.value.reason


def test_check_addon_availability_reports_missing_by_exact_id():
    steps = [StepEntry("crop", "crop_neutral", {}), StepEntry("exposure", "exposure_plus1", {})]
    report = check_addon_availability(steps, available_addon_ids={"crop"})
    assert isinstance(report, MissingAddonReport)
    assert report.missing_addon_ids == ["exposure"]


def test_check_addon_availability_none_is_permissive():
    steps = [StepEntry("crop", "crop_neutral", {}), StepEntry("exposure", "exposure_plus1", {})]
    assert check_addon_availability(steps, available_addon_ids=None) is None


def test_check_addon_availability_all_present_returns_none():
    steps = [StepEntry("crop", "crop_neutral", {}), StepEntry("exposure", "exposure_plus1", {})]
    assert check_addon_availability(steps, available_addon_ids={"crop", "exposure"}) is None


# --- F-018 US1: Load a Recipe with a Recognized Schema Version ---


def test_current_version_recipe_loads_without_error(tmp_path):
    recipe = _build_recipe()
    dest = tmp_path / "recipe.json"
    save_recipe(recipe, dest)

    loaded = load_recipe(dest)
    assert loaded.schema_version == SCHEMA_VERSION


def test_check_schema_version_accepts_current_version():
    recipe = _build_recipe()
    assert check_schema_version(recipe) is None


def test_legacy_v1_version_is_still_supported():
    assert "1" in SUPPORTED_SCHEMA_VERSIONS
    recipe = Recipe(schema_version="1", steps=[StepEntry("crop", "crop_neutral", {})])
    assert check_schema_version(recipe) is None


def test_load_recipe_still_accepts_f014_fixture():
    # The fixture's own on-disk schema_version ("1") is preserved as-is -- loading an old file
    # does not silently rewrite it to the current version.
    loaded = load_recipe(FIXTURES_DIR / "recipe_example_v1.json")
    assert loaded.schema_version == "1"


# --- F-018 US2: Reject a Recipe with an Unknown Schema Version Clearly ---


def test_check_schema_version_rejects_unrecognized_version():
    recipe = Recipe(schema_version="99", steps=[])
    with pytest.raises(RecipeValidationError) as exc_info:
        check_schema_version(recipe, supported_versions={"1"})
    assert exc_info.value.reason == "unrecognized_schema_version"


def test_load_recipe_rejects_unrecognized_version_end_to_end(tmp_path):
    data = recipe_to_dict(_build_recipe())
    data["schema_version"] = "99"
    bad = tmp_path / "future.json"
    bad.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RecipeValidationError) as exc_info:
        load_recipe(bad)
    assert exc_info.value.reason == "unrecognized_schema_version"


def test_unrecognized_version_reason_distinct_from_other_reasons(tmp_path):
    other_reasons = {"invalid_json", "missing_field", "invalid_type", "empty_schema_version"}
    assert "unrecognized_schema_version" not in other_reasons

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RecipeValidationError) as malformed_exc:
        load_recipe(malformed)

    data = recipe_to_dict(_build_recipe())
    data["schema_version"] = "99"
    future = tmp_path / "future.json"
    future.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RecipeValidationError) as future_exc:
        load_recipe(future)

    assert malformed_exc.value.reason != future_exc.value.reason


# --- F-018 US3: Version Field Present and Consistent in Every Saved Recipe ---


def test_save_recipe_output_carries_current_version(tmp_path):
    dest = tmp_path / "recipe.json"
    save_recipe(_build_recipe(), dest)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["schema_version"]


def test_example_recipe_carries_current_version():
    assert example_recipe().schema_version == SCHEMA_VERSION


def test_two_saved_recipes_share_identical_version(tmp_path):
    recipe_a = _build_recipe()
    recipe_b = Recipe(
        schema_version=SCHEMA_VERSION,
        steps=[StepEntry("crop", "crop_neutral", {})],
    )
    dest_a = tmp_path / "a.json"
    dest_b = tmp_path / "b.json"
    save_recipe(recipe_a, dest_a)
    save_recipe(recipe_b, dest_b)

    data_a = json.loads(dest_a.read_text(encoding="utf-8"))
    data_b = json.loads(dest_b.read_text(encoding="utf-8"))
    assert data_a["schema_version"] == data_b["schema_version"] == SCHEMA_VERSION


# --- Polish: structural boundary check ---


def test_recipe_module_has_no_engine_or_qt_imports():
    source_text = Path("lumaflow/persistence/recipe.py").read_text(encoding="utf-8")
    for forbidden in ("lumaflow.engine", "PySide6", "PyQt5", "PyQt6"):
        assert forbidden not in source_text
