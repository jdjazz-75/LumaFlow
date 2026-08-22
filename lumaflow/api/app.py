# LumaFlow v1.0 (2026-08-07)
# Application FastAPI : endpoints REST (sessions, workflow, zoom, recettes,
# preferences, dialogues natifs) et service du frontend React construit.
"""FastAPI app -- started as Phase 1 of the PySide6 -> Web migration plan
(2026-07-20), proving the seam (Session -> FastAPI -> JSON/PNG) end to end
against the real engine/addons/config code before building out the rest.
"""
from __future__ import annotations

import asyncio
import io
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import Tk, filedialog

import numpy
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from lumaflow.addons.contract import ZoomParameterDeclaration
from lumaflow.api import session as session_module
from lumaflow.api.session import (
    ADDON_INDEX,
    RecipeAddonsMissing,
    RecipeApplicationFailed,
    Session,
    activate_step,
    apply_recipe,
    auxiliary_zoom_declarations,
    auxiliary_zoom_effective_values,
    auxiliary_zoom_pure_default_values,
    build_recipe,
    cancel_zoom,
    confirm_zoom,
    create_session,
    open_image,
    open_zoom,
    precompute_row_before,
    refresh_workflow,
    reload_workflow_config,
    render_auxiliary_before,
    render_full_resolution,
    render_zoom_after,
    render_zoom_before,
    reset_session,
    row_has_zoom,
    select_vignette,
    set_auxiliary_zoom_parameter,
    set_zoom_parameter,
    set_zoom_parameters,
    zoom_effective_values,
    zoom_parameter_declarations,
    zoom_pure_default_values,
)
from lumaflow.config.workflow import (
    WorkflowConfig,
    WorkflowConfigIOError,
    WorkflowConfigValidationError,
    WorkflowRow,
    catalog_thumbnail_presets,
    default_workflow_config_path,
    load_workflow_config,
    save_workflow_config,
)
from lumaflow.engine import raw_formats
from lumaflow.engine.errors import ImageIOError
from lumaflow.engine.image_io import export_image, resolve_jpeg_export_params
from lumaflow.persistence.preferences import (
    UIPreferences,
    default_preferences_path,
    load_preferences,
    save_preferences,
)
from lumaflow.persistence.recipe import (
    RecipeIOError,
    RecipeValidationError,
    load_recipe,
    save_recipe,
    validate_session_completeness,
)
from lumaflow.api.filmstrip_types import RowSpec, VignetteStatus

app = FastAPI(title="LumaFlow API")

# The React dev server runs on a different origin (Vite default :5173) than
# this API (:8000) -- both local-only (plan's deployment decision), but the
# browser's CORS policy still applies across those two localhost ports.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store (Phase 1 scope: single local-machine process, no
# persistence across restarts -- matches the "local web app, no auth/multi-
# tenant" deployment decision in the plan).
_sessions: dict[str, Session] = {}


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown session '{session_id}'")
    return session


# Native OS file dialogs -- this is a strictly local web app (deployment
# decision in the migration plan: server and browser on the same machine,
# no auth/remote users), so popping a real native dialog from the API
# process and returning the chosen path is simpler and more honestly
# "native" than trying to fake one with <input type="file"> (which can
# never expose an absolute filesystem path, by browser design -- the /open
# endpoint needs one). tkinter ships with CPython, no extra dependency.
IMAGE_FILE_TYPES = [
    ("Images", "*.png *.jpg *.jpeg"),
    ("RAW", " ".join(f"*{ext}" for ext in sorted(raw_formats.RAW_EXTENSIONS))),
    ("Tous les fichiers", "*.*"),
]


class FileDialogOut(BaseModel):
    path: str | None


# Tkinter is not thread-safe: a Tcl interpreter must be driven from the same OS thread that
# created it, but FastAPI's default `run_in_threadpool` (what a plain `def` endpoint gets) can
# and does dispatch different requests to different worker threads from its shared pool. Two
# Tk()/askXxx() calls landing on different threads crashes the *entire server process* --
# "RuntimeError: main thread is not in main loop" followed by a fatal, uncatchable
# "Tcl_AsyncDelete: async handler deleted by the wrong thread" abort (reproduced 2026-08-05 while
# adding the 5th dialog below: concurrent requests during automated testing spread across more
# threadpool workers than the previous single-dialog-at-a-time manual usage ever had). Fix: every
# dialog call is funneled through this single dedicated worker thread instead, so every Tk() in
# the process's lifetime is created/destroyed on the exact same OS thread.
_DIALOG_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tk-dialog")


async def _run_dialog(show: Callable[[], str]) -> FileDialogOut:
    loop = asyncio.get_running_loop()
    chosen = await loop.run_in_executor(_DIALOG_EXECUTOR, show)
    return FileDialogOut(path=chosen or None)


def _configured_initial_dir(directory: str | None) -> str:
    """A Préférences-configured directory, only if it's actually set and still exists on disk --
    otherwise "" falls back to tkinter's own default (last-used directory)."""
    return directory if directory and Path(directory).is_dir() else ""


@app.get("/dialogs/open-image", response_model=FileDialogOut)
async def open_image_dialog_endpoint() -> FileDialogOut:
    # Defaults to Préférences > Général's configured photo-opening directory (2026-08-05).
    initial_dir = _configured_initial_dir(load_preferences(default_preferences_path()).open_image_directory)

    def show() -> str:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.askopenfilename(title="Ouvrir une image", filetypes=IMAGE_FILE_TYPES, initialdir=initial_dir)
        finally:
            root.destroy()

    return await _run_dialog(show)


@app.get("/dialogs/load-recipe", response_model=FileDialogOut)
async def load_recipe_dialog_endpoint() -> FileDialogOut:
    # Defaults to Préférences > Général's configured presets directory (2026-08-05), same as
    # save-recipe below.
    initial_dir = _configured_initial_dir(load_preferences(default_preferences_path()).presets_directory)

    def show() -> str:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.askopenfilename(
                title="Charger une recette",
                filetypes=[("Recette LumaFlow (JSON)", "*.json"), ("Tous les fichiers", "*.*")],
                initialdir=initial_dir,
            )
        finally:
            root.destroy()

    return await _run_dialog(show)


@app.get("/dialogs/save-recipe", response_model=FileDialogOut)
async def save_recipe_dialog_endpoint() -> FileDialogOut:
    # Defaults to Préférences > Général's configured presets directory (2026-08-05).
    initial_dir = _configured_initial_dir(load_preferences(default_preferences_path()).presets_directory)

    def show() -> str:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.asksaveasfilename(
                title="Enregistrer la recette sous",
                defaultextension=".json",
                filetypes=[("Recette LumaFlow (JSON)", "*.json"), ("Tous les fichiers", "*.*")],
                initialdir=initial_dir,
            )
        finally:
            root.destroy()

    return await _run_dialog(show)


@app.get("/dialogs/export-image", response_model=FileDialogOut)
async def export_image_dialog_endpoint() -> FileDialogOut:
    # Defaults to Préférences > Général's configured photo-export directory (2026-08-05).
    initial_dir = _configured_initial_dir(load_preferences(default_preferences_path()).export_image_directory)

    def show() -> str:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.asksaveasfilename(
                title="Exporter l'image vers",
                defaultextension=".png",
                filetypes=IMAGE_FILE_TYPES,
                initialdir=initial_dir,
            )
        finally:
            root.destroy()

    return await _run_dialog(show)


@app.get("/dialogs/select-presets-directory", response_model=FileDialogOut)
async def select_presets_directory_dialog_endpoint() -> FileDialogOut:
    def show() -> str:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.askdirectory(title="Choisir le dossier des presets")
        finally:
            root.destroy()

    return await _run_dialog(show)


@app.get("/dialogs/select-open-image-directory", response_model=FileDialogOut)
async def select_open_image_directory_dialog_endpoint() -> FileDialogOut:
    def show() -> str:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.askdirectory(title="Choisir le dossier d'ouverture des photos")
        finally:
            root.destroy()

    return await _run_dialog(show)


@app.get("/dialogs/select-export-image-directory", response_model=FileDialogOut)
async def select_export_image_directory_dialog_endpoint() -> FileDialogOut:
    def show() -> str:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.askdirectory(title="Choisir le dossier d'exportation des photos")
        finally:
            root.destroy()

    return await _run_dialog(show)


class VignetteStateOut(BaseModel):
    status: str
    detail: str = ""
    has_pixels: bool = False


class RowSpecOut(BaseModel):
    label: str
    short_description: str
    vignette_labels: list[str]
    selected_vignette_identifier: str | None
    vignette_states: dict[str, VignetteStateOut]
    has_zoom: bool = False


def _row_spec_out(row: RowSpec, row_index: int) -> RowSpecOut:
    return RowSpecOut(
        label=row.label,
        short_description=row.short_description,
        vignette_labels=list(row.vignette_labels),
        selected_vignette_identifier=row.selected_vignette_identifier,
        vignette_states={
            identifier: VignetteStateOut(
                status=state.status.value,
                detail=state.detail,
                has_pixels=state.pixels is not None,
            )
            for identifier, state in row.vignette_states.items()
        },
        has_zoom=row_has_zoom(row_index),
    )


class SessionOut(BaseModel):
    id: str


@app.post("/sessions", response_model=SessionOut)
def create_session_endpoint() -> SessionOut:
    session = create_session()
    _sessions[session.id] = session
    return SessionOut(id=session.id)


class SourceOut(BaseModel):
    filename: str
    width: int
    height: int
    image_format: str


class SessionInfoOut(BaseModel):
    id: str
    active_step_index: int
    source: SourceOut | None


@app.get("/sessions/{session_id}", response_model=SessionInfoOut)
def get_session_info_endpoint(session_id: str) -> SessionInfoOut:
    session = _get_session(session_id)
    source = None
    if session.image_session is not None:
        src = session.image_session.source
        source = SourceOut(
            filename=src.name, width=src.width, height=src.height, image_format=src.image_format,
        )
    return SessionInfoOut(id=session.id, active_step_index=session.active_step_index, source=source)


class OpenImageIn(BaseModel):
    path: str


@app.post("/sessions/{session_id}/open", response_model=list[RowSpecOut])
def open_image_endpoint(session_id: str, body: OpenImageIn) -> list[RowSpecOut]:
    session = _get_session(session_id)
    try:
        open_image(session, Path(body.path))
    except ImageIOError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_row_spec_out(row, index) for index, row in enumerate(refresh_workflow(session))]


@app.get("/sessions/{session_id}/workflow", response_model=list[RowSpecOut])
def get_workflow_endpoint(session_id: str) -> list[RowSpecOut]:
    session = _get_session(session_id)
    return [_row_spec_out(row, index) for index, row in enumerate(refresh_workflow(session))]


@app.get("/sessions/{session_id}/preview")
def get_preview_endpoint(session_id: str) -> Response:
    """The fully-applied image (every step's selected preset composed in
    order) -- what the status bar's thumbnail and the mockup's statusA.
    thumbFilter show. Distinct from /thumbnails/{step}/{identifier}, which is
    one specific vignette option, not the pipeline's current end result.
    Interactive-resolution (session.working_image-derived), not full
    resolution -- see render_full_resolution for that (export, future
    Zoom)."""
    session = _get_session(session_id)
    if session.image_session is None:
        raise HTTPException(status_code=400, detail="No image loaded in this session")
    pil_image = Image.fromarray(session.image_session.pixels, mode="RGB")
    buffer = io.BytesIO()
    pil_image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@app.post("/sessions/{session_id}/steps/{step_index}/activate", response_model=list[RowSpecOut])
def activate_step_endpoint(session_id: str, step_index: int, background_tasks: BackgroundTasks) -> list[RowSpecOut]:
    session = _get_session(session_id)
    try:
        rows = activate_step(session, step_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Warm the "Avant" render for this row in the background so it's already cached if/when the
    # user opens Zoom on it -- never blocks this response (PERF-ZOOM-RENDER-PLAN.md étape 4).
    background_tasks.add_task(precompute_row_before, session, step_index)
    return [_row_spec_out(row, index) for index, row in enumerate(rows)]


@app.post("/sessions/{session_id}/reset", response_model=list[RowSpecOut])
def reset_session_endpoint(session_id: str) -> list[RowSpecOut]:
    session = _get_session(session_id)
    try:
        rows = reset_session(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_row_spec_out(row, index) for index, row in enumerate(rows)]


class SelectVignetteIn(BaseModel):
    identifier: str


@app.post("/sessions/{session_id}/steps/{step_index}/select", response_model=list[RowSpecOut])
def select_vignette_endpoint(
    session_id: str, step_index: int, body: SelectVignetteIn, background_tasks: BackgroundTasks
) -> list[RowSpecOut]:
    session = _get_session(session_id)
    try:
        rows = select_vignette(session, step_index, body.identifier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Same rationale as activate_step_endpoint -- a vignette click also activates its row.
    background_tasks.add_task(precompute_row_before, session, step_index)
    return [_row_spec_out(row, index) for index, row in enumerate(rows)]


@app.get("/sessions/{session_id}/thumbnails/{step_index}/{identifier}")
def get_thumbnail_endpoint(session_id: str, step_index: int, identifier: str) -> Response:
    session = _get_session(session_id)
    row_states = session.vignette_states.get(step_index)
    if row_states is None:
        raise HTTPException(status_code=404, detail="Row not currently visible/computed")
    state = row_states.get(identifier)
    if state is None or state.status != VignetteStatus.READY or state.pixels is None:
        raise HTTPException(status_code=404, detail="Thumbnail not ready")
    pixels: numpy.ndarray = state.pixels
    pil_image = Image.fromarray(pixels, mode="RGB")
    buffer = io.BytesIO()
    pil_image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


# --- Zoom overlay (before/after split-compare + "Réglages manuels" sliders,
# per the reference mockup) -- the manual-adjustment sliders are
# only real for rows whose addon actually declares zoom_parameters (Film,
# for now: intensity + 20 grade-override sliders); every other row's
# ZoomStateOut.sliders is simply empty. ---


def _png_response(pixels: numpy.ndarray) -> Response:
    pil_image = Image.fromarray(pixels, mode="RGB")
    buffer = io.BytesIO()
    pil_image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


class ZoomSliderOut(BaseModel):
    identifier: str
    label: str
    minimum: float
    maximum: float
    step: float
    value: float
    default: float


class ZoomHueRangeOut(BaseModel):
    """One circular hue-selection control (kind="hue_range", feature 098) -- groups the two
    underlying scalar parameters f"{identifier}_hue_center" / f"{identifier}_feather" the same
    way a HueRing widget groups one center + one feather handle on a single ring."""

    identifier: str
    label: str
    hue_minimum: float
    hue_maximum: float
    hue_value: float
    hue_default: float
    feather_minimum: float
    feather_maximum: float
    feather_value: float
    feather_default: float


class ZoomOverlayOut(BaseModel):
    """One composition-guide entry from an addon's overlay_descriptions catalog (e.g. Framing's
    thirds/golden_section/... crop-frame guides). Purely a display aid -- geometry is computed
    client-side (lib/cropGuides.ts) from `kind` alone, never rendered server-side."""

    kind: str
    label: str
    default_active: bool


class ZoomStateOut(BaseModel):
    step_index: int
    identifier: str
    sliders: list[ZoomSliderOut]
    hue_ranges: list[ZoomHueRangeOut] = []
    overlays: list[ZoomOverlayOut] = []


def _build_zoom_state_fields(
    declarations: tuple[ZoomParameterDeclaration, ...],
    effective_values: dict[str, float],
    pure_default_values: dict[str, float],
) -> tuple[list[ZoomSliderOut], list[ZoomHueRangeOut], list[ZoomOverlayOut]]:
    """Shared serialization for a Zoom row's declared parameters into the wire format -- used both
    for the currently zoomed row (_zoom_state_out) and for an auxiliary row resolved independently
    of it (_auxiliary_zoom_state_out, e.g. Geometry/Framing read from within Film/Color Splash's
    own Zoom, feature: cross-row corrections)."""
    sliders: list[ZoomSliderOut] = []
    hue_ranges: list[ZoomHueRangeOut] = []
    overlays: list[ZoomOverlayOut] = []
    for declaration in declarations:
        constraints = declaration.constraints
        if declaration.kind == "numeric_slider":
            try:
                minimum = float(constraints["minimum"])
                maximum = float(constraints["maximum"])
                step_size = float(constraints["step"])
                generic_default = float(constraints["default"])
            except (KeyError, TypeError, ValueError):
                continue
            # `value` reflects what's actually in effect right now (an already-
            # confirmed override, or the selected look's own calibrated value);
            # `default` is the "Réinitialiser" target -- the look's TRUE
            # calibrated baseline, ignoring any override. Both fall back to the
            # generic declared default only when no addon resolver applies (e.g.
            # "neutral" selected, no look to seed from).
            value = effective_values.get(declaration.identifier, generic_default)
            default = pure_default_values.get(declaration.identifier, generic_default)
            sliders.append(
                ZoomSliderOut(
                    identifier=declaration.identifier, label=declaration.label,
                    minimum=minimum, maximum=maximum, step=step_size, value=value, default=default,
                )
            )
        elif declaration.kind == "hue_range":
            try:
                hue_minimum = float(constraints["hue_minimum"])
                hue_maximum = float(constraints["hue_maximum"])
                generic_hue_default = float(constraints["hue_default"])
                feather_minimum = float(constraints["feather_minimum"])
                feather_maximum = float(constraints["feather_maximum"])
                generic_feather_default = float(constraints["feather_default"])
            except (KeyError, TypeError, ValueError):
                continue
            # Same override-wins-else-calibrated convention as the numeric_slider branch above,
            # but each hue_range groups TWO atomic parameter keys (hue center + feather) instead
            # of one -- named by convention as f"{identifier}_hue_center"/f"{identifier}_feather"
            # (the addon contract's hue_range convention, feature 098).
            hue_key = f"{declaration.identifier}_hue_center"
            feather_key = f"{declaration.identifier}_feather"
            hue_ranges.append(
                ZoomHueRangeOut(
                    identifier=declaration.identifier, label=declaration.label,
                    hue_minimum=hue_minimum, hue_maximum=hue_maximum,
                    hue_value=effective_values.get(hue_key, generic_hue_default),
                    hue_default=pure_default_values.get(hue_key, generic_hue_default),
                    feather_minimum=feather_minimum, feather_maximum=feather_maximum,
                    feather_value=effective_values.get(feather_key, generic_feather_default),
                    feather_default=pure_default_values.get(feather_key, generic_feather_default),
                )
            )
        else:
            # Any other declared kind is a display-only composition guide (overlay_descriptions,
            # e.g. Framing's "thirds"/"golden_section"/...) -- not a slider, no value/default to
            # resolve, just catalog metadata for the frontend's guide-vignette selector.
            default_active = constraints.get("default_active")
            if not isinstance(default_active, bool):
                continue
            overlays.append(
                ZoomOverlayOut(kind=declaration.kind, label=declaration.label, default_active=default_active)
            )
    return sliders, hue_ranges, overlays


def _zoom_state_out(session: Session) -> ZoomStateOut:
    zoom = session.zoom
    sliders, hue_ranges, overlays = _build_zoom_state_fields(
        zoom_parameter_declarations(session), zoom_effective_values(session), zoom_pure_default_values(session)
    )
    return ZoomStateOut(
        step_index=zoom.step_index, identifier=zoom.identifier,
        sliders=sliders, hue_ranges=hue_ranges, overlays=overlays,
    )


class AuxiliaryZoomStateOut(BaseModel):
    """Same shape as ZoomStateOut, minus step_index/identifier (an auxiliary row isn't "the"
    zoomed row -- it's Geometry's or Framing's own state, read/written from within Film/Color
    Splash's Zoom, feature: cross-row corrections)."""

    row_identifier: str
    sliders: list[ZoomSliderOut]
    overlays: list[ZoomOverlayOut] = []


def _auxiliary_zoom_state_out(session: Session, row_identifier: str) -> AuxiliaryZoomStateOut:
    sliders, _hue_ranges, overlays = _build_zoom_state_fields(
        auxiliary_zoom_declarations(session, row_identifier),
        auxiliary_zoom_effective_values(session, row_identifier),
        auxiliary_zoom_pure_default_values(session, row_identifier),
    )
    return AuxiliaryZoomStateOut(row_identifier=row_identifier, sliders=sliders, overlays=overlays)


class OpenZoomIn(BaseModel):
    identifier: str


@app.post("/sessions/{session_id}/zoom/{step_index}/open", response_model=ZoomStateOut)
def open_zoom_endpoint(session_id: str, step_index: int, body: OpenZoomIn) -> ZoomStateOut:
    session = _get_session(session_id)
    try:
        open_zoom(session, step_index, body.identifier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _zoom_state_out(session)


@app.get("/sessions/{session_id}/zoom/before")
def get_zoom_before_endpoint(session_id: str) -> Response:
    session = _get_session(session_id)
    try:
        pixels = render_zoom_before(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _png_response(pixels)


@app.get("/sessions/{session_id}/zoom/after")
def get_zoom_after_endpoint(session_id: str) -> Response:
    session = _get_session(session_id)
    try:
        pixels = render_zoom_after(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _png_response(pixels)


class SetZoomParameterIn(BaseModel):
    identifier: str
    value: float
    # PERF-ZOOM-RENDER-PLAN.md étape 2: when given, renders a downscaled "after" pane instead of
    # full resolution -- the client sends this for the reduced-resolution preview fired while a
    # slider is actively being dragged, then follows up with a max_dimension-less call once
    # dragging settles (see ZoomOverlay.tsx's scheduleParameterUpdate).
    max_dimension: int | None = None


@app.post("/sessions/{session_id}/zoom/parameter")
def set_zoom_parameter_endpoint(session_id: str, body: SetZoomParameterIn) -> Response:
    """Writes one slider edit then re-renders the "after" pane -- full resolution by default, or
    downscaled if `max_dimension` is given (see SetZoomParameterIn). The client is responsible for
    debouncing this call while a slider is being dragged (see
    web/src/components/ZoomOverlay.tsx), since a full-resolution Film-look render costs several
    seconds on a large image."""
    session = _get_session(session_id)
    try:
        set_zoom_parameter(session, body.identifier, body.value)
        pixels = render_zoom_after(session, max_dimension=body.max_dimension)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _png_response(pixels)


class ZoomParameterUpdate(BaseModel):
    identifier: str
    value: float


class SetZoomParametersIn(BaseModel):
    updates: list[ZoomParameterUpdate]
    # Same meaning as SetZoomParameterIn.max_dimension (PERF-ZOOM-RENDER-PLAN.md étape 2).
    max_dimension: int | None = None


@app.post("/sessions/{session_id}/zoom/parameters")
def set_zoom_parameters_endpoint(session_id: str, body: SetZoomParametersIn) -> Response:
    """Batched sibling of /zoom/parameter -- writes N slider edits then re-renders the "after"
    pane exactly once, regardless of len(body.updates). Required for "Réinitialiser" and
    polygon-vertex commits, which would otherwise fire one full-resolution render per value
    through the singular endpoint (unusable at Light v2's ~137-parameter scale)."""
    session = _get_session(session_id)
    try:
        set_zoom_parameters(session, [(u.identifier, u.value) for u in body.updates])
        pixels = render_zoom_after(session, max_dimension=body.max_dimension)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _png_response(pixels)


@app.get("/sessions/{session_id}/zoom/auxiliary/{row_identifier}", response_model=AuxiliaryZoomStateOut)
def get_auxiliary_zoom_state_endpoint(session_id: str, row_identifier: str) -> AuxiliaryZoomStateOut:
    """Geometry's or Framing's own declared parameters + current effective values, resolved
    independently of whichever row is actually zoomed -- lets Film/Color Splash's Zoom seed its
    embedded Geometry/Cadrage stage (corner handles + rotation dial, or crop frame + guides)
    without opening a second Zoom session (feature: cross-row corrections)."""
    session = _get_session(session_id)
    if session.zoom is None:
        raise HTTPException(status_code=400, detail="No Zoom session open")
    return _auxiliary_zoom_state_out(session, row_identifier)


@app.get("/sessions/{session_id}/zoom/auxiliary/{row_identifier}/before")
def get_auxiliary_zoom_before_endpoint(session_id: str, row_identifier: str) -> Response:
    """Full-resolution render up to (excluding) `row_identifier`'s own step -- the background
    photo for the embedded Geometry/Cadrage stage, same "before" convention as /zoom/before uses
    for a row zoomed directly."""
    session = _get_session(session_id)
    try:
        pixels = render_auxiliary_before(session, row_identifier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _png_response(pixels)


@app.post("/sessions/{session_id}/zoom/auxiliary/{row_identifier}/parameter")
def set_auxiliary_zoom_parameter_endpoint(session_id: str, row_identifier: str, body: SetZoomParameterIn) -> Response:
    """Writes one edit into Geometry's or Framing's own step while a Zoom session is open on a
    different row (Film/Color Splash). Deliberately does NOT re-render the combined "after" pane
    (unlike /zoom/parameter) -- the combined preview is only recomputed when the "Appliquer"
    button explicitly re-fetches /zoom/after, same convention GeometryCanvas/CropCanvas already
    use for their own corner/crop drags. Returns 204 rather than a rendered blob to make that
    explicit."""
    session = _get_session(session_id)
    try:
        set_auxiliary_zoom_parameter(session, row_identifier, body.identifier, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)


@app.post("/sessions/{session_id}/zoom/confirm", response_model=list[RowSpecOut])
def confirm_zoom_endpoint(session_id: str) -> list[RowSpecOut]:
    session = _get_session(session_id)
    try:
        rows = confirm_zoom(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_row_spec_out(row, index) for index, row in enumerate(rows)]


@app.post("/sessions/{session_id}/zoom/cancel", response_model=list[RowSpecOut])
def cancel_zoom_endpoint(session_id: str) -> list[RowSpecOut]:
    session = _get_session(session_id)
    try:
        rows = cancel_zoom(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_row_spec_out(row, index) for index, row in enumerate(rows)]


class ExportImageIn(BaseModel):
    dest_path: str
    image_format: str
    jpeg_quality: int | None = None
    force: bool = False


class ExportImageOut(BaseModel):
    ok: bool


@app.post("/sessions/{session_id}/export", response_model=ExportImageOut)
def export_image_endpoint(session_id: str, body: ExportImageIn) -> ExportImageOut:
    session = _get_session(session_id)
    if session.image_session is None:
        raise HTTPException(status_code=400, detail="No image loaded in this session")
    dest_path = Path(body.dest_path)
    if dest_path.exists() and not body.force:
        raise HTTPException(
            status_code=409,
            detail="Destination already exists; retry with force=true to overwrite",
        )
    # A fresh full-resolution render, not session.image_session.pixels --
    # that field is now the (downscaled) interactive preview, see
    # render_full_resolution's docstring (correctif de performance,
    # 2026-07-21).
    try:
        pixels = render_full_resolution(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    quality, subsampling = resolve_jpeg_export_params(
        body.jpeg_quality, session.image_session.source
    )
    # Feature 050 (FR-004/US2): export_image can raise ImageIOError (invalid destination path,
    # permission denied, disk full) same as load_image's own errors already caught above via
    # render_full_resolution -- this endpoint never caught it at all, so any export I/O failure
    # crashed as an unhandled 500 "Internal Server Error" instead of a clean 400, exactly the raw/
    # opaque failure this feature exists to eliminate for one of its three named common errors.
    try:
        export_image(
            pixels,
            dest_path,
            body.image_format,
            jpeg_quality=quality,
            jpeg_subsampling=subsampling,
        )
    except ImageIOError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ExportImageOut(ok=True)


# --- Preferences -- process-wide (not per-session), mirrors the desktop
# app's single preferences.json under the OS config dir. ---


class PreferencesOut(BaseModel):
    menu_position: str
    menu_collapsed: bool
    row_spacing_px: int
    vignette_margin_px: int
    attenuated_opacity_percent: int
    row_horizontal_margin_px: int
    zoom_min_percent: int
    zoom_max_percent: int
    export_jpeg_quality: int
    guide_limit_color: str
    guide_overlay_color: str
    accent_color: str
    presets_directory: str | None = None
    open_image_directory: str | None = None
    export_image_directory: str | None = None
    workflow_config_source_path: str | None = None


def _preferences_out(prefs: UIPreferences) -> PreferencesOut:
    return PreferencesOut(
        menu_position=prefs.menu_position,
        menu_collapsed=prefs.menu_collapsed,
        row_spacing_px=prefs.row_spacing_px,
        vignette_margin_px=prefs.vignette_margin_px,
        attenuated_opacity_percent=prefs.attenuated_opacity_percent,
        row_horizontal_margin_px=prefs.row_horizontal_margin_px,
        zoom_min_percent=prefs.zoom_min_percent,
        zoom_max_percent=prefs.zoom_max_percent,
        export_jpeg_quality=prefs.export_jpeg_quality,
        guide_limit_color=prefs.guide_limit_color,
        guide_overlay_color=prefs.guide_overlay_color,
        accent_color=prefs.accent_color,
        presets_directory=prefs.presets_directory,
        open_image_directory=prefs.open_image_directory,
        export_image_directory=prefs.export_image_directory,
        workflow_config_source_path=prefs.workflow_config_source_path,
    )


@app.get("/preferences", response_model=PreferencesOut)
def get_preferences_endpoint() -> PreferencesOut:
    return _preferences_out(load_preferences(default_preferences_path()))


@app.put("/preferences", response_model=PreferencesOut)
def put_preferences_endpoint(body: PreferencesOut) -> PreferencesOut:
    prefs = UIPreferences(
        menu_position=body.menu_position,
        menu_collapsed=body.menu_collapsed,
        row_spacing_px=body.row_spacing_px,
        vignette_margin_px=body.vignette_margin_px,
        attenuated_opacity_percent=body.attenuated_opacity_percent,
        row_horizontal_margin_px=body.row_horizontal_margin_px,
        zoom_min_percent=body.zoom_min_percent,
        zoom_max_percent=body.zoom_max_percent,
        export_jpeg_quality=body.export_jpeg_quality,
        guide_limit_color=body.guide_limit_color,
        guide_overlay_color=body.guide_overlay_color,
        accent_color=body.accent_color,
        presets_directory=body.presets_directory,
        open_image_directory=body.open_image_directory,
        export_image_directory=body.export_image_directory,
        workflow_config_source_path=body.workflow_config_source_path,
    )
    save_preferences(prefs, default_preferences_path())
    return _preferences_out(load_preferences(default_preferences_path()))


class PresetEntryOut(BaseModel):
    name: str
    path: str


class PresetsListOut(BaseModel):
    presets: list[PresetEntryOut]


@app.get("/presets", response_model=PresetsListOut)
def list_presets_endpoint() -> PresetsListOut:
    """Presets shown in the header combobox (2026-08-05) -- scans
    `presets_directory` (Préférences > Général) for `.json` recipe files,
    non-recursively, sorted alphabetically (casefold, no locale-aware FR
    collation). Missing/unset/unreadable directory degrades silently to an
    empty list rather than an error -- the combobox just shows "Nouveau"."""
    prefs = load_preferences(default_preferences_path())
    if not prefs.presets_directory:
        return PresetsListOut(presets=[])
    directory = Path(prefs.presets_directory)
    if not directory.is_dir():
        return PresetsListOut(presets=[])
    entries = sorted(
        (p for p in directory.glob("*.json") if p.is_file()),
        key=lambda p: p.stem.casefold(),
    )
    return PresetsListOut(presets=[PresetEntryOut(name=p.stem, path=str(p)) for p in entries])


# --- Recipes -- session-scoped (a recipe is built from / applied onto the
# session's current pipeline + image), mirrors app.py's save_recipe/
# load_recipe menu actions minus the QFileDialog/QMessageBox prompts. ---


class SaveRecipeIn(BaseModel):
    dest_path: str
    force: bool = False


class SaveRecipeOut(BaseModel):
    ok: bool


@app.post("/sessions/{session_id}/recipe/save", response_model=SaveRecipeOut)
def save_recipe_endpoint(session_id: str, body: SaveRecipeIn) -> SaveRecipeOut:
    session = _get_session(session_id)
    try:
        recipe = build_recipe(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        validate_session_completeness(recipe.steps)
    except RecipeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    dest_path = Path(body.dest_path)
    if dest_path.exists() and not body.force:
        raise HTTPException(
            status_code=409,
            detail="Destination already exists; retry with force=true to overwrite",
        )
    try:
        save_recipe(recipe, dest_path)
    except RecipeIOError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SaveRecipeOut(ok=True)


class LoadRecipeIn(BaseModel):
    path: str


class DimensionWarningStepOut(BaseModel):
    step_identifier: str
    status: str


class DimensionWarningOut(BaseModel):
    incompatible: bool
    step_identifiers: list[str]
    steps: list[DimensionWarningStepOut]


class ParameterCorrectionOut(BaseModel):
    step_identifier: str
    parameter: str
    requested: float
    applied: float


class DisabledVignetteCorrectionOut(BaseModel):
    step_identifier: str
    requested_identifier: str


class LoadRecipeOut(BaseModel):
    rows: list[RowSpecOut]
    dimension_warning: DimensionWarningOut | None
    # Always present, empty by default -- so the frontend
    # never has to distinguish "field absent" from "no correction happened".
    parameter_corrections: list[ParameterCorrectionOut]
    # Same convention (Préférences > Workflow, 2026-08-06): always present, empty by default.
    disabled_vignette_corrections: list[DisabledVignetteCorrectionOut]


# Structured recipe-load error body (feature 048): each of
# the four blocking categories gets a fixed, non-technical `message` distinct from the other three
# (SC-001) -- replacing the flat `str(exc)` this used to be, which either leaked a raw
# json.JSONDecodeError parser string or a generic constant that threw away detail
# already computed elsewhere.
def _blocking_recipe_error_detail(exc: RecipeValidationError | RecipeIOError) -> dict[str, object]:
    if isinstance(exc, RecipeValidationError) and exc.reason == "unrecognized_schema_version":
        return {
            "category": "unsupported_schema_version",
            "message": "Cette recette utilise une version de schéma non supportée.",
            "details": {"schema_version": exc.detail},
        }
    # Every other RecipeValidationError reason (invalid_json, missing_field, ...) and every
    # RecipeIOError (missing file, permission denied, disk full, invalid path) collapse into one
    # clear category -- the raw parser/OS text is never the primary message, only carried as
    # `details.reason` for secondary diagnostics.
    reason = exc.reason if isinstance(exc, RecipeValidationError) else exc.category.value
    return {
        "category": "unreadable_file",
        "message": "Ce fichier de recette est illisible ou corrompu.",
        "details": {"reason": reason},
    }


@app.post("/sessions/{session_id}/recipe/load", response_model=LoadRecipeOut)
def load_recipe_endpoint(session_id: str, body: LoadRecipeIn) -> LoadRecipeOut:
    session = _get_session(session_id)
    try:
        recipe = load_recipe(Path(body.path))
    except (RecipeValidationError, RecipeIOError) as exc:
        raise HTTPException(status_code=400, detail=_blocking_recipe_error_detail(exc)) from exc
    try:
        outcome = apply_recipe(session, recipe)
    except RecipeAddonsMissing as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "category": "missing_addon",
                "message": (
                    "Cette recette référence un ou plusieurs addons introuvables dans la "
                    "configuration actuelle."
                ),
                "details": {"missing_addon_ids": exc.report.missing_addon_ids},
            },
        ) from exc
    except RecipeApplicationFailed as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "category": "application_error",
                "message": "Cette recette n'a pas pu être appliquée à l'image active.",
                "details": {"step_identifiers": exc.step_identifiers, "reasons": exc.reasons},
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dimension_warning = (
        DimensionWarningOut(
            incompatible=outcome.dimension_warning.incompatible,
            step_identifiers=outcome.dimension_warning.step_identifiers,
            steps=[
                DimensionWarningStepOut(step_identifier=step.step_identifier, status=step.status)
                for step in outcome.dimension_warning.steps
            ],
        )
        if outcome.dimension_warning is not None
        else None
    )
    return LoadRecipeOut(
        rows=[_row_spec_out(row, index) for index, row in enumerate(outcome.rows)],
        dimension_warning=dimension_warning,
        parameter_corrections=[
            ParameterCorrectionOut(
                step_identifier=correction.step_identifier,
                parameter=correction.parameter,
                requested=correction.requested,
                applied=correction.applied,
            )
            for correction in outcome.parameter_corrections
        ],
        disabled_vignette_corrections=[
            DisabledVignetteCorrectionOut(
                step_identifier=correction.step_identifier,
                requested_identifier=correction.requested_identifier,
            )
            for correction in outcome.disabled_vignette_corrections
        ],
    )


# --- Workflow config -- process-wide (not per-session), Préférences > Workflow (2026-08-06).
# Row structure (identifier/label/category/addon_identifiers/short_description) is read-only from
# this API's perspective -- only each row's vignette membership/order is ever written back. See
# session.py's reload_workflow_config docstring for why this invariant is what makes a live reload
# safe for already-open sessions without any per-session snapshot. ---


class WorkflowVignetteIO(BaseModel):
    identifier: str
    label: str
    enabled: bool


class WorkflowRowIO(BaseModel):
    identifier: str | None = None
    label: str | None = None
    category: str | None = None
    short_description: str | None = None
    # The FULL catalog this row's addon(s) can show, each flagged enabled/disabled -- one unified,
    # reorderable list (not a curated list + a separate "available" list), per the user's explicit
    # requirement that every vignette be visible with its own flag during administration. Order:
    # enabled entries first (in their configured/applied order), then disabled entries appended.
    vignettes: list[WorkflowVignetteIO] = []


class WorkflowConfigOut(BaseModel):
    rows: list[WorkflowRowIO]
    # Display-only: which file this payload reflects (the default config on GET/after PUT, the
    # imported file's own path on import) -- shown in Préférences > Workflow next to Ouvrir/Exporter
    # so the user knows what's currently loaded. PUT never reads this back (it always (re)writes to
    # the default path); defaulted so a PUT body built without it still validates.
    source_path: str = ""


def _workflow_row_io(row: WorkflowRow) -> WorkflowRowIO:
    enabled_identifiers = list(row.thumbnail_presets)
    enabled_set = set(enabled_identifiers)
    catalog = catalog_thumbnail_presets(row, ADDON_INDEX)
    catalog_labels = dict(catalog)
    vignettes = [
        WorkflowVignetteIO(identifier=identifier, label=catalog_labels.get(identifier, identifier), enabled=True)
        for identifier in enabled_identifiers
    ]
    vignettes.extend(
        WorkflowVignetteIO(identifier=identifier, label=label, enabled=False)
        for identifier, label in catalog
        if identifier not in enabled_set
    )
    return WorkflowRowIO(
        identifier=row.identifier,
        label=row.label,
        category=row.category,
        short_description=row.short_description,
        vignettes=vignettes,
    )


def _workflow_config_out(config: WorkflowConfig, source_path: str) -> WorkflowConfigOut:
    return WorkflowConfigOut(rows=[_workflow_row_io(row) for row in config.rows], source_path=source_path)


def _validate_workflow_row_identity(rows: list[WorkflowRowIO], live_config: WorkflowConfig) -> None:
    """Rows themselves are structurally fixed (2026-08-06 product decision) -- only vignette
    membership/order is ever editable via Préférences > Workflow. Enforced here (not just by the
    frontend leaving identifier/label/category read-only) so an imported/hand-crafted JSON with a
    different row set can never reach reload_workflow_config -- that's the invariant the "no
    per-session snapshot needed" design in session.py depends on."""
    submitted = [row.identifier for row in rows]
    expected = [row.identifier for row in live_config.rows]
    if submitted != expected:
        raise HTTPException(
            status_code=400,
            detail={
                "category": "row_set_mismatch",
                "message": "L'ensemble ou l'ordre des lignes ne correspond pas à la configuration actuelle.",
                "details": {"submitted": submitted, "expected": expected},
            },
        )


def _apply_workflow_row_io(rows: list[WorkflowRowIO], live_config: WorkflowConfig) -> WorkflowConfig:
    """Reconstructs a full WorkflowConfig for writing: identifier/label/category/
    addon_identifiers/short_description always come from the matching LIVE structural row (safe --
    _validate_workflow_row_identity already guarantees a 1:1, same-order identifier match); only a
    row's enabled vignette set/order (`vignettes`) is taken from the submitted payload."""
    live_by_identifier = {row.identifier: row for row in live_config.rows}
    new_rows = []
    for row_io in rows:
        live_row = live_by_identifier[row_io.identifier]
        new_rows.append(
            WorkflowRow(
                category=live_row.category,
                addon_identifiers=live_row.addon_identifiers,
                thumbnail_presets=tuple(v.identifier for v in row_io.vignettes if v.enabled),
                identifier=live_row.identifier,
                label=live_row.label,
                short_description=live_row.short_description,
            )
        )
    return WorkflowConfig(rows=tuple(new_rows))


@app.get("/workflow-config", response_model=WorkflowConfigOut)
def get_workflow_config_endpoint() -> WorkflowConfigOut:
    return _workflow_config_out(session_module.WORKFLOW_CONFIG, session_module.WORKFLOW_CONFIG_SOURCE_PATH)


@app.put("/workflow-config", response_model=WorkflowConfigOut)
def put_workflow_config_endpoint(body: WorkflowConfigOut) -> WorkflowConfigOut:
    """Applies the submitted rows to the LIVE, in-process workflow config immediately -- an
    already-open session's filmstrip reflects it right away, via reload_workflow_config -- but
    NEVER writes anything to disk. Bug report (2026-08-07, user's explicit and repeated
    instruction): Valider was persisting to a workflow config FILE on every click (first always the
    canonical default, then -- after an earlier, now-reverted fix -- whichever file was last
    opened), with no way to opt out. Only "Ouvrir" (a read) and "Exporter" (an explicit, user-
    chosen write, POST /workflow-config/export below) may ever touch a workflow config file on
    disk -- the user decides if/when/where to persist, exactly like every other app that separates
    "apply now" from "save". Valider is a pure in-memory apply, same as it already is for every
    other Préférences field that isn't itself a dedicated "write this file" action."""
    live_config = session_module.WORKFLOW_CONFIG
    _validate_workflow_row_identity(body.rows, live_config)
    new_config = _apply_workflow_row_io(body.rows, live_config)
    reload_workflow_config(new_config, body.source_path or str(default_workflow_config_path()))
    return _workflow_config_out(new_config, session_module.WORKFLOW_CONFIG_SOURCE_PATH)


@app.get("/dialogs/open-workflow-config", response_model=FileDialogOut)
async def open_workflow_config_dialog_endpoint() -> FileDialogOut:
    initial_dir = str(default_workflow_config_path().parent)

    def show() -> str:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.askopenfilename(
                title="Ouvrir une configuration de workflow",
                filetypes=[("Configuration workflow (JSON)", "*.json"), ("Tous les fichiers", "*.*")],
                initialdir=initial_dir,
            )
        finally:
            root.destroy()

    return await _run_dialog(show)


@app.get("/dialogs/export-workflow-config", response_model=FileDialogOut)
async def export_workflow_config_dialog_endpoint() -> FileDialogOut:
    initial_dir = str(default_workflow_config_path().parent)

    def show() -> str:
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.asksaveasfilename(
                title="Exporter la configuration de workflow sous",
                defaultextension=".json",
                filetypes=[("Configuration workflow (JSON)", "*.json"), ("Tous les fichiers", "*.*")],
                initialdir=initial_dir,
            )
        finally:
            root.destroy()

    return await _run_dialog(show)


class WorkflowConfigImportIn(BaseModel):
    path: str


@app.post("/workflow-config/import", response_model=WorkflowConfigOut)
def import_workflow_config_endpoint(body: WorkflowConfigImportIn) -> WorkflowConfigOut:
    try:
        imported = load_workflow_config(Path(body.path))
    except WorkflowConfigIOError as exc:
        raise HTTPException(
            status_code=400, detail={"category": exc.category.value, "detail": exc.detail}
        ) from exc
    except WorkflowConfigValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"category": "invalid_config", "reason": exc.reason, "detail": exc.detail},
        ) from exc
    imported_out = _workflow_config_out(imported, body.path)
    # A draft is only useful once it's known to be applicable -- reject here (before it ever
    # reaches the Préférences UI's draft state) rather than only at Valider time.
    _validate_workflow_row_identity(imported_out.rows, session_module.WORKFLOW_CONFIG)
    return imported_out  # draft only -- no persist, no reload


class WorkflowConfigExportIn(BaseModel):
    path: str
    rows: list[WorkflowRowIO]


class WorkflowConfigSaveOut(BaseModel):
    ok: bool


@app.post("/workflow-config/export", response_model=WorkflowConfigSaveOut)
def export_workflow_config_endpoint(body: WorkflowConfigExportIn) -> WorkflowConfigSaveOut:
    live_config = session_module.WORKFLOW_CONFIG
    _validate_workflow_row_identity(body.rows, live_config)
    config = _apply_workflow_row_io(body.rows, live_config)
    try:
        save_workflow_config(config, Path(body.path))
    except WorkflowConfigIOError as exc:
        raise HTTPException(
            status_code=400, detail={"category": exc.category.value, "detail": exc.detail}
        ) from exc
    return WorkflowConfigSaveOut(ok=True)


# Serve the built React frontend from this same process/port -- Phase 3 of the
# migration plan (2026-07-23): `lumaflow` now launches a single self-contained
# web app instead of API + a separate Vite dev server. Mounted LAST and only
# when the build exists, so it never shadows an API route above, and so the
# test suite (which never runs `npm run build`) sees the exact same app it
# always has -- no mount, no behavior change, no crash on a missing directory
# (StaticFiles raises at construction time if its directory doesn't exist).
_WEB_DIST_DIR = Path(__file__).resolve().parents[2] / "web" / "dist"
if _WEB_DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_WEB_DIST_DIR, html=True), name="frontend")
