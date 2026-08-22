# LumaFlow v1.0 (2026-08-07)
# Teste le loader d'addons (load_addons/DiscoveryLocation) : découverte du répertoire builtin réel,
# chargement d'addons valides, détection de doublons d'identifiant (2 et 3 voies), et gestion
# d'addons invalides/en erreur d'import sans bloquer les autres (sauf mode fail_fast).

import pathlib

from lumaflow.addons.loader import AddonLoadIssueKind, DiscoveryLocation, load_addons

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURES_ROOT = REPO_ROOT / "tests" / "fixtures" / "addons"
BUILTIN_ADDONS_ROOT = REPO_ROOT / "lumaflow" / "addons" / "builtin"


# --- Real discovery directory (feature 040) ---


def test_real_builtin_directory_resolves_geometry_addon():
    report = load_addons(DiscoveryLocation(path=BUILTIN_ADDONS_ROOT))
    assert report.succeeded
    assert "geometry_correction" in report.index
    descriptor = report.index["geometry_correction"]
    assert descriptor.category == "geometry"
    assert descriptor.processing_function is not None


def test_real_builtin_directory_resolves_both_geometry_and_framing_addons():
    report = load_addons(DiscoveryLocation(path=BUILTIN_ADDONS_ROOT))
    assert report.succeeded
    assert set(report.index) >= {"geometry_correction", "framing_crop"}
    descriptor = report.index["framing_crop"]
    assert descriptor.category == "framing"
    assert descriptor.processing_function is not None


def test_real_builtin_directory_resolves_geometry_framing_and_film_addons():
    report = load_addons(DiscoveryLocation(path=BUILTIN_ADDONS_ROOT))
    assert report.succeeded
    assert set(report.index) >= {"geometry_correction", "framing_crop", "film_look"}
    descriptor = report.index["film_look"]
    assert descriptor.category == "film"
    assert descriptor.processing_function is not None


def test_real_builtin_directory_resolves_color_splash_addon():
    report = load_addons(DiscoveryLocation(path=BUILTIN_ADDONS_ROOT))
    assert report.succeeded
    assert "color_splash" in report.index
    descriptor = report.index["color_splash"]
    assert descriptor.category == "color_splash"
    assert descriptor.processing_function is not None
    assert len(descriptor.thumbnail_presets) == 7
    assert len(descriptor.zoom_parameters) == 11
    assert descriptor.resolve_zoom_values is not None


def test_real_builtin_directory_resolves_light_addon_alongside_the_others():
    report = load_addons(DiscoveryLocation(path=BUILTIN_ADDONS_ROOT))
    assert report.succeeded
    assert set(report.index) >= {
        "geometry_correction", "framing_crop", "film_look", "color_splash", "light_adjustments",
    }
    descriptor = report.index["light_adjustments"]
    assert descriptor.category == "light"
    assert descriptor.processing_function is not None
    assert len(descriptor.thumbnail_presets) == 6
    assert len(descriptor.zoom_parameters) == 137  # intensity + 31 base-grade + 38 region-delta + 67 mask fields (feature 047)
    assert descriptor.resolve_zoom_values is not None


def test_real_builtin_directory_resolves_vignetting_addon_alongside_the_others():
    report = load_addons(DiscoveryLocation(path=BUILTIN_ADDONS_ROOT))
    assert report.succeeded
    assert set(report.index) >= {
        "geometry_correction", "framing_crop", "film_look", "color_splash", "light_adjustments",
        "vignetting",
    }
    descriptor = report.index["vignetting"]
    assert descriptor.category == "vignette"
    assert descriptor.processing_function is not None
    assert len(descriptor.thumbnail_presets) == 3
    assert len(descriptor.zoom_parameters) == 10  # intensity + progressivity + 8 shape/feather geometry fields
    assert descriptor.resolve_zoom_values is not None


# --- User Story 1: Installed Addons Are Discovered, Validated, and Made Available by Identifier ---


def test_two_valid_addons_loaded_and_retrievable_by_identifier():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "valid_pair"))
    assert report.succeeded
    assert set(report.index) == {"intensity_demo", "grid_overlay_demo"}


def test_loaded_declaration_matches_discovered_data_exactly():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "valid_pair"))
    descriptor = report.index["intensity_demo"]
    assert descriptor.label == "Intensity Demo"
    assert descriptor.category == "light"
    assert descriptor.thumbnail_presets is not None
    assert descriptor.thumbnail_presets[0].identifier == "neutral"
    assert descriptor.processing_function is not None
    assert len(descriptor.zoom_parameters) == 1


def test_empty_and_missing_discovery_location_yield_empty_index_no_error(tmp_path):
    empty_report = load_addons(DiscoveryLocation(path=tmp_path))
    assert empty_report.succeeded
    assert empty_report.index == {}
    assert empty_report.issues == ()

    missing_report = load_addons(DiscoveryLocation(path=REPO_ROOT / "does" / "not" / "exist"))
    assert missing_report.succeeded
    assert missing_report.index == {}
    assert missing_report.issues == ()


def test_non_addon_file_is_silently_ignored():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "non_addon_file"))
    assert report.succeeded
    assert report.index == {}
    assert report.issues == ()


# --- User Story 2: Duplicate Addon Identifiers Are Detected and Reported Clearly ---


def test_two_way_duplicate_produces_one_issue_neither_indexed():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "duplicate_pair"))
    duplicate_issues = [
        issue for issue in report.issues if issue.kind is AddonLoadIssueKind.DUPLICATE_IDENTIFIER
    ]
    assert len(duplicate_issues) == 1
    assert duplicate_issues[0].identifier == "shared_id"
    assert "shared_id" not in report.index


def test_duplicate_issue_kind_distinguishable_from_invalid_addon():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "duplicate_pair"))
    duplicate_issues = [
        issue for issue in report.issues if issue.identifier == "shared_id"
    ]
    assert len(duplicate_issues) == 1
    assert duplicate_issues[0].kind is AddonLoadIssueKind.DUPLICATE_IDENTIFIER
    assert duplicate_issues[0].kind is not AddonLoadIssueKind.INVALID_ADDON


def test_three_way_duplicate_reflects_true_count_not_first_pair():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "triple_duplicate"))
    duplicate_issues = [
        issue for issue in report.issues if issue.kind is AddonLoadIssueKind.DUPLICATE_IDENTIFIER
    ]
    assert len(duplicate_issues) == 1
    assert duplicate_issues[0].identifier == "triple_id"
    assert "3" in duplicate_issues[0].detail


def test_same_physical_module_discovered_twice_collides_identically():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "duplicate_pair"))
    duplicate_issues = [
        issue for issue in report.issues if issue.kind is AddonLoadIssueKind.DUPLICATE_IDENTIFIER
    ]
    assert len(duplicate_issues) == 1
    assert duplicate_issues[0].identifier == "shared_id"
    assert "shared_id" not in report.index


# --- User Story 3: An Invalid Addon Does Not Prevent Other Valid Addons From Loading ---


def test_invalid_addon_does_not_block_valid_addon_default_config():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "mixed_valid_invalid"))
    assert report.succeeded
    assert "valid_demo" in report.index


def test_invalid_addon_issue_names_specific_problem_not_generic():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "mixed_valid_invalid"))
    invalid_issues = [
        issue for issue in report.issues if issue.kind is AddonLoadIssueKind.INVALID_ADDON
    ]
    assert len(invalid_issues) == 1
    assert invalid_issues[0].identifier == "invalid_demo"
    assert invalid_issues[0].detail
    assert "label" in invalid_issues[0].detail


def test_fail_fast_aborts_whole_load_instead_of_skip_and_continue():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "mixed_valid_invalid"), fail_fast=True)
    assert report.aborted is True
    assert not report.succeeded
    assert any(issue.kind is AddonLoadIssueKind.LOAD_ABORTED for issue in report.issues)


def test_import_time_exception_is_caught_not_propagated():
    report = load_addons(DiscoveryLocation(path=FIXTURES_ROOT / "import_error"))
    assert report.succeeded
    invalid_issues = [
        issue for issue in report.issues if issue.kind is AddonLoadIssueKind.INVALID_ADDON
    ]
    assert len(invalid_issues) == 1
    assert invalid_issues[0].identifier is None
