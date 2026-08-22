# LumaFlow v1.0 (2026-08-07)
# Teste la validation des descriptions de paramètres et de surcouches graphiques (parameter.py) :
# ParameterDescription (curseur numérique, bornes, valeur par défaut) et OverlayDescription, ainsi
# que leur conversion en déclarations de zoom acceptées par le contrat d'addon.

import pytest

from lumaflow.addons.contract import AddonDescriptor, ThumbnailPreset, validate_addon
from lumaflow.addons.parameters import (
    NumericSliderConstraints,
    OverlayDescription,
    ParameterDescription,
    overlay_to_zoom_declaration,
    parameter_to_zoom_declaration,
    validate_overlay_description,
    validate_parameter_description,
)


def _intensity_parameter() -> ParameterDescription:
    return ParameterDescription(
        identifier="intensity",
        label="Intensity",
        kind="numeric_slider",
        default=50,
        constraints=NumericSliderConstraints(minimum=0, maximum=100, step=1),
    )


# --- User Story 1: Describe a Numeric Fine-Tuning Control Without Any UI Code ---


def test_full_0_100_intensity_parameter_is_accepted():
    report = validate_parameter_description(_intensity_parameter())
    assert report.valid is True
    assert report.issues == ()


def test_accepted_parameter_has_no_widget_reference():
    description = _intensity_parameter()
    assert isinstance(description.identifier, str)
    assert isinstance(description.label, str)
    assert isinstance(description.kind, str)
    assert isinstance(description.default, (int, float))
    assert isinstance(description.constraints, NumericSliderConstraints)
    assert isinstance(description.zoom_only, bool)


def test_accepted_parameter_default_within_range():
    description = _intensity_parameter()
    assert description.constraints.minimum <= description.default <= description.constraints.maximum


# --- User Story 2: Invalid Parameter Descriptions Are Rejected at Addon Load Time ---


def test_min_greater_than_max_refused_with_distinct_reason():
    broken = ParameterDescription(
        identifier="broken",
        label="Broken",
        kind="numeric_slider",
        default=50,
        constraints=NumericSliderConstraints(minimum=100, maximum=0, step=1),
    )
    report = validate_parameter_description(broken)
    assert any(issue.reason == "min_greater_than_max" for issue in report.issues)


@pytest.mark.parametrize("omitted_field", ["identifier", "label", "kind", "default", "constraints"])
def test_missing_required_attribute_named_for_each_field(omitted_field):
    fields = {
        "identifier": "intensity",
        "label": "Intensity",
        "kind": "numeric_slider",
        "default": 50,
        "constraints": NumericSliderConstraints(minimum=0, maximum=100, step=1),
    }
    fields[omitted_field] = None
    description = ParameterDescription(**fields)

    report = validate_parameter_description(description)
    matching = [issue for issue in report.issues if issue.field == omitted_field]
    assert len(matching) == 1
    assert matching[0].reason == "missing"


def test_default_out_of_range_refused_distinctly_from_min_max():
    out_of_range = ParameterDescription(
        identifier="oor",
        label="Out of Range",
        kind="numeric_slider",
        default=500,
        constraints=NumericSliderConstraints(minimum=0, maximum=100, step=1),
    )
    report = validate_parameter_description(out_of_range)
    reasons = {issue.reason for issue in report.issues}
    assert reasons == {"default_out_of_range"}


def test_validate_parameter_description_never_raises_for_invalid_input():
    report = validate_parameter_description(ParameterDescription())
    assert report.valid is False
    assert len(report.issues) > 0


# --- User Story 3: Describe an Overlay and a Zoom-Only Parameter Without Referencing a Graphical Class ---


def test_grid_overlay_description_is_accepted_with_no_issues():
    grid = OverlayDescription(
        kind="grid",
        label="Rule-of-thirds grid",
        default_active=False,
        graphical_parameters={"line_spacing": 3, "color": "#E3A75E"},
    )
    assert validate_overlay_description(grid).valid is True


def test_overlay_graphical_parameters_are_plain_data_no_graphical_class_reference():
    grid = OverlayDescription(
        kind="grid",
        label="Rule-of-thirds grid",
        default_active=False,
        graphical_parameters={"line_spacing": 3, "color": "#E3A75E"},
    )
    for value in grid.graphical_parameters.values():
        assert isinstance(value, (int, float, str, bool))


def test_zoom_only_flag_present_as_plain_data_on_parameter_only():
    description = ParameterDescription(
        identifier="intensity",
        label="Intensity",
        kind="numeric_slider",
        default=50,
        constraints=NumericSliderConstraints(minimum=0, maximum=100, step=1),
        zoom_only=True,
    )
    assert description.zoom_only is True

    overlay_fields = {f.name for f in OverlayDescription.__dataclass_fields__.values()}
    assert "zoom_only" not in overlay_fields


def test_overlay_missing_default_active_refused_by_name():
    grid = OverlayDescription(kind="grid", label="Grid")
    report = validate_overlay_description(grid)
    assert any(
        issue.field == "default_active" and issue.reason == "missing" for issue in report.issues
    )


# --- Phase 6: Polish & Cross-Cutting Concerns ---


def test_parameter_and_overlay_conversion_functions_produce_zoom_declarations_accepted_by_f019_validate_addon():
    intensity = _intensity_parameter()
    zoom_param = parameter_to_zoom_declaration(intensity)

    grid = OverlayDescription(
        kind="grid",
        label="Rule-of-thirds grid",
        default_active=False,
        graphical_parameters={"line_spacing": 3, "color": "#E3A75E"},
    )
    zoom_overlay = overlay_to_zoom_declaration("grid_overlay", grid)

    descriptor = AddonDescriptor(
        identifier="light",
        label="Light",
        category="light",
        thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),),
        processing_function=lambda image, params: image,
        zoom_parameters=(zoom_param, zoom_overlay),
    )

    report = validate_addon(descriptor)
    assert report.valid is True
