# LumaFlow v1.0 (2026-08-07)
# Chargement, validation et sauvegarde de config_workflow.json (les lignes de la filmstrip
# et leurs presets), plus resolution des addons/presets associes a chaque ligne.
"""Workflow configuration (config_workflow.json v1) — structural loading and semantic addon-
reference validation. No pipeline engine, no persistence module, no addon loader import.
"""

from __future__ import annotations

import errno
import json
import os
import pathlib
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from lumaflow.addons.contract import AddonDescriptor

# Public types: WorkflowRow, WorkflowConfig, WorkflowConfigIOErrorCategory, WorkflowConfigIOError,
# WorkflowConfigValidationError, WorkflowRowIssue, WorkflowValidationResult
# Public functions: validate_workflow_config_dict, workflow_config_from_dict, load_workflow_config,
# validate_workflow_config, resolve_row_addons, catalog_thumbnail_presets, workflow_config_to_dict,
# save_workflow_config, default_workflow_config_path

DEFAULT_WORKFLOW_CONFIG_PATH = pathlib.Path(__file__).parent / "config_workflow.json"


@dataclass(frozen=True)
class WorkflowRow:
    category: Optional[str] = None
    addon_identifiers: tuple[str, ...] = ()
    thumbnail_presets: tuple[str, ...] = ()
    identifier: Optional[str] = None
    label: Optional[str] = None
    short_description: Optional[str] = None


@dataclass(frozen=True)
class WorkflowConfig:
    rows: tuple[WorkflowRow, ...] = ()


class WorkflowConfigIOErrorCategory(Enum):
    MISSING_FILE = "missing_file"
    PERMISSION_DENIED = "permission_denied"
    UNKNOWN = "unknown"


class WorkflowConfigIOError(Exception):
    def __init__(self, category: WorkflowConfigIOErrorCategory, operation: str, detail: str = "") -> None:
        super().__init__(detail or f"{operation} failed: {category.value}")
        self.category = category
        self.operation = operation
        self.detail = detail


class WorkflowConfigValidationError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class WorkflowRowIssue:
    row_index: int
    reason: str
    detail: str


@dataclass(frozen=True)
class WorkflowValidationResult:
    issues: tuple[WorkflowRowIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues


def validate_workflow_config_dict(data: dict[str, Any]) -> None:
    if "rows" not in data:
        raise WorkflowConfigValidationError(reason="missing_field", detail="rows")
    rows = data["rows"]
    if not isinstance(rows, list):
        raise WorkflowConfigValidationError(reason="invalid_type", detail="rows")

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise WorkflowConfigValidationError(reason="invalid_type", detail=f"rows[{index}]")

        category = row.get("category")
        addon_identifiers = row.get("addon_identifiers")
        if category is None and not addon_identifiers:
            raise WorkflowConfigValidationError(
                reason="missing_field", detail=f"rows[{index}].category_or_addon_identifiers"
            )

        if addon_identifiers is not None:
            if not isinstance(addon_identifiers, list) or not all(
                isinstance(item, str) for item in addon_identifiers
            ):
                raise WorkflowConfigValidationError(
                    reason="invalid_type", detail=f"rows[{index}].addon_identifiers"
                )

        thumbnail_presets = row.get("thumbnail_presets")
        if thumbnail_presets is not None:
            if not isinstance(thumbnail_presets, list) or not all(
                isinstance(item, str) for item in thumbnail_presets
            ):
                raise WorkflowConfigValidationError(
                    reason="invalid_type", detail=f"rows[{index}].thumbnail_presets"
                )

        short_description = row.get("short_description")
        if short_description is not None and not isinstance(short_description, str):
            raise WorkflowConfigValidationError(
                reason="invalid_type", detail=f"rows[{index}].short_description"
            )


def workflow_config_from_dict(data: dict[str, Any]) -> WorkflowConfig:
    validate_workflow_config_dict(data)
    rows = tuple(
        WorkflowRow(
            category=row.get("category"),
            addon_identifiers=tuple(row.get("addon_identifiers") or ()),
            thumbnail_presets=tuple(row.get("thumbnail_presets") or ()),
            identifier=row.get("identifier"),
            label=row.get("label"),
            short_description=row.get("short_description"),
        )
        for row in data["rows"]
    )
    return WorkflowConfig(rows=rows)


def load_workflow_config(path: pathlib.Path) -> WorkflowConfig:
    path = pathlib.Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise WorkflowConfigIOError(WorkflowConfigIOErrorCategory.MISSING_FILE, "load", detail=str(e)) from e
    except PermissionError as e:
        raise WorkflowConfigIOError(
            WorkflowConfigIOErrorCategory.PERMISSION_DENIED, "load", detail=str(e)
        ) from e
    except OSError as e:
        raise WorkflowConfigIOError(WorkflowConfigIOErrorCategory.UNKNOWN, "load", detail=str(e)) from e

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise WorkflowConfigValidationError(reason="invalid_json", detail=str(e)) from e

    return workflow_config_from_dict(data)


def validate_workflow_config(
    config: WorkflowConfig, addon_index: dict[str, "AddonDescriptor"]
) -> WorkflowValidationResult:
    issues: list[WorkflowRowIssue] = []

    for row_index, row in enumerate(config.rows):
        resolved_addons: list["AddonDescriptor"] = []
        reference_failed = False

        if row.addon_identifiers:
            for identifier in row.addon_identifiers:
                descriptor = addon_index.get(identifier)
                if descriptor is None:
                    issues.append(
                        WorkflowRowIssue(
                            row_index=row_index, reason="unavailable_addon", detail=identifier
                        )
                    )
                    reference_failed = True
                else:
                    resolved_addons.append(descriptor)
        elif row.category is not None:
            matching = [
                descriptor
                for descriptor in addon_index.values()
                if descriptor.category == row.category
            ]
            if not matching:
                issues.append(
                    WorkflowRowIssue(
                        row_index=row_index, reason="unavailable_category", detail=row.category
                    )
                )
                reference_failed = True
            else:
                resolved_addons.extend(matching)

        if reference_failed or not row.thumbnail_presets:
            continue

        available_presets: set[str] = set()
        for descriptor in resolved_addons:
            if descriptor.thumbnail_presets:
                available_presets.update(preset.identifier for preset in descriptor.thumbnail_presets)

        for preset_name in row.thumbnail_presets:
            if preset_name not in available_presets:
                issues.append(
                    WorkflowRowIssue(
                        row_index=row_index, reason="unknown_thumbnail_preset", detail=preset_name
                    )
                )

    return WorkflowValidationResult(issues=tuple(issues))


def resolve_row_addons(row: WorkflowRow, addon_index: dict[str, "AddonDescriptor"]) -> list["AddonDescriptor"]:
    """Resolves `row.addon_identifiers` (if present) or `row.category` (fallback) against
    `addon_index` -- same matching rule `validate_workflow_config` performs inline above, factored
    out here for the Préférences > Workflow read-model (catalog_thumbnail_presets below), which
    needs it independently of that function's own per-identifier issue-reporting shape. Silent
    (returns []) on an unresolvable reference rather than raising -- a read-only "what's available"
    call site doesn't need issue reporting."""
    if row.addon_identifiers:
        return [addon_index[identifier] for identifier in row.addon_identifiers if identifier in addon_index]
    if row.category is not None:
        return [descriptor for descriptor in addon_index.values() if descriptor.category == row.category]
    return []


def catalog_thumbnail_presets(
    row: WorkflowRow, addon_index: dict[str, "AddonDescriptor"]
) -> list[tuple[str, str]]:
    """The FULL catalog of (identifier, label) pairs `row`'s resolved addon(s) declare -- the
    superset `config_workflow.json`'s own curated, ordered `thumbnail_presets` is drawn from.
    Deduplicated by identifier, first-declaring-addon order. Used by GET /workflow-config to build
    the Préférences > Workflow tab's unified "every vignette this row could show, each flagged
    enabled/disabled" list (2026-08-06)."""
    seen: set[str] = set()
    ordered: list[tuple[str, str]] = []
    for descriptor in resolve_row_addons(row, addon_index):
        if not descriptor.thumbnail_presets:
            continue
        for preset in descriptor.thumbnail_presets:
            if preset.identifier not in seen:
                seen.add(preset.identifier)
                ordered.append((preset.identifier, preset.label))
    return ordered


def workflow_config_to_dict(config: WorkflowConfig) -> dict[str, Any]:
    return {
        "rows": [
            {
                "identifier": row.identifier,
                "label": row.label,
                "category": row.category,
                "addon_identifiers": list(row.addon_identifiers) or None,
                "short_description": row.short_description,
                "thumbnail_presets": list(row.thumbnail_presets),
            }
            for row in config.rows
        ]
    }


def save_workflow_config(config: WorkflowConfig, path: pathlib.Path) -> None:
    """Atomic write (tempfile in the same dir + os.replace) -- same durability guarantee as
    save_recipe (lumaflow/persistence/recipe.py), justified because a corrupted
    config_workflow.json degrades the WHOLE app to zero workflow rows (session.py's
    _load_workflow_config fallback), unlike a single recipe file."""
    path = pathlib.Path(path)
    try:
        payload = json.dumps(workflow_config_to_dict(config), indent=2)
        fd, tmp_str = tempfile.mkstemp(dir=path.parent)
        tmp_path = pathlib.Path(tmp_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp_path, path)
        except Exception:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise
    except WorkflowConfigIOError:
        raise
    except PermissionError as e:
        raise WorkflowConfigIOError(WorkflowConfigIOErrorCategory.PERMISSION_DENIED, "save", detail=str(e)) from e
    except FileNotFoundError as e:
        raise WorkflowConfigIOError(WorkflowConfigIOErrorCategory.UNKNOWN, "save", detail=str(e)) from e
    except OSError as e:
        if e.errno == errno.ENOSPC:
            raise WorkflowConfigIOError(WorkflowConfigIOErrorCategory.UNKNOWN, "save", detail=str(e)) from e
        raise WorkflowConfigIOError(WorkflowConfigIOErrorCategory.UNKNOWN, "save", detail=str(e)) from e
    except Exception as e:
        raise WorkflowConfigIOError(WorkflowConfigIOErrorCategory.UNKNOWN, "save", detail=str(e)) from e


def default_workflow_config_path() -> pathlib.Path:
    """Wrapper around DEFAULT_WORKFLOW_CONFIG_PATH so tests can monkeypatch the write/dialog
    target the exact same way tests already isolate default_preferences_path
    (tests/test_api_session_wiring.py's isolated_preferences_path fixture) -- app.py's
    workflow-config endpoints must call this function, never reference DEFAULT_WORKFLOW_CONFIG_PATH
    as a bare imported name, or a test monkeypatch on this function would silently not apply."""
    return DEFAULT_WORKFLOW_CONFIG_PATH
