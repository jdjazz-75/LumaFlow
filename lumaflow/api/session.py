# LumaFlow v1.0 (2026-08-07)
# Etat de session par requete : pipeline, selections de vignettes, rendu incremental
# (Zoom avant/apres, recettes) et configuration de workflow partagee entre sessions.
"""Per-session workflow/pipeline state -- the Phase 1 seam of the
FastAPI/React migration plan (2026-07-20).

Originally adapted from the now-removed PySide6 desktop app's (``lumaflow/app.py``, deleted
2026-07-29 once the web UI became the sole IHM) module-level globals (``_active_session``,
``_active_pipeline``, ``_active_thumbnail_selections``, ``_active_step_index``,
``_active_vignette_states``, ``_vignette_state_cache``) and its
``_compute_applied_pipeline``/``_compute_vignette_states``/``_on_vignette_selected`` functions:
same logic, but every function here takes an explicit ``Session`` instead of reading
process-global state, so more than one session can exist side by side behind a REST API.

``RowSpec``/``VignetteState``/``VignetteStatus``/``NEUTRAL_PRESET_IDENTIFIER``/
``visible_row_indices`` live in ``lumaflow.api.filmstrip_types`` -- plain frozen
dataclasses/an enum, no Qt dependency (relocated there from the deleted Qt UI's own
``filmstrip_view.py``, which used to pull PySide6 in as a side effect of importing them).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy
from PIL import Image

from lumaflow.addons.contract import AddonDescriptor, ThumbnailPreset, ZoomParameterDeclaration
from lumaflow.addons.loader import DiscoveryLocation, load_addons
from lumaflow.config.workflow import (
    DEFAULT_WORKFLOW_CONFIG_PATH,
    WorkflowConfig,
    WorkflowConfigIOError,
    WorkflowConfigValidationError,
    load_workflow_config,
)
from lumaflow.engine.compatibility import apply_recipe_pipeline
from lumaflow.engine.errors import StepError
from lumaflow.engine.image_io import load_image
from lumaflow.engine.image_session import ImageSession
from lumaflow.engine.pipeline import Pipeline, PipelineStep, StepParameters
from lumaflow.persistence.preferences import default_preferences_path, load_preferences
from lumaflow.persistence.recipe import SCHEMA_VERSION as RECIPE_SCHEMA_VERSION
from lumaflow.persistence.recipe import (
    MissingAddonReport,
    Recipe,
    SourceReference,
    StepEntry,
    check_addon_availability,
    load_recipe,
    save_recipe,
    validate_session_completeness,
)
from lumaflow.api.filmstrip_types import (
    NEUTRAL_PRESET_IDENTIFIER,
    RowSpec,
    VignetteState,
    VignetteStatus,
    visible_row_indices,
)

RenderVignette = Callable[[str, numpy.ndarray, dict[str, Any]], numpy.ndarray]

# ---------------------------------------------------------------------------
# Process-wide static resources -- loaded once, shared by every session,
# mirroring app.py's own "Decision 5" convention (config_workflow.json and
# the builtin addon directory are static, committed content for the lifetime
# of a process, not per-session data).
# ---------------------------------------------------------------------------

BUILTIN_ADDONS_PATH: Path = Path(__file__).resolve().parent.parent / "addons" / "builtin"


def _load_workflow_config(path: Path = DEFAULT_WORKFLOW_CONFIG_PATH) -> WorkflowConfig:
    try:
        return load_workflow_config(path)
    except (WorkflowConfigIOError, WorkflowConfigValidationError):
        return WorkflowConfig(rows=())


def _resolve_initial_workflow_config() -> tuple[WorkflowConfig, Path]:
    """Which file WORKFLOW_CONFIG loads from at process start, and the config it produced.

    2026-08-06 follow-up bug fix: PUT /workflow-config now saves to whichever file is currently
    ACTIVE (see put_workflow_config_endpoint's docstring) instead of unconditionally to the
    canonical config_workflow.json -- so at the NEXT launch, the canonical file may well be stale
    while preferences.json's remembered workflow_config_source_path holds the real, current data.
    Loading must follow that same remembered path, or "chargé directement au prochain lancement"
    (the whole point of persisting it) would silently not hold.

    Falls back to the canonical default if the remembered path is unset, or if loading it fails
    for any reason (moved/deleted/corrupted since it was last opened) -- a stale pointer degrading
    the WHOLE app to zero rows would be far worse than silently falling back to "as if this were a
    fresh install"."""
    try:
        remembered = load_preferences(default_preferences_path()).workflow_config_source_path
    except Exception:
        remembered = None
    if remembered:
        candidate = Path(remembered)
        try:
            return load_workflow_config(candidate), candidate
        except (WorkflowConfigIOError, WorkflowConfigValidationError):
            pass
    return _load_workflow_config(DEFAULT_WORKFLOW_CONFIG_PATH), DEFAULT_WORKFLOW_CONFIG_PATH


WORKFLOW_CONFIG, _INITIAL_WORKFLOW_CONFIG_PATH = _resolve_initial_workflow_config()
# Display/save-target pointer for Préférences > Workflow -- separate from WORKFLOW_CONFIG itself
# since a file's own path has no natural home inside the row data it describes. Only
# reload_workflow_config() (i.e. a validated PUT) moves this IN-PROCESS copy. The durable copy
# that survives a real app restart lives in preferences.json's own workflow_config_source_path
# field instead (written by PUT /preferences, which the Préférences dialog's Valider always fires
# alongside PUT /workflow-config) -- deliberately NOT written here too, to avoid two independent
# endpoints racing to write the same file.
WORKFLOW_CONFIG_SOURCE_PATH: str = str(_INITIAL_WORKFLOW_CONFIG_PATH)
ADDON_INDEX: dict[str, AddonDescriptor] = load_addons(DiscoveryLocation(BUILTIN_ADDONS_PATH)).index


def resolve_workflow_rows(config: WorkflowConfig) -> list[RowSpec]:
    """Mirrors app.py's own resolve_workflow_rows -- a load/validation
    failure degrades to zero rows, never raises.

    `config` has no default (2026-08-06, Préférences > Workflow) -- a mutable default bound to the
    ORIGINAL WORKFLOW_CONFIG object at function-definition time would silently ignore any later
    reload_workflow_config() call, since Python evaluates a default argument once."""
    return [
        RowSpec(
            label=row.label or row.identifier or f"Step {i + 1}",
            vignette_labels=tuple(row.thumbnail_presets),
            short_description=row.short_description or "",
        )
        for i, row in enumerate(config.rows)
    ]


WORKFLOW_ROWS: list[RowSpec] = resolve_workflow_rows(WORKFLOW_CONFIG)


def reload_workflow_config(new_config: WorkflowConfig, source_path: str | None = None) -> None:
    """Reassigns the module-level WORKFLOW_CONFIG/WORKFLOW_ROWS globals in-process, no restart --
    called by app.py's PUT /workflow-config after a validated save (Préférences > Workflow,
    2026-08-06). Encapsulated here (rather than an external caller poking session.WORKFLOW_CONFIG
    directly) so the two globals can never be set out of sync. Safe to call while sessions are
    open: row identifiers/order are enforced (by app.py's endpoint, before this is called) to stay
    identical to what they were when every open session's pipeline was built -- only each row's
    `thumbnail_presets` may differ -- so refresh_workflow's positional zip against WORKFLOW_ROWS
    stays valid for every already-open session, with no per-session snapshot needed.

    `source_path` (2026-08-06 bug fix) also updates WORKFLOW_CONFIG_SOURCE_PATH when given -- the
    caller passes the submitted draft's own source_path (the file the user last opened, or the
    canonical default if they never used "Ouvrir…" this session) so it survives a Préférences
    dialog close/reopen instead of resetting to the default path on every GET."""
    global WORKFLOW_CONFIG, WORKFLOW_ROWS, WORKFLOW_CONFIG_SOURCE_PATH
    WORKFLOW_CONFIG = new_config
    WORKFLOW_ROWS = resolve_workflow_rows(new_config)
    if source_path is not None:
        WORKFLOW_CONFIG_SOURCE_PATH = source_path


def _is_vignette_enabled(row, descriptor, identifier: str) -> bool:
    """Whether `identifier` is currently a selectable vignette for `row` -- "neutral" is always
    implicitly enabled (RowSpec.__post_init__ guarantees it leads vignette_labels regardless of
    what thumbnail_presets says). Everything else must be present in `row.thumbnail_presets`
    (Préférences > Workflow's enabled set, 2026-08-06) -- BUT ONLY if it's also a real preset the
    addon declares at all (`descriptor.thumbnail_presets`). A handful of rows (Geometry/Framing)
    repurpose the same `identifier` field for a free-form value that was never a catalog preset to
    begin with (e.g. Framing's crop-ratio tag "16:9", set directly via select_vignette/a saved
    recipe, never listed in config_workflow.json nor declared by framing.py's AddonDescriptor) --
    those are outside this feature's scope entirely and must never be overridden. Used by both
    live clicks (select_vignette) and recipe application (apply_recipe) to keep rendering coherent
    with whatever vignettes are currently enabled -- a disabled one must never be applied."""
    if identifier == NEUTRAL_PRESET_IDENTIFIER:
        return True
    if row is None:
        return True
    catalog_identifiers = (
        {preset.identifier for preset in descriptor.thumbnail_presets}
        if descriptor is not None and descriptor.thumbnail_presets
        else set()
    )
    if identifier not in catalog_identifiers:
        return True
    return identifier in row.thumbnail_presets


def _resolve_addon_for_row(row, addon_index: dict[str, AddonDescriptor]) -> AddonDescriptor | None:
    for descriptor in addon_index.values():
        if descriptor.category is not None and descriptor.category == row.category:
            return descriptor
    return None


# Geometry/Framing no longer have their own filmstrip row in the WEB frontend (2026-07-24) -- only
# reachable via the "Réglages manuels" > Geometry/Cadrage toggle inside Film's/Color Splash's own
# Zoom (auxiliary_zoom_* below). They remain real, indexed pipeline steps -- this constant/helper
# affect ONLY which rows _compute_vignette_states lazily renders thumbnails for on the web API,
# mirroring web/src/lib/filmstrip.ts's HIDDEN_ROW_LABELS/visibleRowRealIndices exactly. Never touch
# `visible_row_indices` itself (lumaflow.api.filmstrip_types) -- filter before calling it, map back
# after.
_HIDDEN_ROW_LABELS = {"Geometry", "Framing"}


def _visible_row_real_indices(total: int) -> list[int]:
    return [i for i in range(total) if WORKFLOW_CONFIG.rows[i].label not in _HIDDEN_ROW_LABELS]


def _row_index_by_identifier(row_identifier: str) -> int | None:
    """Resolves a `config_workflow.json` row identifier (e.g. "geometry", "framing") to its
    pipeline step index, independently of whichever row currently has a Zoom session open -- used
    by the "auxiliary" zoom endpoints (Geometry/Cadrage integrated into Film/Color Splash's own
    Zoom, feature: cross-row corrections)."""
    for index, row in enumerate(WORKFLOW_CONFIG.rows):
        if row.identifier == row_identifier:
            return index
    return None


def row_has_zoom(row_index: int) -> bool:
    """Whether the row at `row_index` has any manual (Zoom) parameter to show -- the exact same
    addon resolution the /zoom/* endpoints use, exposed publicly so app.py's row listing (feature
    046) can derive `has_zoom` without duplicating or diverging from real Zoom availability. False
    for an out-of-range index or a row with no addon / no declared zoom parameters."""
    if not (0 <= row_index < len(WORKFLOW_CONFIG.rows)):
        return False
    row = WORKFLOW_CONFIG.rows[row_index]
    descriptor = _resolve_addon_for_row(row, ADDON_INDEX)
    return descriptor is not None and bool(descriptor.zoom_parameters)


def _resolve_preset_parameter_values(
    preset: ThumbnailPreset, image_shape: tuple[int, int, int]
) -> dict[str, Any]:
    if preset.preset_parameters is None:
        return {}
    return dict(preset.preset_parameters)


def _default_render_vignette(identifier: str, image: numpy.ndarray, parameters: dict[str, Any]) -> numpy.ndarray:
    return image


def _render_vignette(identifier: str, image: numpy.ndarray, parameters: dict[str, Any]) -> numpy.ndarray:
    for row in WORKFLOW_CONFIG.rows:
        descriptor = _resolve_addon_for_row(row, ADDON_INDEX)
        if descriptor is None or descriptor.processing_function is None or descriptor.thumbnail_presets is None:
            continue
        if any(preset.identifier == identifier for preset in descriptor.thumbnail_presets):
            return descriptor.processing_function(image, parameters)
    return _default_render_vignette(identifier, image, parameters)


_VIGNETTE_PREVIEW_MAX_DIMENSION_PX = 480


def _downscaled_for_preview(
    image: numpy.ndarray, max_dimension: int = _VIGNETTE_PREVIEW_MAX_DIMENSION_PX
) -> numpy.ndarray:
    height, width = image.shape[0], image.shape[1]
    if max(height, width) <= max_dimension:
        return image
    scale = max_dimension / max(height, width)
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    pil_image = Image.fromarray(image, mode="RGB")
    resized = pil_image.resize((new_width, new_height), Image.Resampling.BILINEAR)
    return numpy.array(resized, dtype=numpy.uint8)


def _effective_parameters_for_vignette(
    step: PipelineStep,
    descriptor: AddonDescriptor | None,
    identifier: str,
    image_shape: tuple[int, int, int],
    selections: dict[str, str],
) -> dict[str, Any]:
    if identifier == selections.get(step.identifier, NEUTRAL_PRESET_IDENTIFIER):
        return step.parameters.values
    if descriptor is not None and descriptor.thumbnail_presets is not None:
        for preset in descriptor.thumbnail_presets:
            if preset.identifier == identifier:
                return _resolve_preset_parameter_values(preset, image_shape)
    return {}


def _compute_applied_pipeline(
    pipeline: Pipeline,
    source: numpy.ndarray,
    selections: dict[str, str],
    *,
    render_vignette: RenderVignette = _default_render_vignette,
    upto_exclusive: int | None = None,
    start_index: int = 0,
) -> tuple[dict[str, numpy.ndarray], StepError | None]:
    """`start_index` lets a caller resume from an already-computed prefix -- `source` is then that
    prefix's OUTPUT, not the pipeline's original input, and `step.identifier`-keyed `outputs`/a
    StepError's `step_index` still refer to true pipeline positions (PERF-ZOOM-RENDER-PLAN.md
    étape 1: render_zoom_after replays only the zoomed step on top of render_zoom_before's cached
    result instead of the whole pipeline). Every other caller keeps the default (0), unchanged
    behavior."""
    outputs: dict[str, numpy.ndarray] = {}
    current_input = source
    steps = pipeline._steps[start_index:upto_exclusive] if upto_exclusive is not None else pipeline._steps[start_index:]
    for offset, step in enumerate(steps):
        index = start_index + offset
        identifier = selections.get(step.identifier, NEUTRAL_PRESET_IDENTIFIER)
        try:
            parameters = _effective_parameters_for_vignette(
                step, None, identifier, current_input.shape, selections
            )
            if step.processor is not None:
                current_input = step.processor(current_input, parameters)
            else:
                current_input = render_vignette(identifier, current_input, parameters)
        except Exception as exc:
            return outputs, StepError(step.identifier, index, str(exc), cause=exc)
        outputs[step.identifier] = current_input
    return outputs, None


def _row_ancestry_signatures(
    pipeline: Pipeline, selections: dict[str, str], upto_exclusive: int
) -> dict[int, tuple]:
    signatures: dict[int, tuple] = {}
    ancestry: tuple = ()
    for i in range(min(upto_exclusive, len(pipeline._steps))):
        step = pipeline._steps[i]
        selected = selections.get(step.identifier, NEUTRAL_PRESET_IDENTIFIER)
        params = tuple(sorted(step.parameters.values.items()))
        ancestry = ancestry + ((selected, params),)
        signatures[i] = ancestry
    return signatures


def _render_pipeline_prefix(session: "Session", upto_exclusive: int) -> numpy.ndarray:
    """Full-resolution render of the pipeline's first `upto_exclusive` steps, reusing
    session.step_render_cache wherever a position's cached ancestry signature still matches the
    session's current state -- replays only the smallest invalid suffix (from the first stale
    position onward), never the whole prefix. Generalizes PERF-ZOOM-RENDER-PLAN.md étape 1's
    single-slot "before" cache (one opaque result per boundary) into one cached entry per step
    POSITION, so switching between different zoomed rows reuses shared upstream steps instead of
    recomputing them from scratch every time (étape 5). Sole reader/writer of step_render_cache;
    render_full_resolution is currently its only caller."""
    if session.pipeline is None or session.image_session is None:
        raise ValueError("No image loaded in this session")
    total_steps = len(session.pipeline._steps)
    upto_exclusive = min(upto_exclusive, total_steps)
    if upto_exclusive <= 0:
        return session.image_session.original

    fresh_signatures = _row_ancestry_signatures(session.pipeline, session.thumbnail_selections, upto_exclusive)

    with session._row_before_lock:
        start = 0
        while start < upto_exclusive:
            cached = session.step_render_cache.get(start)
            if cached is None or cached[0] != fresh_signatures[start]:
                break
            start += 1
        if start >= upto_exclusive:
            return session.step_render_cache[upto_exclusive - 1][1]
        seed = session.image_session.original if start == 0 else session.step_render_cache[start - 1][1]

    steps = session.pipeline._steps[:upto_exclusive]
    outputs, error = _compute_applied_pipeline(
        session.pipeline, seed, session.thumbnail_selections,
        render_vignette=_render_vignette, upto_exclusive=upto_exclusive, start_index=start,
    )
    if error is not None:
        raise ValueError(f"Step '{error.step_identifier}' failed: {error.detail}")

    with session._row_before_lock:
        for position in range(start, upto_exclusive):
            session.step_render_cache[position] = (fresh_signatures[position], outputs[steps[position].identifier])

    return outputs[steps[upto_exclusive - 1].identifier]


def _compute_vignette_states(
    pipeline: Pipeline,
    source: numpy.ndarray,
    row_labels: list[tuple[str, tuple[str, ...]]],
    active_index: int,
    selections: dict[str, str],
    *,
    render_vignette: RenderVignette = _default_render_vignette,
    cache: dict[int, tuple[tuple, dict[str, VignetteState]]] | None = None,
) -> dict[int, dict[str, VignetteState]]:
    if cache is None:
        cache = {}
    outputs, error = _compute_applied_pipeline(
        pipeline, source, selections, render_vignette=render_vignette
    )
    total = len(row_labels)
    failed_step_index = error.step_index if error is not None else None
    # Windowed over the WEB-visible rows only (Geometry/Framing excluded, see
    # _visible_row_real_indices) -- `active_index` is a real row index (may itself be Geometry/
    # Framing right after open_image, before the frontend has activated a real row; `visible.
    # index()` raising ValueError is avoided by defaulting to the first visible position). Real
    # indices are preserved throughout (not renumbered), same "filter, window, map back" shape as
    # web/src/components/Filmstrip.tsx's visibleRowRealIndices/visibleRowIndices split.
    visible_real = _visible_row_real_indices(total)
    active_pos = visible_real.index(active_index) if active_index in visible_real else 0
    positions = [visible_real[pos] for pos in visible_row_indices(active_pos, len(visible_real))]

    states: dict[int, dict[str, VignetteState]] = {}
    if not positions:
        return states
    ancestry_signatures = _row_ancestry_signatures(pipeline, selections, max(positions) + 1)

    for i in positions:
        # Cache key is the ancestry of rows STRICTLY BEFORE i -- not
        # ancestry_signatures.get(i), which also bakes in row i's OWN
        # selection. A row's own rendered options never depend on which one
        # is currently "selected" (_effective_parameters_for_vignette
        # resolves every identifier from its own preset regardless), so
        # keying on row i's own selection was invalidating -- and re-
        # rendering -- every option in the row on every click within it
        # (correctif de performance, 2026-07-21: this is what made the
        # 8-preset "Film" row specifically slow to click through).
        upstream_signature = ancestry_signatures.get(i - 1, ()) if i > 0 else ()
        cached = cache.get(i)
        if cached is not None and cached[0] == upstream_signature:
            states[i] = cached[1]
            continue

        _, vignette_labels = row_labels[i]
        upstream_unavailable = failed_step_index is not None and (i - 1) >= failed_step_index

        if i == 0:
            row_input = source
        else:
            row_input = outputs.get(pipeline._steps[i - 1].identifier)

        row_states: dict[str, VignetteState] = {}
        if upstream_unavailable or row_input is None:
            detail = (
                f"Step '{error.step_identifier}' failed: {error.detail}"
                if error is not None
                else "Upstream input unavailable"
            )
            for identifier in vignette_labels:
                row_states[identifier] = VignetteState(VignetteStatus.ERROR, detail=detail)
        else:
            step = pipeline._steps[i]
            row = WORKFLOW_CONFIG.rows[i] if i < len(WORKFLOW_CONFIG.rows) else None
            descriptor = _resolve_addon_for_row(row, ADDON_INDEX) if row is not None else None
            preview_input = _downscaled_for_preview(row_input)
            for identifier in vignette_labels:
                try:
                    parameters = _effective_parameters_for_vignette(
                        step, descriptor, identifier, preview_input.shape, selections
                    )
                    if step.processor is not None:
                        pixels = step.processor(preview_input, parameters)
                    else:
                        pixels = render_vignette(identifier, preview_input, parameters)
                    row_states[identifier] = VignetteState(VignetteStatus.READY, pixels=pixels)
                except Exception as exc:
                    row_states[identifier] = VignetteState(VignetteStatus.ERROR, detail=str(exc))
        cache[i] = (upstream_signature, row_states)
        states[i] = row_states

    return states


def _working_row_input(session: "Session", step_index: int) -> numpy.ndarray | None:
    """The interactive-resolution input to `step_index` -- used only to
    resolve a clicked preset's aspect-ratio crop parameters (a normalized
    0..1 fraction of image_shape, so the working copy's shape gives the
    exact same ratio as the full-resolution original would -- see
    render_full_resolution for the one place that genuinely needs full
    resolution). Renamed 2026-07-21 from _full_resolution_row_input, which
    it no longer is."""
    if session.pipeline is None or session.working_image is None:
        return None
    outputs, _ = _compute_applied_pipeline(
        session.pipeline, session.working_image, session.thumbnail_selections,
        render_vignette=_render_vignette,
    )
    if step_index == 0:
        return session.working_image
    return outputs.get(session.pipeline._steps[step_index - 1].identifier)


def render_full_resolution(session: "Session", *, upto_exclusive: int | None = None) -> numpy.ndarray:
    """On-demand, full-resolution render of the current selections --
    NEVER called by the interactive Lignes+Vignettes path (refresh_workflow/
    _compute_vignette_states/_working_row_input all stay on session.
    working_image). Two callers: export (upto_exclusive=None, the full
    pipeline) and Zoom mode's before/after comparison
    (upto_exclusive=step_index for "before", step_index + 1 for "after").
    Delegates to _render_pipeline_prefix, which reuses session.step_render_cache per step position
    instead of recomputing the whole prefix on every call (PERF-ZOOM-RENDER-PLAN.md étape 5)."""
    if session.pipeline is None or session.image_session is None:
        raise ValueError("No image loaded in this session")
    target = len(session.pipeline._steps) if upto_exclusive is None else upto_exclusive
    return _render_pipeline_prefix(session, target)


# ---------------------------------------------------------------------------
# Session: the per-request/per-project state that used to be app.py's
# module-level globals.
# ---------------------------------------------------------------------------


@dataclass
class ZoomSession:
    """One open Zoom-overlay editing session (React migration, 2026-07-22) --
    mirrors app.py's _active_zoom_target + _zoom_parameter_snapshot globals,
    but scoped to a Session instead of the process. ``parameter_snapshot`` is
    the step's parameter values at the moment Zoom was opened, so cancel_zoom
    can restore exactly that state (feature 036's own semantics)."""

    step_index: int
    identifier: str
    parameter_snapshot: dict[str, Any]
    # Snapshot of any OTHER step's parameter values touched during this Zoom session, keyed by
    # that step's own index -- e.g. Geometry/Framing edited from within a Film/Color Splash Zoom
    # (feature: cross-row corrections). Populated lazily by set_auxiliary_zoom_parameter on first
    # write to a given step, so cancel_zoom can restore it exactly like the zoomed step's own
    # parameter_snapshot. Empty for a Zoom session that never touches an auxiliary row.
    auxiliary_snapshots: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass
class _PendingRowBefore:
    """Marks a background row-before precompute in flight for one (step_index, signature) --
    PERF-ZOOM-RENDER-PLAN.md étape 4. Published into Session._active_row_before_pending so a
    concurrent render_zoom_before (Zoom opened while the precompute is still running) can wait on
    `event` for THIS exact computation instead of starting a duplicate one. `result` stays None
    until the render finishes (or fails)."""

    step_index: int
    signature: tuple
    event: threading.Event = field(default_factory=threading.Event)
    result: numpy.ndarray | None = None


@dataclass
class Session:
    id: str
    image_session: ImageSession | None = None
    # Downscaled (<=_VIGNETTE_PREVIEW_MAX_DIMENSION_PX) copy of image_session.
    # original, computed once in open_image. The ENTIRE interactive Lignes+
    # Vignettes path (refresh_workflow, _compute_vignette_states, _working_
    # row_input) runs on this, never on the full-resolution original -- full
    # resolution is reserved for render_full_resolution (export, and later
    # Zoom mode), on demand only. See the "Correctif de performance" section
    # of the migration plan for the full rationale (2026-07-21).
    #
    # A preview/export resolution-divergence hypothesis was investigated here
    # (2026-08-04) as a candidate explanation for a reported "exported RAW
    # darker than preview" bug -- measured against real RAW files and found
    # imperceptible (<0.2/255). Not the real cause; see AppShell.tsx's
    # pendingCommit guard for the actual fix (a frontend race condition).
    working_image: numpy.ndarray | None = None
    pipeline: Pipeline | None = None
    thumbnail_selections: dict[str, str] = field(default_factory=dict)
    active_step_index: int = 0
    vignette_states: dict[int, dict[str, VignetteState]] = field(default_factory=dict)
    vignette_state_cache: dict[int, tuple[tuple, dict[str, VignetteState]]] = field(default_factory=dict)
    zoom: ZoomSession | None = None
    # Per-STEP-POSITION full-resolution render cache (PERF-ZOOM-RENDER-PLAN.md étape 5), keyed by
    # pipeline position -- one entry per step, so switching between different zoomed rows reuses
    # already-computed shared upstream steps instead of recomputing them from scratch each time.
    # Also the single backing cache for the "Avant" render (précalcul en arrière-plan sur activation
    # de ligne, PERF-ZOOM-RENDER-PLAN.md étape 4 -- see precompute_row_before/render_zoom_before),
    # which used to have its own separate single-slot caches (ZoomSession.before_cache/
    # Session.active_row_before_cache, removed étape 2 once this per-position cache subsumed them).
    # Populated/consulted exclusively by _render_pipeline_prefix. Guarded by _row_before_lock -- only
    # field assignments are locked, never the render itself.
    step_render_cache: dict[int, tuple[tuple, numpy.ndarray]] = field(default_factory=dict)
    _active_row_before_pending: _PendingRowBefore | None = None
    _row_before_lock: threading.Lock = field(default_factory=threading.Lock)


def create_session() -> Session:
    return Session(id=uuid.uuid4().hex)


def open_image(session: Session, path: Path) -> ImageSession:
    """Open `path` into `session` -- mirrors app.py's open_image_into, minus
    the MainWindow/Qt widget pushes at the end."""
    image_session = load_image(path)
    session.image_session = image_session
    session.working_image = _downscaled_for_preview(image_session.original)
    pipeline = Pipeline()
    for row in WORKFLOW_CONFIG.rows:
        descriptor = _resolve_addon_for_row(row, ADDON_INDEX)
        processor = descriptor.processing_function if descriptor is not None else None
        pipeline.add_step(PipelineStep(identifier=row.identifier, processor=processor))
    session.pipeline = pipeline
    session.thumbnail_selections = {}
    session.active_step_index = 0
    session.vignette_state_cache = {}
    # A Zoom session tied to the PREVIOUS image's steps is meaningless once a new one loads.
    session.zoom = None
    # step_render_cache is keyed by (position -> (signature, pixels)) -- a stale entry from the
    # PREVIOUS image must never be served just because its signature happens to coincide with the
    # freshly-opened one (e.g. position 0, often signature ()).
    with session._row_before_lock:
        session.step_render_cache = {}
        session._active_row_before_pending = None
    refresh_workflow(session)
    return image_session


def refresh_workflow(session: Session) -> list[RowSpec]:
    """Recompute every visible row's RowSpec (labels + real vignette states)
    -- mirrors app.py's _refresh_filmstrip, minus the `window.set_workflow_
    steps(...)` push."""
    rows = WORKFLOW_ROWS
    if session.image_session is not None and session.working_image is not None and session.pipeline is not None and rows:
        # A vignette selected before a live Préférences > Workflow reload (2026-08-06 follow-up:
        # Valider now reflects immediately in an already-open session, not just the next photo
        # opened) may have since been disabled. reload_workflow_config() only swaps the module-wide
        # WORKFLOW_CONFIG/WORKFLOW_ROWS globals -- it never touches any open session's
        # thumbnail_selections -- so re-validate here, on every refresh, using the same
        # _is_vignette_enabled guarantee select_vignette/apply_recipe already enforce at their own
        # call time. Silent fallback to neutral (deleting the stale key), matching
        # select_vignette's own silent guard -- no separate correction to report for a passive
        # background reconciliation like this one (unlike apply_recipe's one-shot, user-visible
        # disabled_vignette_corrections).
        for step, row in zip(session.pipeline._steps, WORKFLOW_CONFIG.rows):
            selected = session.thumbnail_selections.get(step.identifier)
            if selected is None:
                continue
            descriptor = _resolve_addon_for_row(row, ADDON_INDEX)
            if not _is_vignette_enabled(row, descriptor, selected):
                del session.thumbnail_selections[step.identifier]

        # Interactive path: always the downscaled working copy, never
        # image_session.original -- see Session.working_image's docstring
        # and render_full_resolution for where full resolution actually
        # happens (export, Zoom).
        #
        # **Investigated and reverted (2026-08-04)**: a preview/export
        # resolution-divergence hypothesis (running addon math on this
        # downscaled copy vs. full resolution) was suspected as the cause of
        # a reported "exported RAW file darker than the preview" bug.
        # Measured empirically against real Canon/Nikon/Sony RAW files with
        # Light/High Key: the divergence was <0.2/255 (imperceptible) --
        # not the real cause. Forcing render_full_resolution here was tried
        # and reverted: it added multi-second latency to every single preset
        # click on a large RAW with no measurable correctness benefit. The
        # real root cause was a frontend race condition (AppShell.tsx firing
        # export before a pending select_vignette request resolved) -- fixed
        # there instead. See the encapsulated-crunching-hennessy plan.
        outputs, error = _compute_applied_pipeline(
            session.pipeline, session.working_image, session.thumbnail_selections,
            render_vignette=_render_vignette,
        )
        if error is None and session.pipeline._steps:
            session.image_session.replace_active(outputs[session.pipeline._steps[-1].identifier])
        row_labels = [(row.label, row.vignette_labels) for row in rows]
        vignette_states = _compute_vignette_states(
            session.pipeline, session.working_image, row_labels, session.active_step_index,
            session.thumbnail_selections, render_vignette=_render_vignette,
            cache=session.vignette_state_cache,
        )
        session.vignette_states = vignette_states
        rows = [
            RowSpec(
                label=row.label,
                vignette_labels=row.vignette_labels,
                vignette_states=vignette_states.get(i, {}),
                short_description=row.short_description,
                selected_vignette_identifier=session.thumbnail_selections.get(
                    session.pipeline._steps[i].identifier, NEUTRAL_PRESET_IDENTIFIER
                ),
            )
            for i, row in enumerate(rows)
        ]
    return rows


def activate_step(session: Session, step_index: int) -> list[RowSpec]:
    """Mirrors app.py's _on_step_activated: switch the active row without
    changing any selection."""
    if session.pipeline is None or session.image_session is None:
        raise ValueError("No image loaded in this session")
    total = len(WORKFLOW_ROWS)
    if not (0 <= step_index < total):
        raise ValueError(f"step_index {step_index} out of range [0, {total})")
    session.active_step_index = step_index
    return refresh_workflow(session)


def reset_session(session: Session) -> list[RowSpec]:
    """Clears every row's preset selection back to NEUTRAL_PRESET_IDENTIFIER, without touching the
    loaded image -- the header preset combobox's "Nouveau" entry (2026-08-05). Mirrors the reset
    lines inside open_image (thumbnail_selections/vignette_state_cache), minus reloading the file."""
    if session.pipeline is None or session.image_session is None:
        raise ValueError("No image loaded in this session")
    session.thumbnail_selections = {}
    session.active_step_index = 0
    session.vignette_state_cache = {}
    return refresh_workflow(session)


def select_vignette(session: Session, step_index: int, identifier: str) -> list[RowSpec]:
    """Mirrors app.py's _on_vignette_selected: record the click-driven
    preset choice, activate that row, and resolve the clicked identifier's
    own ThumbnailPreset into the step's live parameters (feature 041)."""
    if session.pipeline is None or session.image_session is None:
        raise ValueError("No image loaded in this session")
    total = len(WORKFLOW_ROWS)
    if not (0 <= step_index < total):
        raise ValueError(f"step_index {step_index} out of range [0, {total})")
    session.active_step_index = step_index
    step = session.pipeline._steps[step_index]
    row = WORKFLOW_CONFIG.rows[step_index] if step_index < len(WORKFLOW_CONFIG.rows) else None
    descriptor = _resolve_addon_for_row(row, ADDON_INDEX) if row is not None else None
    if not _is_vignette_enabled(row, descriptor, identifier):
        # Defense-in-depth (Préférences > Workflow, 2026-08-06): the frontend never renders a card
        # for a disabled vignette, so this only guards a stale/racing direct call -- fall back to
        # neutral rather than ever applying a disabled vignette's rendering.
        identifier = NEUTRAL_PRESET_IDENTIFIER
    if session.thumbnail_selections.get(step.identifier) == identifier:
        # Already the row's current selection -- no parameter rewrite, just activate the row.
        # Without this guard, a plain click on an already-selected vignette (which ALWAYS fires
        # before a dblclick, per browser event order) silently discards any confirmed Zoom-only
        # override for it -- including Light's subject-mask contour -- every time the user reopens
        # Zoom on a vignette they'd already left as selected. open_zoom's own guard below can't
        # prevent this by itself: it runs AFTER the preceding click has already done the damage.
        return refresh_workflow(session)
    session.thumbnail_selections[step.identifier] = identifier
    if descriptor is not None and descriptor.thumbnail_presets is not None:
        row_input = _working_row_input(session, step_index)
        image_shape = row_input.shape if row_input is not None else session.working_image.shape
        for preset in descriptor.thumbnail_presets:
            if preset.identifier == identifier:
                step.parameters.values = _resolve_preset_parameter_values(preset, image_shape)
                break
    return refresh_workflow(session)


# ---------------------------------------------------------------------------
# Zoom overlay (React migration, 2026-07-22) -- the mockup's before/after
# split-compare + "Réglages manuels" sliders screen, backed by the addon
# zoom-parameter mechanism that already existed (film.py's `intensity`,
# `parameter_descriptions`/`zoom_only`) but was never consumed by anything
# until now. Mirrors app.py's _on_zoom_requested/_on_zoom_confirm/
# _on_zoom_cancel/_on_zoom_parameter_changed, adapted to per-Session state
# instead of module globals (same seam as everything else in this file).
# ---------------------------------------------------------------------------


def open_zoom(session: Session, step_index: int, identifier: str) -> None:
    """Opens a Zoom session on one candidate vignette. If `identifier` is not
    already the row's current selection, promotes+selects it first (same
    convention as a single click -- see select_vignette's own docstring);
    if it's already selected, selection is left untouched so any previously
    confirmed manual-adjustment values for it are NOT reset back to the
    preset's bare defaults (select_vignette always re-resolves parameter
    values from scratch, which would otherwise silently discard a prior
    Zoom confirm every time the same already-selected vignette is reopened).
    Snapshots the step's parameter values (post-selection) so cancel_zoom can
    restore them.
    """
    if session.pipeline is None or session.image_session is None:
        raise ValueError("No image loaded in this session")
    total = len(WORKFLOW_ROWS)
    if not (0 <= step_index < total):
        raise ValueError(f"step_index {step_index} out of range [0, {total})")
    step = session.pipeline._steps[step_index]
    current_identifier = session.thumbnail_selections.get(step.identifier, NEUTRAL_PRESET_IDENTIFIER)
    if identifier != current_identifier:
        select_vignette(session, step_index, identifier)
    session.zoom = ZoomSession(
        step_index=step_index, identifier=identifier, parameter_snapshot=dict(step.parameters.values)
    )


def _row_descriptor_by_index(step_index: int) -> AddonDescriptor | None:
    if not (0 <= step_index < len(WORKFLOW_CONFIG.rows)):
        return None
    return _resolve_addon_for_row(WORKFLOW_CONFIG.rows[step_index], ADDON_INDEX)


def _zoom_row_descriptor(session: Session) -> AddonDescriptor | None:
    if session.zoom is None:
        return None
    return _row_descriptor_by_index(session.zoom.step_index)


def zoom_parameter_declarations(session: Session) -> tuple[ZoomParameterDeclaration, ...]:
    """The current Zoom session's real, addon-declared adjustable parameters
    (e.g. film.py's 14 sliders) -- empty for a row whose addon declares none."""
    descriptor = _zoom_row_descriptor(session)
    return descriptor.zoom_parameters if descriptor is not None and descriptor.zoom_parameters else ()


def zoom_effective_values(session: Session) -> dict[str, float]:
    """The value ACTUALLY in effect for every zoom parameter of the current
    Zoom session -- an override already present in the step's parameter
    values (e.g. from a previously confirmed Zoom edit) wins, otherwise the
    addon's own calibrated/neutral value (via AddonDescriptor.
    resolve_zoom_values). Empty dict for a row with no addon, or an addon
    that declares no resolver. This is the fix for the "sliders seed with a
    generic neutral value instead of the selected look's real value" bug
    (2026-07-22) -- see film.py's resolve_zoom_values for the Film-specific
    implementation."""
    descriptor = _zoom_row_descriptor(session)
    if descriptor is None or descriptor.resolve_zoom_values is None:
        return {}
    step = session.pipeline._steps[session.zoom.step_index]
    return descriptor.resolve_zoom_values(step.parameters.values)


def zoom_pure_default_values(session: Session) -> dict[str, float]:
    """Same as zoom_effective_values, but computed from a stripped-down
    {"look": ..., "intensity": 1.0} input -- i.e. ignoring any override
    already in effect. This is the TRUE calibrated baseline for the
    selection, used as the Zoom overlay's "Réinitialiser" target (mirrors the
    mockup's own neutralParams() intent: reset means back to the look's pure
    recipe, not back to whatever value was showing when Zoom was opened)."""
    descriptor = _zoom_row_descriptor(session)
    if descriptor is None or descriptor.resolve_zoom_values is None:
        return {}
    step = session.pipeline._steps[session.zoom.step_index]
    pure_params = {"look": step.parameters.values.get("look"), "intensity": 1.0}
    return descriptor.resolve_zoom_values(pure_params)


# ---------------------------------------------------------------------------
# Auxiliary zoom parameters -- Geometry/Cadrage integrated into Film/Color
# Splash's own Zoom (cross-row corrections). Unlike the functions above,
# these are NOT scoped to `session.zoom.step_index` (the currently open
# row): they resolve an arbitrary OTHER row by its `config_workflow.json`
# identifier (e.g. "geometry", "framing"), so Film/Color Splash's Zoom can
# read/write Geometry's or Framing's own step while its own Zoom session
# stays open on Film/Color Splash. Requires a Zoom session to be open (any
# row), same precondition as the rest of this module's zoom functions.
# ---------------------------------------------------------------------------


def auxiliary_zoom_declarations(session: Session, row_identifier: str) -> tuple[ZoomParameterDeclaration, ...]:
    """Same as zoom_parameter_declarations, but for `row_identifier` instead of the currently
    zoomed row -- e.g. Geometry's corner_*/rotation_angle declarations while Film's own Zoom is
    open."""
    step_index = _row_index_by_identifier(row_identifier)
    if step_index is None:
        return ()
    descriptor = _row_descriptor_by_index(step_index)
    return descriptor.zoom_parameters if descriptor is not None and descriptor.zoom_parameters else ()


def auxiliary_zoom_effective_values(session: Session, row_identifier: str) -> dict[str, float]:
    """Same as zoom_effective_values, but for `row_identifier` instead of the currently zoomed
    row."""
    if session.pipeline is None:
        return {}
    step_index = _row_index_by_identifier(row_identifier)
    if step_index is None or not (0 <= step_index < len(session.pipeline._steps)):
        return {}
    descriptor = _row_descriptor_by_index(step_index)
    if descriptor is None or descriptor.resolve_zoom_values is None:
        return {}
    step = session.pipeline._steps[step_index]
    return descriptor.resolve_zoom_values(step.parameters.values)


def auxiliary_zoom_pure_default_values(session: Session, row_identifier: str) -> dict[str, float]:
    """Same as zoom_pure_default_values, but for `row_identifier` instead of the currently zoomed
    row -- the "Réinitialiser" target for Geometry's/Framing's own stage when opened from within
    Film/Color Splash's Zoom. Geometry/Framing's own resolve_zoom_values implementations ignore
    the Film-specific "look"/"intensity" keys entirely (they only read their own corner_*/
    rotation_angle or crop_* keys), so passing the same stripped-down input here is harmless and
    keeps this symmetric with zoom_pure_default_values."""
    if session.pipeline is None:
        return {}
    step_index = _row_index_by_identifier(row_identifier)
    if step_index is None or not (0 <= step_index < len(session.pipeline._steps)):
        return {}
    descriptor = _row_descriptor_by_index(step_index)
    if descriptor is None or descriptor.resolve_zoom_values is None:
        return {}
    step = session.pipeline._steps[step_index]
    pure_params = {"look": step.parameters.values.get("look"), "intensity": 1.0}
    return descriptor.resolve_zoom_values(pure_params)


def render_auxiliary_before(session: Session, row_identifier: str) -> numpy.ndarray:
    """Full-resolution render of the pipeline up to (excluding) `row_identifier`'s own step -- the
    background photo for Geometry's/Framing's interactive stage (corner handles, crop frame) when
    opened from within Film/Color Splash's Zoom, same "before" convention as render_zoom_before
    uses for a row zoomed directly."""
    if session.zoom is None:
        raise ValueError("No Zoom session open")
    step_index = _row_index_by_identifier(row_identifier)
    if step_index is None:
        raise ValueError(f"Unknown row identifier '{row_identifier}'")
    return render_full_resolution(session, upto_exclusive=step_index)


def set_auxiliary_zoom_parameter(session: Session, row_identifier: str, identifier: str, value: float) -> None:
    """Writes one edit into `row_identifier`'s own step (Geometry's corner_*/rotation_angle,
    Framing's crop_*) while a Zoom session is open on a DIFFERENT row (Film/Color Splash) --
    mirrors set_zoom_parameter, but targets an explicit row instead of session.zoom.step_index.
    Snapshots that step's parameter values on first write this session (lazily, keyed by step
    index) so cancel_zoom can restore them alongside the zoomed step's own snapshot. Deliberately
    does NOT re-render (unlike set_zoom_parameter, which the plain-slider debounce path relies on)
    -- the combined preview is only recomputed when the caller explicitly renders zoom/after,
    triggered by the "Appliquer" button, same convention GeometryCanvas/CropCanvas already use for
    their own corner/crop drags."""
    if session.zoom is None:
        raise ValueError("No Zoom session open")
    if session.pipeline is None:
        raise ValueError("No image loaded in this session")
    step_index = _row_index_by_identifier(row_identifier)
    if step_index is None or not (0 <= step_index < len(session.pipeline._steps)):
        raise ValueError(f"Unknown row identifier '{row_identifier}'")
    step = session.pipeline._steps[step_index]
    if step_index not in session.zoom.auxiliary_snapshots:
        session.zoom.auxiliary_snapshots[step_index] = dict(step.parameters.values)
    step.parameters.values[identifier] = value


def _before_signature_for_step(session: Session, step_index: int) -> tuple:
    """Ancestry signature (selection + params) of every step strictly before step_index -- reuses
    _row_ancestry_signatures' own convention (see _compute_vignette_states' cache). Changes
    whenever an upstream preset selection or an auxiliary-row edit (set_auxiliary_zoom_parameter
    writes directly into that step's live parameters.values) would change that step's "before"
    render, and ONLY then. Shared by _zoom_before_signature (Zoom's own before/after compare) and
    the background row-before precompute (PERF-ZOOM-RENDER-PLAN.md étape 4), so both agree on
    exactly when a cached "before" render is still valid -- a single invalidation rule, not two."""
    if session.pipeline is None or step_index == 0:
        return ()
    signatures = _row_ancestry_signatures(session.pipeline, session.thumbnail_selections, step_index)
    return signatures.get(step_index - 1, ())


def _zoom_before_signature(session: Session) -> tuple:
    if session.pipeline is None or session.zoom is None:
        return ()
    return _before_signature_for_step(session, session.zoom.step_index)


_ROW_BEFORE_PRECOMPUTE_DELAY_S = 0.4
_ROW_BEFORE_WAIT_TIMEOUT_S = 12.0


def precompute_row_before(session: Session, step_index: int) -> None:
    """Background task (FastAPI BackgroundTasks, scheduled by activate_step_endpoint/
    select_vignette_endpoint) that renders and caches the "Avant" view for step_index ahead of
    time, so render_zoom_before finds session.step_render_cache already warm instead of computing
    cold when the user actually opens Zoom on this row (PERF-ZOOM-RENDER-PLAN.md étape 4). Runs
    AFTER the HTTP response is sent, on the same threadpool as every other synchronous endpoint in
    this file -- never blocks the request that scheduled it.

    The delay + recheck avoids wasted work for a row only briefly passed through (e.g. arrow-key
    navigation), mirroring the debounce reasoning already used on the frontend (see
    ZoomOverlay.tsx's scheduleParameterUpdate). Publishing a _PendingRowBefore BEFORE doing the
    actual (possibly multi-second) render, and only holding _row_before_lock around the small
    field checks/assignments rather than the render itself, is what lets a concurrent
    render_zoom_before wait for this exact computation instead of starting a duplicate one -- see
    its docstring. render_full_resolution (via _render_pipeline_prefix) is what actually populates
    step_render_cache; this function only decides WHETHER a render is still needed."""
    if step_index == 0:
        return  # "Avant" there is the raw source image -- already instant, nothing to precompute.
    time.sleep(_ROW_BEFORE_PRECOMPUTE_DELAY_S)
    if session.pipeline is None or session.image_session is None:
        return
    if session.active_step_index != step_index:
        return  # User already moved on -- this row's "Avant" isn't imminently needed.
    signature = _before_signature_for_step(session, step_index)
    pending = _PendingRowBefore(step_index, signature)
    with session._row_before_lock:
        cached = session.step_render_cache.get(step_index - 1)
        if cached is not None and cached[0] == signature:
            return  # Already cached -- e.g. render_zoom_before's own cold path got there first.
        existing = session._active_row_before_pending
        if existing is not None and existing.step_index == step_index and existing.signature == signature:
            return  # Another precompute for this exact (step_index, signature) is already running.
        session._active_row_before_pending = pending
    try:
        pixels = render_full_resolution(session, upto_exclusive=step_index)
    except ValueError:
        # Pipeline failed (e.g. a step errored) -- nothing to cache; a later Zoom-open will compute
        # cold and surface the error there instead.
        with session._row_before_lock:
            if session._active_row_before_pending is pending:
                session._active_row_before_pending = None
        pending.event.set()
        return
    with session._row_before_lock:
        pending.result = pixels
        if session._active_row_before_pending is pending:
            session._active_row_before_pending = None
    pending.event.set()


def render_zoom_before(session: Session) -> numpy.ndarray:
    """Full-resolution render of the pipeline up to (excluding) the zoomed step -- the split-
    compare's "AVANT" pane. Backed by session.step_render_cache (PERF-ZOOM-RENDER-PLAN.md étape 5,
    subsuming étape 1's original ZoomSession-scoped cache) via render_full_resolution -- every step
    strictly before the zoomed one is fixed for the life of a Zoom session unless an auxiliary row
    is edited, so recomputing it from scratch on every render_zoom_after call (its main caller) was
    pure waste. Being session-scoped rather than Zoom-session-scoped also means switching between
    two different zoomed rows (e.g. Film -> Vignettage) reuses whatever shared upstream steps
    neither edit touched, instead of starting cold on every new Zoom.

    Before falling back to a cold render, also consults the étape-4 in-flight precompute (see
    precompute_row_before): a matching in-flight precompute is waited on (bounded by
    _ROW_BEFORE_WAIT_TIMEOUT_S) rather than racing it with a second, redundant render -- a ready
    match is already found by render_full_resolution's own cache check, so no separate lookup is
    needed here for that case. The cold path (render_full_resolution) itself also publishes into
    step_render_cache, so a precompute that was merely delayed (still in its debounce sleep) finds
    the work already done and skips it too -- closing the race in both directions."""
    if session.zoom is None:
        raise ValueError("No Zoom session open")
    step_index = session.zoom.step_index
    signature = _zoom_before_signature(session)

    with session._row_before_lock:
        pending = session._active_row_before_pending
        if pending is not None and (pending.step_index != step_index or pending.signature != signature):
            pending = None  # In flight for a different row/signature -- irrelevant here.

    if pending is not None:
        if pending.event.wait(timeout=_ROW_BEFORE_WAIT_TIMEOUT_S) and pending.result is not None:
            return pending.result
        # Timed out, or the precompute failed (result stayed None) -- fall through to a cold
        # render rather than ever risk blocking indefinitely or serving nothing.

    pixels = render_full_resolution(session, upto_exclusive=step_index)
    with session._row_before_lock:
        resolved = session._active_row_before_pending
        if resolved is not None and resolved.step_index == step_index and resolved.signature == signature:
            resolved.result = pixels
            session._active_row_before_pending = None
        else:
            resolved = None
    if resolved is not None:
        resolved.event.set()
    return pixels


def render_zoom_after(session: Session, *, max_dimension: int | None = None) -> numpy.ndarray:
    """Render including the zoomed step, with its CURRENT (possibly live-edited) parameter values
    -- the split-compare's "APRÈS" pane. Reuses render_zoom_before's cached upstream result and
    replays only the zoomed step itself on top (PERF-ZOOM-RENDER-PLAN.md étape 1), instead of the
    whole pipeline from the source image on every call -- see render_zoom_before's docstring for
    the cache/invalidation contract this relies on.

    A full-resolution call (max_dimension=None) also writes its own result into
    session.step_render_cache[step_index] (étape 5's last gap: only the steps strictly BEFORE the
    zoomed one used to be cached, never the zoomed step's own output) -- keyed by the ancestry
    signature INCLUSIVE of the zoomed step's current parameter values, so opening Zoom on a row
    further downstream right after can reuse this step's output too via render_full_resolution's
    own prefix scan, not just the steps before it. A live slider edit naturally invalidates this
    entry the same way every other position does: the next read computes a different signature (it
    bakes in step.parameters.values), so it simply misses the cache instead of serving stale
    pixels -- no manual invalidation on confirm/cancel needed.

    `max_dimension`, when given, downscales the cached "before" (via _downscaled_for_preview, the
    SAME helper the interactive Lignes+Vignettes preview path already uses) before replaying the
    zoomed step on it -- a smaller, faster render for the reduced-resolution preview requested
    while a slider is being actively dragged (étape 2). This never mutates the cached full-
    resolution "before" itself: the downscale happens on a local copy only, so a later full-
    resolution call (max_dimension=None) still starts from the real thing, not a degraded cache.
    For the same reason, a reduced call must NEVER write into step_render_cache either -- that
    cache is full-resolution-only, exactly like the "before" pane it already protects."""
    if session.zoom is None:
        raise ValueError("No Zoom session open")
    if session.pipeline is None or session.image_session is None:
        raise ValueError("No image loaded in this session")
    step_index = session.zoom.step_index
    before = render_zoom_before(session)
    if max_dimension is not None:
        before = _downscaled_for_preview(before, max_dimension)
    outputs, error = _compute_applied_pipeline(
        session.pipeline, before, session.thumbnail_selections,
        render_vignette=_render_vignette, upto_exclusive=step_index + 1, start_index=step_index,
    )
    if error is not None:
        raise ValueError(f"Step '{error.step_identifier}' failed: {error.detail}")
    result = outputs[session.pipeline._steps[step_index].identifier]
    if max_dimension is None:
        signature = _before_signature_for_step(session, step_index + 1)
        with session._row_before_lock:
            session.step_render_cache[step_index] = (signature, result)
    return result


def set_zoom_parameter(session: Session, identifier: str, value: float) -> None:
    """Writes one slider edit into the zoomed step's live parameter values --
    mirrors app.py's _on_zoom_parameter_changed. The caller re-renders via
    render_zoom_after to see the effect; deliberately NOT done here, so the
    API layer can debounce the (full-resolution, potentially several-second)
    re-render instead of recomputing it on every single slider tick."""
    if session.zoom is None:
        raise ValueError("No Zoom session open")
    if session.pipeline is None:
        raise ValueError("No image loaded in this session")
    step = session.pipeline._steps[session.zoom.step_index]
    step.parameters.values[identifier] = value


def set_zoom_parameters(session: Session, updates: list[tuple[str, float]]) -> None:
    """Writes N slider edits into the zoomed step's live parameter values in one call --
    same write-only division of responsibility as set_zoom_parameter (the API layer renders
    once, after all writes, not here). A later duplicate identifier wins (last write wins),
    matching what a sequence of individual set_zoom_parameter calls would already produce.
    Required so "Réinitialiser" (~137 Light parameters) and a polygon-vertex commit (up to 65
    scalar keys) trigger exactly one full-resolution render instead of one per value."""
    if session.zoom is None:
        raise ValueError("No Zoom session open")
    if session.pipeline is None:
        raise ValueError("No image loaded in this session")
    step = session.pipeline._steps[session.zoom.step_index]
    for identifier, value in updates:
        step.parameters.values[identifier] = value


def confirm_zoom(session: Session) -> list[RowSpec]:
    """Keeps whatever edits were made since Zoom was opened (drops the
    snapshot -- including any auxiliary_snapshots, e.g. Geometry/Framing edited from within this
    Zoom session; those edits already live directly on their own steps' parameter values, so
    simply discarding the snapshot keeps them), refreshes the workflow, and closes the Zoom
    session -- mirrors app.py's _on_zoom_confirm."""
    if session.zoom is None:
        raise ValueError("No Zoom session open")
    session.zoom = None
    return refresh_workflow(session)


def cancel_zoom(session: Session) -> list[RowSpec]:
    """Discards whatever edits were made since Zoom was opened (restores the
    snapshot taken in open_zoom, plus any auxiliary row -- e.g. Geometry/Framing edited from
    within this Zoom session, see set_auxiliary_zoom_parameter -- touched since), refreshes the
    workflow, and closes the Zoom session -- mirrors app.py's _on_zoom_cancel."""
    if session.zoom is None:
        raise ValueError("No Zoom session open")
    if session.pipeline is None:
        raise ValueError("No image loaded in this session")
    step = session.pipeline._steps[session.zoom.step_index]
    step.parameters.values = dict(session.zoom.parameter_snapshot)
    for aux_step_index, aux_snapshot in session.zoom.auxiliary_snapshots.items():
        session.pipeline._steps[aux_step_index].parameters.values = dict(aux_snapshot)
    session.zoom = None
    return refresh_workflow(session)


# ---------------------------------------------------------------------------
# Recipes -- mirrors app.py's build_recipe_from_pipeline / build_pipeline_
# from_recipe / the "load_recipe" action, minus the QFileDialog/QMessageBox
# prompts (those become the API caller's responsibility: dest_path + force).
# ---------------------------------------------------------------------------


def build_recipe(session: Session) -> Recipe:
    if session.pipeline is None or session.image_session is None:
        raise ValueError("No image loaded in this session")
    source = session.image_session.source
    steps = [
        StepEntry(
            step_identifier=step.identifier,
            thumbnail_identifier=session.thumbnail_selections.get(
                step.identifier, NEUTRAL_PRESET_IDENTIFIER
            ),
            parameters=dict(step.parameters.values),
        )
        for step in session.pipeline._steps
    ]
    return Recipe(
        schema_version=RECIPE_SCHEMA_VERSION,
        source=SourceReference(filename=source.name, width=source.width, height=source.height),
        steps=steps,
    )


# Row identifiers whose addon parameters are normalized fractions relative to the image's own
# width/height (framing.py::_resolve_box, geometry.py::_resolve_corners/_resolve_angle) -- the only
# steps a differing aspect ratio can visually shear. Color/tone addons (Film,
# Light, Vignette, ...) don't consume dimension-relative parameters, so they're deliberately never
# flagged, even at a wildly different ratio.
DIMENSION_DEPENDENT_STEP_IDENTIFIERS = {"geometry", "framing"}

# Relative tolerance on the width/height ratio comparison, not absolute dimensions
# -- accommodates a recipe re-applied to a resized (same-ratio) copy of its original image
# without a false positive, while still catching a genuine aspect-ratio change (e.g. portrait vs.
# paysage).
DIMENSION_RATIO_TOLERANCE = 0.02


@dataclass
class DimensionWarningStep:
    step_identifier: str
    # "applied_as_is" | "adapted" (feature 048, US2 AC2) -- always "applied_as_is" today: no addon
    # currently re-normalizes its geometry/framing parameters for a differing target ratio, it just
    # applies the same fractional box/corners unchanged (the very reason this warning exists). The
    # field exists so a future ratio-aware adaptation can report "adapted" for a given step without
    # another contract change.
    status: str


@dataclass
class DimensionWarning:
    incompatible: bool
    step_identifiers: list[str]
    steps: list[DimensionWarningStep]


@dataclass
class RecipeApplicationOutcome:
    rows: list[RowSpec]
    dimension_warning: DimensionWarning | None
    parameter_corrections: list["ParameterCorrection"]
    disabled_vignette_corrections: list["DisabledVignetteCorrection"]


def _detect_dimension_warning(recipe: Recipe, image_session: ImageSession) -> DimensionWarning | None:
    """Non-blocking signal, deliberately separate from check_compatibility/apply_recipe_pipeline's
    all-or-nothing CompatibilityReport path -- that path is reserved for the hard
    failures feature 048 owns (missing addon, bad schema version); this one must never prevent the
    recipe from being applied (FR-004's Edge Case: export MUST remain possible regardless)."""
    source = recipe.source
    if not source.width or not source.height:
        return None
    active = image_session.source
    if not active.width or not active.height:
        return None

    recipe_ratio = source.width / source.height
    active_ratio = active.width / active.height
    if abs(active_ratio - recipe_ratio) / recipe_ratio <= DIMENSION_RATIO_TOLERANCE:
        return None

    affected = [
        step.step_identifier
        for step in recipe.steps
        if step.step_identifier in DIMENSION_DEPENDENT_STEP_IDENTIFIERS
    ]
    if not affected:
        return None
    return DimensionWarning(
        incompatible=True,
        step_identifiers=affected,
        steps=[DimensionWarningStep(step_identifier=identifier, status="applied_as_is") for identifier in affected],
    )


@dataclass
class ParameterCorrection:
    step_identifier: str
    parameter: str
    requested: float
    applied: float


@dataclass
class DisabledVignetteCorrection:
    """A recipe step whose chosen vignette (`requested_identifier`) is no longer enabled for its
    row (Préférences > Workflow, 2026-08-06) -- apply_recipe substitutes that row's neutral
    vignette instead of ever applying a disabled vignette's rendering (see _is_vignette_enabled).
    Non-blocking, same family as ParameterCorrection/DimensionWarning -- surfaced to the user
    rather than silently swapped."""

    step_identifier: str
    requested_identifier: str


# Addons whose resolution functions clamp/correct an out-of-bounds parameter and return enough
# information to compare "requested" (raw recipe value) against "applied" (resolved value) --
# populated per addon in _parameter_corrections_for_step below.
# A step identifier absent from this set never produces a correction signal, either because the
# addon has no bounded numeric parameters or because it isn't dimension/
# geometry-like enough to warrant one.
def _parameter_corrections_for_step(step: StepEntry, resolved_parameters: dict) -> list[ParameterCorrection]:
    corrections: list[ParameterCorrection] = []
    for key, requested in step.parameters.items():
        if not isinstance(requested, (int, float)) or isinstance(requested, bool):
            continue
        applied = resolved_parameters.get(key)
        if not isinstance(applied, (int, float)) or isinstance(applied, bool):
            continue
        if requested != applied:
            corrections.append(
                ParameterCorrection(
                    step_identifier=step.step_identifier,
                    parameter=key,
                    requested=float(requested),
                    applied=float(applied),
                )
            )
    return corrections


def apply_recipe(session: Session, recipe: Recipe) -> RecipeApplicationOutcome:
    """Raises MissingAddonReport-wrapping ValueError-like exceptions the same
    way app.py's action handler does (check_addon_availability then
    apply_recipe_pipeline) -- the FastAPI layer translates those into HTTP
    error responses."""
    if session.image_session is None:
        raise ValueError("No image loaded in this session")
    rows_by_identifier = {row.identifier: row for row in WORKFLOW_CONFIG.rows}
    # FR-001 (feature 048): a recipe's step_identifier is a WORKFLOW ROW identifier (e.g.
    # "geometry", "framing"), not an addon's own identifier -- "missing" means the row no longer
    # exists in the CURRENT WORKFLOW_CONFIG at all (e.g. a recipe authored against an older/
    # renamed config). Previously this always passed available_addon_ids=None, which
    # check_addon_availability treats as "permissive" (never reports anything missing) --
    # RecipeAddonsMissing could structurally never fire. A row that DOES exist but whose category
    # has no matching addon (_resolve_addon_for_row returns None) is a separate, pre-existing,
    # tolerated case (the step runs as a no-op identity pass-through, see the loop below) --
    # unrelated to a recipe/config mismatch, so it is deliberately not flagged here.
    missing = check_addon_availability(recipe.steps, available_addon_ids=set(rows_by_identifier))
    if missing is not None:
        raise RecipeAddonsMissing(missing)

    pipeline = Pipeline()
    thumbnail_selections: dict[str, str] = {}
    parameter_corrections: list[ParameterCorrection] = []
    disabled_vignette_corrections: list[DisabledVignetteCorrection] = []
    for step in recipe.steps:
        row = rows_by_identifier.get(step.step_identifier)
        processor = None
        thumbnail_identifier = step.thumbnail_identifier
        parameters = dict(step.parameters)
        if row is not None:
            descriptor = _resolve_addon_for_row(row, ADDON_INDEX)
            if descriptor is not None:
                processor = descriptor.processing_function
            if not _is_vignette_enabled(row, descriptor, thumbnail_identifier):
                # Préférences > Workflow (2026-08-06): a since-disabled vignette must never have
                # its rendering applied -- fall back to this row's neutral vignette (empty
                # parameters) instead of the recipe's baked-in ones, and surface the substitution
                # non-blockingly rather than silently.
                disabled_vignette_corrections.append(
                    DisabledVignetteCorrection(
                        step_identifier=step.step_identifier, requested_identifier=thumbnail_identifier
                    )
                )
                thumbnail_identifier = NEUTRAL_PRESET_IDENTIFIER
                parameters = {}
            elif descriptor is not None and descriptor.resolve_zoom_values is not None:
                # Every builtin addon's resolve_zoom_values already applies the same defensive
                # clamping/fallback its processing_function does -- comparing its
                # output against the recipe's raw values is a diff, not new bounding logic.
                resolved = descriptor.resolve_zoom_values(step.parameters)
                parameter_corrections.extend(_parameter_corrections_for_step(step, resolved))
        pipeline.add_step(
            PipelineStep(
                identifier=step.step_identifier,
                parameters=StepParameters(values=parameters),
                processor=processor,
            )
        )
        thumbnail_selections[step.step_identifier] = thumbnail_identifier

    result = apply_recipe_pipeline(pipeline, session.image_session)
    if not result.succeeded:
        raise RecipeApplicationFailed(result)

    dimension_warning = _detect_dimension_warning(recipe, session.image_session)

    session.pipeline = pipeline
    session.thumbnail_selections = thumbnail_selections
    session.active_step_index = 0
    session.vignette_state_cache = {}
    return RecipeApplicationOutcome(
        rows=refresh_workflow(session),
        dimension_warning=dimension_warning,
        parameter_corrections=parameter_corrections,
        disabled_vignette_corrections=disabled_vignette_corrections,
    )


class RecipeAddonsMissing(Exception):
    def __init__(self, report: MissingAddonReport) -> None:
        super().__init__(f"Missing addons: {', '.join(report.missing_addon_ids)}")
        self.report = report


class RecipeApplicationFailed(Exception):
    """Carries result.compatibility.issues (step_identifier/reason per issue, from
    check_compatibility's rules -- currently never populated in the live app.py wiring, which
    calls apply_recipe_pipeline without rules) OR, for the actual failure path that fires in
    practice today (a step's processor raising during execution), result.execution.error's own
    step_identifier/detail -- so the message is meaningful under either path instead of only the
    generic constant it used to carry."""

    def __init__(self, result) -> None:
        issues = result.compatibility.issues
        if issues:
            self.step_identifiers = [issue.step_identifier for issue in issues]
            self.reasons = [issue.reason for issue in issues]
        elif result.execution is not None and result.execution.error is not None:
            self.step_identifiers = [result.execution.error.step_identifier]
            self.reasons = [result.execution.error.detail]
        else:
            self.step_identifiers = []
            self.reasons = []
        message = (
            "; ".join(f"{sid}: {reason}" for sid, reason in zip(self.step_identifiers, self.reasons))
            or "Recipe is not compatible with the current image"
        )
        super().__init__(message)
        self.result = result
