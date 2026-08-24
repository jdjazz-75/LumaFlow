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

# Current recipe schema version. 1.1 dropped the `source` file-reference block (a preset is no
# longer tied to the image it was authored on) and stopped writing Geometry/Framing step entries
# (image-specific corrections almost never portable to a different photo, see CLAUDE.md).
SCHEMA_VERSION = "1.1"

# Every schema version load_recipe still accepts, past and present -- "1" (the original shape,
# with `source` and every row including Geometry/Framing) must keep loading silently, with its
# now-obsolete fields simply ignored rather than erroring or warning (recipe_from_dict below).
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({SCHEMA_VERSION, "1"})


@dataclass(frozen=True)
class StepEntry:
    step_identifier: str
    thumbnail_identifier: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Recipe:
    schema_version: str
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

    # `source` is no longer part of the schema (1.1) -- a v1 file that still carries it is
    # simply left unread below, never validated or rejected.

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


# Row identifiers a recipe never carries, regardless of the file's own schema version --
# image-specific corrections (geometry.py::_resolve_corners/_resolve_angle,
# framing.py::_resolve_box) that almost never apply to a different photo. build_recipe (session.py)
# never emits them; a v1 file that still has one (authored before this exclusion existed) simply
# has that entry dropped here, silently, same as a v1.1 file that never mentioned it.
EXCLUDED_STEP_IDENTIFIERS: frozenset[str] = frozenset({"geometry", "framing"})


def recipe_from_dict(data: dict[str, Any]) -> Recipe:
    validate_recipe_dict(data)
    steps = [
        StepEntry(
            step_identifier=step["step_identifier"],
            thumbnail_identifier=step["thumbnail_identifier"],
            parameters=dict(step["parameters"]),
        )
        for step in data["steps"]
        if step["step_identifier"] not in EXCLUDED_STEP_IDENTIFIERS
    ]
    return Recipe(schema_version=data["schema_version"], steps=steps)


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
            # in this module (a field name/raw value, e.g. "schema_version"), so the API boundary
            # (lumaflow/api/app.py) can expose the actual version in a structured `details` field
            # instead of parsing it back out of a sentence.
            detail=recipe.schema_version,
        )


def example_recipe() -> Recipe:
    return Recipe(
        schema_version=SCHEMA_VERSION,
        steps=[
            StepEntry("crop", "crop_neutral", {}),
            StepEntry("exposure", "exposure_plus1", {"ev": 1.0}),
        ],
    )
