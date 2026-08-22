# LumaFlow v1.0 (2026-08-07)
# Teste le contrat de validation des addons (validate_addon/AddonDescriptor) : acceptation d'un
# descripteur complet, détection des champs manquants/vides, et résolution des paramètres de preset.

from lumaflow.addons.contract import (
    AddonDescriptor,
    ThumbnailPreset,
    ZoomParameterDeclaration,
    validate_addon,
)


def _neutral_intensity(image, params):
    return image


def _fully_declared_descriptor() -> AddonDescriptor:
    return AddonDescriptor(
        identifier="intensity",
        label="Intensity",
        category="light",
        thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),),
        processing_function=_neutral_intensity,
        zoom_parameters=(
            ZoomParameterDeclaration(
                identifier="amount",
                label="Amount",
                kind="numeric_slider",
                constraints={"minimum": 0, "maximum": 100, "step": 1},
            ),
        ),
    )


# --- User Story 1: A Conforming Addon Is Recognized by the Contract ---


def test_fully_declared_descriptor_is_accepted():
    report = validate_addon(_fully_declared_descriptor())
    assert report.valid is True
    assert report.issues == ()


def test_processing_function_returns_image_without_requiring_mutation():
    descriptor = _fully_declared_descriptor()
    image = object()
    result = descriptor.processing_function(image, {})
    assert result is image


def test_two_distinct_addons_validated_independently():
    complete = _fully_declared_descriptor()
    incomplete = AddonDescriptor(identifier="broken")

    complete_report = validate_addon(complete)
    validate_addon(incomplete)
    complete_report_again = validate_addon(complete)

    assert complete_report.valid is True
    assert complete_report_again.valid is True
    assert complete_report_again.issues == ()


# --- User Story 2: An Incomplete Addon Is Rejected With a Clear, Actionable Reason ---


def test_missing_identifier_is_flagged():
    descriptor = AddonDescriptor(
        label="Intensity",
        category="light",
        thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),),
        processing_function=_neutral_intensity,
        zoom_parameters=(),
    )
    report = validate_addon(descriptor)
    assert any(issue.field == "identifier" and issue.reason == "missing" for issue in report.issues)


def test_multiple_missing_fields_all_enumerated():
    report = validate_addon(AddonDescriptor(identifier="broken"))
    missing_fields = {issue.field for issue in report.issues if issue.reason == "missing"}
    assert missing_fields == {
        "label",
        "category",
        "thumbnail_presets",
        "processing_function",
        "zoom_parameters",
    }


def test_blank_identifier_produces_empty_not_missing():
    report = validate_addon(AddonDescriptor(identifier="   "))
    identifier_issue = next(issue for issue in report.issues if issue.field == "identifier")
    assert identifier_issue.reason == "empty"


def test_validate_addon_never_raises_for_invalid_descriptor():
    report = validate_addon(AddonDescriptor())
    assert report.valid is False
    assert len(report.issues) > 0


# --- User Story 3: Addon Interface Parameters Are Declared, Not Hard-Coded as Widgets ---


def test_zoom_parameters_are_plain_data_not_widgets():
    parameter = ZoomParameterDeclaration(
        identifier="amount",
        label="Amount",
        kind="numeric_slider",
        constraints={"minimum": 0, "maximum": 100},
        zoom_only=True,
    )
    assert isinstance(parameter.identifier, str)
    assert isinstance(parameter.label, str)
    assert isinstance(parameter.kind, str)
    assert isinstance(parameter.constraints, dict)
    assert isinstance(parameter.zoom_only, bool)


def test_thumbnail_presets_are_plain_data():
    preset = ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True)
    assert isinstance(preset.identifier, str)
    assert isinstance(preset.label, str)
    assert isinstance(preset.neutral, bool)


def test_dummy_noop_processing_function_satisfies_contract():
    descriptor = AddonDescriptor(
        identifier="intensity",
        label="Intensity",
        category="light",
        thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),),
        processing_function=lambda image, params: image,
        zoom_parameters=(),
    )
    report = validate_addon(descriptor)
    assert not any(issue.field == "processing_function" for issue in report.issues)


# --- Feature 041: ThumbnailPreset.preset_parameters (additive, backward compatible) ---


def test_preset_parameters_defaults_to_none():
    preset = ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True)
    assert preset.preset_parameters is None


def test_preset_without_preset_parameters_still_validates_unchanged():
    descriptor = _fully_declared_descriptor()
    report = validate_addon(descriptor)
    assert report.valid is True
    assert report.issues == ()


def test_preset_parameters_accepts_a_declared_dict():
    preset = ThumbnailPreset(identifier="16:9", label="16:9", preset_parameters={"aspect_ratio": 16 / 9})
    assert preset.preset_parameters == {"aspect_ratio": 16 / 9}


# --- Feature 042: _resolve_preset_parameter_values generalized to pass unrecognized keys ---
# --- through verbatim instead of dropping them. ---
#
# The aspect_ratio -> crop_x/crop_y/crop_width/crop_height expansion these tests used to check
# was specific to the deleted Qt app.py's copy of this function (Framing was a real, preset-driven
# filmstrip row there); the web API's lumaflow.api.session copy is a plain pass-through -- Framing
# is a hidden/auxiliary row on the web UI (its own CropToolStage endpoints handle cropping
# directly, never through a preset selection), so that expansion was never ported there. Removed
# along with lumaflow/app.py (2026-07-29) rather than silently asserted against dead code.


def test_resolve_preset_parameter_values_passes_arbitrary_keys_through_unchanged():
    from lumaflow.api.session import _resolve_preset_parameter_values

    preset = ThumbnailPreset(
        identifier="Velvia", label="Velvia", preset_parameters={"look": "velvia", "intensity": 1.0}
    )
    assert _resolve_preset_parameter_values(preset, (100, 200, 3)) == {"look": "velvia", "intensity": 1.0}


def test_resolve_preset_parameter_values_none_still_resolves_to_empty_dict():
    from lumaflow.api.session import _resolve_preset_parameter_values

    preset = ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True)
    assert _resolve_preset_parameter_values(preset, (100, 200, 3)) == {}
