# LumaFlow v1.0 (2026-08-07)
# Vérifie l'avertissement non bloquant de compatibilité de dimensions lors de l'application d'une
# recette (mêmes ratios sans avertissement, ratios différents avec identification des étapes
# Geometry/Framing concernées, recette quand même appliquée intégralement malgré l'avertissement).

"""Tests for the non-blocking dimension-compatibility warning (feature 047, US2,
FR-004) -- lumaflow/api/session.py::apply_recipe/_detect_dimension_warning.

Deliberately separate from tests/test_compatibility.py: that file covers the generic,
BLOCKING engine-level check_compatibility/apply_recipe_pipeline path (lumaflow/engine/
compatibility.py), which this feature explicitly does not reuse -- a
dimension mismatch here must never prevent the recipe from being applied.

Most cases below exercise `_detect_dimension_warning` directly against a synthetic
Recipe/ImageSession pair (data-model.md's own framing: a pure comparison, independent of
pipeline execution) -- this sidesteps an unrelated, pre-existing constraint of
apply_recipe/refresh_workflow that a Recipe's `steps` must cover every WORKFLOW_CONFIG row
to avoid an IndexError (a partial-steps recipe already crashes today regardless of this
feature; reproducing that constraint here would only test an unrelated invariant). One
end-to-end test through `apply_recipe` itself, with a full-length recipe, proves the real
wiring (outcome.dimension_warning) without hitting that unrelated constraint.
"""
from __future__ import annotations

import pathlib

import numpy
import pytest
from PIL import Image

from lumaflow.api.session import (
    WORKFLOW_CONFIG,
    DimensionWarning,
    DimensionWarningStep,
    _detect_dimension_warning,
    apply_recipe,
    create_session,
    open_image,
)
from lumaflow.engine.image_session import ImageSession, ImageSource
from lumaflow.persistence.recipe import SCHEMA_VERSION, Recipe, SourceReference, StepEntry


def _image_session(width: int, height: int) -> ImageSession:
    pixels = numpy.zeros((height, width, 3), dtype=numpy.uint8)
    source = ImageSource(identifier="test-id", path=None, name="active.png", width=width, height=height, image_format="PNG")
    return ImageSession.create(pixels=pixels, source=source)


def _recipe(width: int, height: int, step_identifiers: list[str]) -> Recipe:
    return Recipe(
        schema_version=SCHEMA_VERSION,
        source=SourceReference(filename="source.png", width=width, height=height),
        steps=[
            StepEntry(step_identifier=identifier, thumbnail_identifier="neutral", parameters={})
            for identifier in step_identifiers
        ],
    )


def test_same_ratio_produces_no_warning_even_at_different_absolute_dimensions():
    # 1600x1067 (recipe source) vs. 800x534 (active image) -- same ratio, a
    # resized copy of the same photo, not a real proportion change.
    active = _image_session(width=800, height=534)
    recipe = _recipe(1600, 1067, ["geometry", "framing"])

    assert _detect_dimension_warning(recipe, active) is None


def test_different_ratio_with_geometry_step_warns_naming_that_step():
    # Recipe authored on a landscape image, applied onto a portrait one -- a genuine ratio change.
    active = _image_session(width=1067, height=1600)
    recipe = _recipe(1600, 1067, ["geometry", "film", "vignette"])

    warning = _detect_dimension_warning(recipe, active)

    assert warning == DimensionWarning(
        incompatible=True,
        step_identifiers=["geometry"],
        steps=[DimensionWarningStep(step_identifier="geometry", status="applied_as_is")],
    )


def test_different_ratio_with_both_geometry_and_framing_steps_names_both():
    active = _image_session(width=1067, height=1600)
    recipe = _recipe(1600, 1067, ["geometry", "framing"])

    warning = _detect_dimension_warning(recipe, active)

    assert warning is not None
    assert warning.incompatible is True
    assert set(warning.step_identifiers) == {"geometry", "framing"}
    # US2 AC2 (feature 048): each affected step names its status -- always "applied_as_is" today,
    # since no addon currently re-adapts its parameters for a differing target ratio.
    assert {step.step_identifier: step.status for step in warning.steps} == {
        "geometry": "applied_as_is",
        "framing": "applied_as_is",
    }


def test_different_ratio_without_geometry_or_framing_step_produces_no_warning():
    # Color/tonal-only recipes (Film/Light/Vignette) never carry
    # dimension-dependent parameters, so no signal should fire even at a wildly different ratio.
    active = _image_session(width=1067, height=1600)
    recipe = _recipe(1600, 1067, ["film", "light", "vignette"])

    assert _detect_dimension_warning(recipe, active) is None


def test_missing_source_dimensions_produces_no_warning():
    # A recipe saved before SourceReference existed, or with unrecorded dimensions -- must not
    # crash and must not warn (nothing to compare against).
    active = _image_session(width=1067, height=1600)
    recipe = Recipe(
        schema_version=SCHEMA_VERSION,
        source=SourceReference(filename="source.png", width=None, height=None),
        steps=[StepEntry(step_identifier="geometry", thumbnail_identifier="neutral", parameters={})],
    )

    assert _detect_dimension_warning(recipe, active) is None


def test_recipe_is_still_fully_applied_regardless_of_the_warning(tmp_path: pathlib.Path):
    """FR-004's Edge Case: the warning MUST be non-blocking. End-to-end through apply_recipe
    itself, with a full-length recipe (one entry per real WORKFLOW_CONFIG row, same shape
    build_recipe always produces) at a genuinely different ratio."""
    session = create_session()
    array = numpy.zeros((1600, 1067, 3), dtype=numpy.uint8)  # portrait: height > width
    path = tmp_path / "active.png"
    Image.fromarray(array, mode="RGB").save(path, format="PNG")
    open_image(session, path)

    all_row_identifiers = [row.identifier for row in WORKFLOW_CONFIG.rows]
    assert "geometry" in all_row_identifiers  # sanity: this feature's core assumption
    recipe = _recipe(1600, 1067, all_row_identifiers)  # landscape source -- different ratio

    outcome = apply_recipe(session, recipe)

    assert outcome.dimension_warning is not None
    assert outcome.dimension_warning.incompatible is True
    assert "geometry" in outcome.dimension_warning.step_identifiers
    assert len(outcome.rows) == len(all_row_identifiers)
