# LumaFlow v1.0 (2026-08-07)
# Schema et (dé)serialisation des recettes (fichier .json de la sequence de steps) :
# validation, sauvegarde/chargement atomiques, verification de compatibilite d'addons.
from __future__ import annotations

import errno
import json
import os
import pathlib
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Collection, Optional

# Initial v1 recipe schema version, seeding SUPPORTED_SCHEMA_VERSIONS below.
SCHEMA_VERSION = "1"

# The single authoritative set of schema versions load_recipe accepts.
# Seeded from SCHEMA_VERSION so the version written and the version
# accepted can never silently diverge.
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({SCHEMA_VERSION})


@dataclass(frozen=True)
class SourceReference:
    filename: str
    width: Optional[int] = None
    height: Optional[int] = None
    checksum: Optional[str] = None


@dataclass(frozen=True)
class StepEntry:
    step_identifier: str
    thumbnail_identifier: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Recipe:
    schema_version: str
    source: SourceReference
    steps: list[StepEntry] = field(default_factory=list)


class RecipeValidationError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


class RecipeIOErrorCategory(Enum):
    PERMISSION_DENIED = "permission_denied"
    DISK_FULL = "disk_full"
    INVALID_PATH = "invalid_path"
    MISSING_FILE = "missing_file"
    UNKNOWN = "unknown"


class RecipeIOError(Exception):
    def __init__(self, category: RecipeIOErrorCategory, operation: str, detail: str = "") -> None:
        super().__init__(detail or f"{operation} failed: {category.value}")
        self.category = category
        self.operation = operation
        self.detail = detail


def recipe_to_dict(recipe: Recipe) -> dict[str, Any]:
    return {
        "schema_version": recipe.schema_version,
        "source": {
            "filename": recipe.source.filename,
            "width": recipe.source.width,
            "height": recipe.source.height,
            "checksum": recipe.source.checksum,
        },
        "steps": [
            {
                "step_identifier": step.step_identifier,
                "thumbnail_identifier": step.thumbnail_identifier,
                "parameters": dict(step.parameters),
            }
            for step in recipe.steps
        ],
    }


def validate_recipe_dict(data: dict[str, Any]) -> None:
    if "schema_version" not in data:
        raise RecipeValidationError(reason="missing_field", detail="schema_version")
    schema_version = data["schema_version"]
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise RecipeValidationError(reason="empty_schema_version", detail="schema_version")

    if "source" not in data or not isinstance(data["source"], dict):
        raise RecipeValidationError(reason="missing_field", detail="source")
    source = data["source"]
    filename = source.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise RecipeValidationError(reason="missing_field", detail="source.filename")

    if "steps" not in data or not isinstance(data["steps"], list):
        raise RecipeValidationError(reason="invalid_type", detail="steps")

    for index, step in enumerate(data["steps"]):
        if not isinstance(step, dict):
            raise RecipeValidationError(reason="invalid_type", detail=f"steps[{index}]")
        step_identifier = step.get("step_identifier")
        if not isinstance(step_identifier, str) or not step_identifier.strip():
            raise RecipeValidationError(reason="missing_field", detail=f"steps[{index}].step_identifier")
        thumbnail_identifier = step.get("thumbnail_identifier")
        if not isinstance(thumbnail_identifier, str) or not thumbnail_identifier.strip():
            raise RecipeValidationError(reason="missing_field", detail=f"steps[{index}].thumbnail_identifier")
        if "parameters" not in step or not isinstance(step["parameters"], dict):
            raise RecipeValidationError(reason="invalid_type", detail=f"steps[{index}].parameters")


def recipe_from_dict(data: dict[str, Any]) -> Recipe:
    validate_recipe_dict(data)
    source_data = data["source"]
    source = SourceReference(
        filename=source_data["filename"],
        width=source_data.get("width"),
        height=source_data.get("height"),
        checksum=source_data.get("checksum"),
    )
    steps = [
        StepEntry(
            step_identifier=step["step_identifier"],
            thumbnail_identifier=step["thumbnail_identifier"],
            parameters=dict(step["parameters"]),
        )
        for step in data["steps"]
    ]
    return Recipe(schema_version=data["schema_version"], source=source, steps=steps)


def validate_session_completeness(steps: list[StepEntry]) -> None:
    if not steps:
        raise RecipeValidationError(
            reason="empty_session", detail="The workflow has no configured steps."
        )


def save_recipe(recipe: Recipe, dest_path: pathlib.Path) -> None:
    validate_session_completeness(recipe.steps)
    dest_path = pathlib.Path(dest_path)
    try:
        payload = json.dumps(recipe_to_dict(recipe), indent=2)
        fd, tmp_str = tempfile.mkstemp(dir=dest_path.parent)
        tmp_path = pathlib.Path(tmp_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp_path, dest_path)
        except Exception:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise
    except RecipeIOError:
        raise
    except PermissionError as e:
        raise RecipeIOError(RecipeIOErrorCategory.PERMISSION_DENIED, "save", detail=str(e)) from e
    except FileNotFoundError as e:
        raise RecipeIOError(RecipeIOErrorCategory.INVALID_PATH, "save", detail=str(e)) from e
    except OSError as e:
        if e.errno == errno.ENOSPC:
            raise RecipeIOError(RecipeIOErrorCategory.DISK_FULL, "save", detail=str(e)) from e
        raise RecipeIOError(RecipeIOErrorCategory.UNKNOWN, "save", detail=str(e)) from e
    except Exception as e:
        raise RecipeIOError(RecipeIOErrorCategory.UNKNOWN, "save", detail=str(e)) from e


@dataclass(frozen=True)
class MissingAddonReport:
    missing_addon_ids: list[str]


def check_addon_availability(
    steps: list[StepEntry], available_addon_ids: Optional[Collection[str]]
) -> Optional[MissingAddonReport]:
    if available_addon_ids is None:
        return None
    missing: list[str] = []
    for step in steps:
        if step.step_identifier not in available_addon_ids and step.step_identifier not in missing:
            missing.append(step.step_identifier)
    if not missing:
        return None
    return MissingAddonReport(missing_addon_ids=missing)


def load_recipe(path: pathlib.Path) -> Recipe:
    path = pathlib.Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise RecipeIOError(RecipeIOErrorCategory.MISSING_FILE, "load", detail=str(e)) from e
    except PermissionError as e:
        raise RecipeIOError(RecipeIOErrorCategory.PERMISSION_DENIED, "load", detail=str(e)) from e
    except OSError as e:
        raise RecipeIOError(RecipeIOErrorCategory.UNKNOWN, "load", detail=str(e)) from e

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RecipeValidationError(reason="invalid_json", detail=str(e)) from e

    recipe = recipe_from_dict(data)
    check_schema_version(recipe)
    return recipe


def check_schema_version(
    recipe: Recipe, supported_versions: Collection[str] = SUPPORTED_SCHEMA_VERSIONS
) -> None:
    if recipe.schema_version not in supported_versions:
        raise RecipeValidationError(
            reason="unrecognized_schema_version",
            # Raw value, not a formatted sentence -- consistent with every other reason's `detail`
            # in this module (a field name/raw value, e.g. "source.filename"), so the API boundary
            # (lumaflow/api/app.py) can expose the actual version in a structured `details` field
            # instead of parsing it back out of a sentence.
            detail=recipe.schema_version,
        )


def example_recipe() -> Recipe:
    return Recipe(
        schema_version=SCHEMA_VERSION,
        source=SourceReference(filename="sunset.jpg", width=4032, height=3024),
        steps=[
            StepEntry("crop", "crop_neutral", {}),
            StepEntry("exposure", "exposure_plus1", {"ev": 1.0}),
        ],
    )
