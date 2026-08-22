# LumaFlow v1.0 (2026-08-07)
# Teste le chargement/validation/sauvegarde de la configuration de workflow (config/workflow.py) :
# ordre des lignes tel que déclaré, addons/catégories/presets indisponibles signalés par ligne,
# erreurs de chargement distinctes (fichier manquant/JSON invalide/structure invalide), et
# cohérence des lignes réelles (film/bleach_bypass/color_splash/monochrome/bw/light) avec les
# addons réellement chargés.

import pathlib

import pytest

from lumaflow.addons.contract import AddonDescriptor, ThumbnailPreset
from lumaflow.config.workflow import (
    WorkflowConfig,
    WorkflowConfigIOError,
    WorkflowConfigIOErrorCategory,
    WorkflowConfigValidationError,
    WorkflowRow,
    catalog_thumbnail_presets,
    load_workflow_config,
    resolve_row_addons,
    save_workflow_config,
    validate_workflow_config,
    workflow_config_from_dict,
)

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURES_ROOT = REPO_ROOT / "tests" / "fixtures" / "workflow_config"


# --- User Story 1: A Minimal Workflow Is Loaded From Configuration, in File Order ---


def test_rows_load_in_exact_file_order():
    config = load_workflow_config(FIXTURES_ROOT / "minimal_valid.json")
    assert [row.category or tuple(row.addon_identifiers) for row in config.rows] == [
        "geometry",
        ("light_intensity",),
        "film",
    ]


def test_loaded_row_exposes_category_and_presets_matching_file():
    config = load_workflow_config(FIXTURES_ROOT / "minimal_valid.json")
    assert config.rows[0].category == "geometry"
    assert config.rows[0].thumbnail_presets == ("neutral",)
    assert config.rows[1].addon_identifiers == ("light_intensity",)
    assert config.rows[1].thumbnail_presets == ()
    assert config.rows[2].category == "film"
    assert config.rows[2].thumbnail_presets == ("neutral",)


def test_zero_rows_config_loads_successfully():
    config = workflow_config_from_dict({"rows": []})
    assert config.rows == ()


def test_identifier_and_label_optional_fields_round_trip():
    config = workflow_config_from_dict(
        {"rows": [{"category": "x", "identifier": "row1", "label": "Row One"}]}
    )
    assert config.rows[0].identifier == "row1"
    assert config.rows[0].label == "Row One"

    config_without = workflow_config_from_dict({"rows": [{"category": "x"}]})
    assert config_without.rows[0].identifier is None
    assert config_without.rows[0].label is None


def test_short_description_optional_field_round_trips():
    config = workflow_config_from_dict(
        {"rows": [{"category": "x", "short_description": "A short description"}]}
    )
    assert config.rows[0].short_description == "A short description"

    config_without = workflow_config_from_dict({"rows": [{"category": "x"}]})
    assert config_without.rows[0].short_description is None


def test_short_description_wrong_type_raises_validation_error():
    with pytest.raises(WorkflowConfigValidationError) as exc_info:
        workflow_config_from_dict({"rows": [{"category": "x", "short_description": 42}]})
    assert exc_info.value.reason == "invalid_type"


# --- User Story 2: A Row Referencing an Unavailable Addon Is Flagged, Not Silently Dropped ---


def test_unavailable_specific_addon_identifier_flagged_by_row_and_name():
    config = WorkflowConfig(
        rows=(
            WorkflowRow(addon_identifiers=("light_intensity",)),
            WorkflowRow(addon_identifiers=("missing_addon",)),
        )
    )
    addon_index = {"light_intensity": AddonDescriptor(identifier="light_intensity", category="light")}

    result = validate_workflow_config(config, addon_index)

    matching = [issue for issue in result.issues if issue.row_index == 1]
    assert len(matching) == 1
    assert matching[0].reason == "unavailable_addon"
    assert matching[0].detail == "missing_addon"


def test_only_offending_row_flagged_among_several():
    config = WorkflowConfig(
        rows=(
            WorkflowRow(addon_identifiers=("light_intensity",)),
            WorkflowRow(addon_identifiers=("missing_addon",)),
        )
    )
    addon_index = {"light_intensity": AddonDescriptor(identifier="light_intensity", category="light")}

    result = validate_workflow_config(config, addon_index)

    assert not any(issue.row_index == 0 for issue in result.issues)
    assert any(issue.row_index == 1 for issue in result.issues)


def test_zero_match_category_flagged_distinctly_from_missing_identifier():
    config = WorkflowConfig(rows=(WorkflowRow(category="vignette"),))
    result = validate_workflow_config(config, addon_index={})

    assert result.issues[0].reason == "unavailable_category"
    assert result.issues[0].detail == "vignette"


def test_unknown_thumbnail_preset_flagged_distinctly_and_skipped_when_reference_unavailable():
    # (a) reference resolves, but a declared preset is not among the resolved addon's presets
    resolvable_config = WorkflowConfig(
        rows=(
            WorkflowRow(
                addon_identifiers=("light_intensity",), thumbnail_presets=("does_not_exist",)
            ),
        )
    )
    addon_index = {
        "light_intensity": AddonDescriptor(
            identifier="light_intensity",
            category="light",
            thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),),
        )
    }
    result = validate_workflow_config(resolvable_config, addon_index)
    assert len(result.issues) == 1
    assert result.issues[0].reason == "unknown_thumbnail_preset"
    assert result.issues[0].detail == "does_not_exist"

    # (b) reference itself is unavailable — no additional preset-related issue
    unresolvable_config = WorkflowConfig(
        rows=(
            WorkflowRow(
                addon_identifiers=("missing_addon",), thumbnail_presets=("does_not_exist",)
            ),
        )
    )
    result = validate_workflow_config(unresolvable_config, addon_index={})
    assert len(result.issues) == 1
    assert result.issues[0].reason == "unavailable_addon"


def test_empty_addon_index_fails_every_referencing_row_no_special_case():
    config = WorkflowConfig(
        rows=(
            WorkflowRow(addon_identifiers=("light_intensity",)),
            WorkflowRow(category="vignette"),
        )
    )
    result = validate_workflow_config(config, addon_index={})

    reasons = {issue.row_index: issue.reason for issue in result.issues}
    assert reasons[0] == "unavailable_addon"
    assert reasons[1] == "unavailable_category"


def test_repeated_category_or_identifier_across_rows_is_valid():
    config = WorkflowConfig(
        rows=(
            WorkflowRow(category="light"),
            WorkflowRow(category="light"),
        )
    )
    addon_index = {"light_intensity": AddonDescriptor(identifier="light_intensity", category="light")}

    result = validate_workflow_config(config, addon_index)
    assert result.valid is True


# --- User Story 3: Absent or Invalid Configuration Never Produces a Silent or Confusing Startup ---


def test_missing_file_raises_workflow_config_io_error_missing_file():
    with pytest.raises(WorkflowConfigIOError) as exc_info:
        load_workflow_config(REPO_ROOT / "does" / "not" / "exist.json")
    assert exc_info.value.category is WorkflowConfigIOErrorCategory.MISSING_FILE


def test_invalid_json_raises_validation_error_distinct_from_missing_file():
    with pytest.raises(WorkflowConfigValidationError) as exc_info:
        load_workflow_config(FIXTURES_ROOT / "invalid_json.json")
    assert exc_info.value.reason == "invalid_json"


def test_missing_rows_structure_raises_validation_error_distinct_from_other_two():
    with pytest.raises(WorkflowConfigValidationError) as exc_info:
        load_workflow_config(FIXTURES_ROOT / "missing_rows.json")
    assert exc_info.value.reason in {"missing_field", "invalid_type"}


def test_no_silent_fallback_ever_returned_on_any_failure():
    for path, expected_exception in (
        (REPO_ROOT / "does" / "not" / "exist.json", WorkflowConfigIOError),
        (FIXTURES_ROOT / "invalid_json.json", WorkflowConfigValidationError),
        (FIXTURES_ROOT / "missing_rows.json", WorkflowConfigValidationError),
    ):
        with pytest.raises(expected_exception):
            load_workflow_config(path)


# --- Phase 6: Polish & Cross-Cutting Concerns ---


def test_structural_loading_and_semantic_validation_are_independently_callable():
    config = load_workflow_config(FIXTURES_ROOT / "minimal_valid.json")
    result = validate_workflow_config(config, addon_index={})
    assert not result.valid


# --- Feature 041: the real `framing` row's new preset list validates against ---
# --- the real, loaded Framing addon (not a fixture). ---


def test_real_framing_row_new_preset_list_validates_against_loaded_addon():
    from lumaflow.addons.loader import DiscoveryLocation, load_addons

    builtin_root = REPO_ROOT / "lumaflow" / "addons" / "builtin"
    addon_index = load_addons(DiscoveryLocation(path=builtin_root)).index
    config = load_workflow_config(REPO_ROOT / "lumaflow" / "config" / "config_workflow.json")

    framing_row = next(row for row in config.rows if row.identifier == "framing")
    # Free-form crop only (no aspect-ratio-locked presets) since the crop-frame rework.
    assert framing_row.thumbnail_presets == ("neutral",)

    result = validate_workflow_config(config, addon_index)
    assert not any(
        issue.reason == "unknown_thumbnail_preset" for issue in result.issues
    )


# --- Feature 042: the real `film` row's preset list validates against ---
# --- the real, loaded Film addon (not a fixture). ---


def test_real_film_row_new_preset_list_validates_against_loaded_addon():
    from lumaflow.addons.loader import DiscoveryLocation, load_addons

    builtin_root = REPO_ROOT / "lumaflow" / "addons" / "builtin"
    addon_index = load_addons(DiscoveryLocation(path=builtin_root)).index
    config = load_workflow_config(REPO_ROOT / "lumaflow" / "config" / "config_workflow.json")

    film_row = next(row for row in config.rows if row.identifier == "film")
    # config_workflow.json's per-row thumbnail_presets became live, user-editable content via
    # Préférences > Workflow (2026-08-06): enabling/disabling/reordering vignettes there rewrites
    # this exact file, so the precise list is no longer a fixed historical curation to lock in
    # here (unlike before that feature -- see git history for the retired literal-tuple version of
    # this assertion). What stays a real invariant regardless of how the user has curated it:
    # "neutral" leads, and every entry is a preset the loaded Film addon actually declares.
    assert film_row.thumbnail_presets[0] == "neutral"
    declared = {identifier for identifier, _label in catalog_thumbnail_presets(film_row, addon_index)}
    assert set(film_row.thumbnail_presets) <= declared

    result = validate_workflow_config(config, addon_index)
    assert not any(
        issue.reason == "unknown_thumbnail_preset" for issue in result.issues
    )


# --- 2026-07-25: the real `bleach_bypass` row sits between `film` and `color_splash`, ---
# --- shares the Film addon's category, and validates against the loaded addon. ---


def test_real_bleach_bypass_row_positioned_between_film_and_color_splash_and_validates():
    from lumaflow.addons.loader import DiscoveryLocation, load_addons

    builtin_root = REPO_ROOT / "lumaflow" / "addons" / "builtin"
    addon_index = load_addons(DiscoveryLocation(path=builtin_root)).index
    config = load_workflow_config(REPO_ROOT / "lumaflow" / "config" / "config_workflow.json")

    identifiers = [row.identifier for row in config.rows]
    assert identifiers.index("bleach_bypass") == identifiers.index("film") + 1
    assert identifiers.index("color_splash") == identifiers.index("bleach_bypass") + 1

    bleach_bypass_row = next(row for row in config.rows if row.identifier == "bleach_bypass")
    assert bleach_bypass_row.category == "film"  # same addon as "film", split preset subset
    # Live, user-editable content since Préférences > Workflow (2026-08-06) -- see
    # test_real_film_row_new_preset_list_validates_against_loaded_addon's comment for why this is
    # no longer a fixed literal tuple.
    assert bleach_bypass_row.thumbnail_presets[0] == "neutral"
    declared = {identifier for identifier, _label in catalog_thumbnail_presets(bleach_bypass_row, addon_index)}
    assert set(bleach_bypass_row.thumbnail_presets) <= declared

    result = validate_workflow_config(config, addon_index)
    assert not any(
        issue.reason == "unknown_thumbnail_preset" for issue in result.issues
    )


# --- Feature 046: the real `color_splash` row is positioned after `film`/`bleach_bypass` ---
# --- and validates against the real, loaded Color Splash addon (not a fixture). ---


def test_real_color_splash_row_positioned_after_bleach_bypass_and_validates_against_loaded_addon():
    from lumaflow.addons.loader import DiscoveryLocation, load_addons

    builtin_root = REPO_ROOT / "lumaflow" / "addons" / "builtin"
    addon_index = load_addons(DiscoveryLocation(path=builtin_root)).index
    config = load_workflow_config(REPO_ROOT / "lumaflow" / "config" / "config_workflow.json")

    identifiers = [row.identifier for row in config.rows]
    assert identifiers.index("color_splash") == identifiers.index("bleach_bypass") + 1

    color_splash_row = next(row for row in config.rows if row.identifier == "color_splash")
    assert color_splash_row.thumbnail_presets == (
        "neutral", "Rouge", "Orange", "Jaune", "Vert", "Bleu", "Violet",
    )

    result = validate_workflow_config(config, addon_index)
    assert not any(
        issue.reason == "unknown_thumbnail_preset" for issue in result.issues
    )


# --- 2026-07-26: the real `monochrome` row sits between `color_splash` and `light`, ---
# --- shares the Film addon's category, and validates against the loaded addon. ---


def test_real_monochrome_row_positioned_between_color_splash_and_light_and_validates():
    from lumaflow.addons.loader import DiscoveryLocation, load_addons

    builtin_root = REPO_ROOT / "lumaflow" / "addons" / "builtin"
    addon_index = load_addons(DiscoveryLocation(path=builtin_root)).index
    config = load_workflow_config(REPO_ROOT / "lumaflow" / "config" / "config_workflow.json")

    identifiers = [row.identifier for row in config.rows]
    assert identifiers.index("monochrome") == identifiers.index("color_splash") + 1
    # "bw" (2026-07-26, later the same day) now sits between "monochrome" and
    # "light" -- see test_real_bw_row_positioned_between_monochrome_and_light_and_validates.
    assert identifiers.index("bw") == identifiers.index("monochrome") + 1

    monochrome_row = next(row for row in config.rows if row.identifier == "monochrome")
    # "Mono Moonlight" moved out to the "bw" row 2026-07-27 (same day); later
    # that day "Monochrome"/"Underglow"/"Gilt Trip" were retired outright (user
    # request, film.py's module docstring), and "Titanium"/"Milestone"/
    # "Quicklime" moved out to "bleach_bypass" (config-only), leaving the row
    # briefly empty. Still later the same day: the row was repointed to a
    # brand-new, dedicated addon (`monochrome_tone.py` -- a duotone/colorize
    # addon, distinct from film_look) with 5 new presets (Ambre/Bleu Nuit/Vert
    # Cactus/Jaune Léger/Sépia Chaud). category changes from "film" to
    # "monochrome_tone" accordingly -- this is the first row NOT sharing
    # film_look's category among film/bleach_bypass/monochrome/bw. Revised yet
    # again the same day, once the Zoom's ColorWheel picker existed: the 5
    # presets above were replaced by 6 hex-derived ones (Rouge/Sepia/Jaune/
    # Vert/Bleu/Violet, monochrome_tone.py's module docstring).
    assert monochrome_row.category == "monochrome_tone"
    assert monochrome_row.thumbnail_presets == (
        "neutral", "Rouge", "Sepia", "Jaune", "Vert", "Bleu", "Violet",
    )

    result = validate_workflow_config(config, addon_index)
    assert not any(
        issue.reason == "unknown_thumbnail_preset" for issue in result.issues
    )


# --- 2026-07-26 (later the same day): the real `bw` row sits between `monochrome` ---
# --- and `light`, shares the Film addon's category, and validates against the loaded addon. ---


def test_real_bw_row_positioned_between_monochrome_and_light_and_validates():
    from lumaflow.addons.loader import DiscoveryLocation, load_addons

    builtin_root = REPO_ROOT / "lumaflow" / "addons" / "builtin"
    addon_index = load_addons(DiscoveryLocation(path=builtin_root)).index
    config = load_workflow_config(REPO_ROOT / "lumaflow" / "config" / "config_workflow.json")

    identifiers = [row.identifier for row in config.rows]
    assert identifiers.index("bw") == identifiers.index("monochrome") + 1
    assert identifiers.index("light") == identifiers.index("bw") + 1

    bw_row = next(row for row in config.rows if row.identifier == "bw")
    assert bw_row.category == "film"  # same addon as "film"/"bleach_bypass"/"monochrome"
    # "Mono Moonlight"/"Daido Moriyama" retired 2026-08-04, then "Silvertone
    # 99"/"Newsprint" retired 2026-08-05 (both user requests, see film.py's
    # module docstring), replaced by four new colored-filter presets built on
    # Acros. "Kodak T-MAX"/"Kodak T-MAX 3200"/"Kodak Tri-X" added 2026-08-05
    # (later the same day), then "Agfa APX"/"Ilford Delta"/"Ilford FP4"/
    # "Ilford HP5"/"Ilford XP2" (later still). "Kodak T-MAX"/"Agfa APX"/
    # "Ilford Delta"/"Ilford HP5"/"Ilford XP2" retired (still later the same
    # day, user request), leaving "Kodak T-MAX 3200"/"Kodak Tri-X"/
    # "Ilford FP4".
    assert bw_row.thumbnail_presets == (
        "neutral", "Acros",
        "Acros + Yellow", "Acros + Red", "Acros + Green", "Acros + Blue",
        "Kodak T-MAX 3200", "Kodak Tri-X", "Ilford FP4",
    )

    result = validate_workflow_config(config, addon_index)
    assert not any(
        issue.reason == "unknown_thumbnail_preset" for issue in result.issues
    )


# --- Préférences > Workflow (2026-08-06): catalog resolution + persistence for the new ---
# --- GET/PUT /workflow-config read/write model (per-vignette enabled flag). ---


def test_catalog_thumbnail_presets_is_superset_of_configured_thumbnail_presets():
    from lumaflow.addons.loader import DiscoveryLocation, load_addons

    builtin_root = REPO_ROOT / "lumaflow" / "addons" / "builtin"
    addon_index = load_addons(DiscoveryLocation(path=builtin_root)).index
    config = load_workflow_config(REPO_ROOT / "lumaflow" / "config" / "config_workflow.json")

    for row in config.rows:
        catalog_identifiers = {identifier for identifier, _label in catalog_thumbnail_presets(row, addon_index)}
        assert set(row.thumbnail_presets) <= catalog_identifiers


def test_catalog_thumbnail_presets_resolves_via_category_when_no_addon_identifiers():
    row = WorkflowRow(category="light")
    addon_index = {
        "light_intensity": AddonDescriptor(
            identifier="light_intensity",
            category="light",
            thumbnail_presets=(
                ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),
                ThumbnailPreset(identifier="balance", label="Balance"),
            ),
        )
    }
    assert catalog_thumbnail_presets(row, addon_index) == [("neutral", "Neutral"), ("balance", "Balance")]


def test_catalog_thumbnail_presets_empty_for_unresolvable_row():
    row = WorkflowRow(category="does-not-exist")
    assert catalog_thumbnail_presets(row, addon_index={}) == []


def test_resolve_row_addons_prefers_addon_identifiers_over_category():
    row = WorkflowRow(category="film", addon_identifiers=("only_this_one",))
    only = AddonDescriptor(identifier="only_this_one", category="film")
    other = AddonDescriptor(identifier="another", category="film")
    addon_index = {"only_this_one": only, "another": other}
    assert resolve_row_addons(row, addon_index) == [only]


def test_workflow_config_save_then_load_round_trips_field_for_field(tmp_path):
    config = WorkflowConfig(
        rows=(
            WorkflowRow(
                identifier="film",
                label="Film",
                category="film",
                short_description="Rendu argentique",
                thumbnail_presets=("neutral", "Velvia"),
            ),
            WorkflowRow(identifier="light", label="Light", category="light", thumbnail_presets=("neutral",)),
        )
    )
    dest = tmp_path / "config_workflow.json"

    save_workflow_config(config, dest)
    reloaded = load_workflow_config(dest)

    assert reloaded == config


def test_workflow_config_save_persists_thumbnail_presets_disabled_entry_absent(tmp_path):
    config = WorkflowConfig(
        rows=(WorkflowRow(identifier="film", category="film", thumbnail_presets=("neutral",)),)
    )
    dest = tmp_path / "config_workflow.json"

    save_workflow_config(config, dest)

    text = dest.read_text(encoding="utf-8")
    assert '"neutral"' in text
    assert "Velvia" not in text  # a vignette absent from thumbnail_presets is simply not written


# --- Feature 043: the real `light` row's new preset list validates against ---
# --- the real, loaded Light addon (not a fixture). ---


def test_real_light_row_new_preset_list_validates_against_loaded_addon():
    from lumaflow.addons.loader import DiscoveryLocation, load_addons

    builtin_root = REPO_ROOT / "lumaflow" / "addons" / "builtin"
    addon_index = load_addons(DiscoveryLocation(path=builtin_root)).index
    config = load_workflow_config(REPO_ROOT / "lumaflow" / "config" / "config_workflow.json")

    light_row = next(row for row in config.rows if row.identifier == "light")
    assert light_row.category == "light"
    # Feature 047: RowSpec.vignette_labels (what the filmstrip actually renders) comes from the
    # CONFIG row's own thumbnail_presets list (lumaflow/api/session.py's resolve_workflow_rows),
    # not from the addon's own declared thumbnail_presets -- so this list must be kept in sync by
    # hand whenever the addon grows a new preset (same as every prior addon feature, F-041/043/046).
    # Live, user-editable content since Préférences > Workflow (2026-08-06) -- see
    # test_real_film_row_new_preset_list_validates_against_loaded_addon's comment for why this is
    # no longer a fixed literal tuple.
    assert light_row.thumbnail_presets[0] == "neutral"
    declared = {identifier for identifier, _label in catalog_thumbnail_presets(light_row, addon_index)}
    assert set(light_row.thumbnail_presets) <= declared

    result = validate_workflow_config(config, addon_index)
    assert not any(
        issue.reason == "unknown_thumbnail_preset" for issue in result.issues
    )
