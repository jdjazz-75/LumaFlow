# LumaFlow v1.0 (2026-08-07)
# Teste le modèle de recette (persistence/recipe.py) : sérialisation/désérialisation fidèle, version
# de schéma, usage sans fichier source présent, sauvegarde/chargement atomiques, détection d'addons
# manquants, rejet de version de schéma non reconnue, et absence d'import moteur/Qt dans le module.

import json
import os
from pathlib import Path

import pytest

from lumaflow.persistence.recipe import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    MissingAddonReport,
    Recipe,
    RecipeIOError,
    RecipeIOErrorCategory,
    RecipeValidationError,
    SourceReference,
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
        source=SourceReference(filename="beach.jpg", width=100, height=200, checksum="abc123"),
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


# --- US2: Recipe Identified by Schema Version ---


def test_schema_version_present_and_nonempty():
    recipe = _build_recipe()
    assert recipe.schema_version == SCHEMA_VERSION
    assert recipe.schema_version


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


# --- US3: Recipe Usable Without the Original Source File ---


def test_recipe_valid_without_source_file_present():
    recipe = Recipe(
        schema_version=SCHEMA_VERSION,
        source=SourceReference(filename="does_not_exist_on_this_machine.jpg"),
        steps=[],
    )
    restored = recipe_from_dict(recipe_to_dict(recipe))
    assert restored.source.filename == "does_not_exist_on_this_machine.jpg"


def test_minimal_source_reference_valid():
    recipe = Recipe(schema_version=SCHEMA_VERSION, source=SourceReference(filename="x.jpg"), steps=[])
    restored = recipe_from_dict(recipe_to_dict(recipe))
    assert restored.source.filename == "x.jpg"
    assert restored.source.width is None
    assert restored.source.height is None
    assert restored.source.checksum is None


def test_two_recipes_same_filename_independently_valid():
    recipe_a = Recipe(schema_version=SCHEMA_VERSION, source=SourceReference(filename="shared.jpg"), steps=[])
    recipe_b = Recipe(schema_version=SCHEMA_VERSION, source=SourceReference(filename="shared.jpg"), steps=[])
    recipe_from_dict(recipe_to_dict(recipe_a))
    recipe_from_dict(recipe_to_dict(recipe_b))


def test_committed_fixture_round_trips():
    original = json.loads((FIXTURES_DIR / "recipe_example_v1.json").read_text(encoding="utf-8"))
    recipe = recipe_from_dict(original)
    assert recipe_to_dict(recipe) == original

    neutral_steps = [s for s in recipe.steps if s.parameters == {}]
    enriched_steps = [s for s in recipe.steps if s.parameters != {}]
    assert len(neutral_steps) == 1
    assert len(enriched_steps) == 1


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
        source=SourceReference(filename="beach.jpg"),
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


def test_load_recipe_machine_independent(tmp_path):
    recipe = Recipe(
        schema_version=SCHEMA_VERSION,
        source=SourceReference(filename="does_not_exist_anywhere.jpg"),
        steps=[StepEntry("crop", "crop_neutral", {})],
    )
    dest = tmp_path / "recipe.json"
    save_recipe(recipe, dest)
    loaded = load_recipe(dest)
    assert loaded.source.filename == "does_not_exist_anywhere.jpg"


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
    incomplete.write_text(json.dumps({"source": {"filename": "x.jpg"}, "steps": []}), encoding="utf-8")
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
    incomplete.write_text(json.dumps({"source": {"filename": "x.jpg"}, "steps": []}), encoding="utf-8")
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


def test_load_recipe_still_accepts_f014_fixture():
    loaded = load_recipe(FIXTURES_DIR / "recipe_example_v1.json")
    assert loaded.schema_version == SCHEMA_VERSION


# --- F-018 US2: Reject a Recipe with an Unknown Schema Version Clearly ---


def test_check_schema_version_rejects_unrecognized_version():
    recipe = Recipe(schema_version="99", source=SourceReference(filename="x.jpg"), steps=[])
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
        source=SourceReference(filename="other.jpg"),
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
