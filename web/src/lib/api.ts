// LumaFlow v1.0 (2026-08-07)
// Client HTTP typé pour l'API FastAPI (sessions, workflow, zoom, préférences, dialogues natifs,
// recettes) : chaque fonction correspond à un endpoint de lumaflow/api/app.py.

/* Mirrors the Pydantic response models field-for-field so a shape mismatch
surfaces as a TypeScript error here rather than silently at render time. */

// Only Vite's dev server (:5173) needs an absolute cross-origin URL to reach the API (:8000) --
// in production the built frontend is served BY that same FastAPI process on the same origin, so
// a relative (same-origin) URL is used instead. A hardcoded absolute "http://127.0.0.1:8000" here
// used to break every fetch whenever the page was loaded as "http://localhost:8000" instead (very
// easy to do via browser history/autocomplete) -- same machine, same port, but a different origin
// as far as the browser's CORS enforcement is concerned, which the backend's CORS allowlist
// (lumaflow/api/app.py) never covered for :8000 in the first place. Relative URLs sidestep the
// whole cross-origin question: requests always target whatever origin the page itself was loaded
// from, matching by construction.
const BASE_URL = import.meta.env.DEV ? "http://127.0.0.1:8000" : "";

/** A structured error body from ANY endpoint (i18n phase 4, 2026-09-03) -- generalizes the
recipe-load shape above (feature 048) to image open/export (ImageIOError.category), batch
validation (BatchValidationError.code) and the destination-exists conflict. `category` is always
a stable machine-readable string; `code`/`batch_index`/other fields are category-specific extras.
`message` is the backend's own French text, used as errorMessages.ts's repli when the active
locale's catalog does not recognize `category` (D3's addon-label pattern, applied to errors). */
export type StructuredErrorDetail = {
  category: string;
  message: string;
  code?: string;
  batch_index?: number | null;
  details?: Record<string, unknown>;
};

export class ApiError extends Error {
  status: number;
  category?: string;
  code?: string;
  details?: Record<string, unknown>;
  constructor(status: number, detail: string | StructuredErrorDetail) {
    super(typeof detail === "string" ? detail : detail.message);
    this.status = status;
    if (typeof detail !== "string") {
      this.category = detail.category;
      this.code = detail.code;
      this.details = detail.details ?? (detail.batch_index !== undefined ? { batch_index: detail.batch_index } : undefined);
    }
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    const detail: string | StructuredErrorDetail = body.detail ?? response.statusText;
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export type VignetteState = {
  status: "pending" | "ready" | "error";
  detail: string;
  has_pixels: boolean;
};

export type RowSpec = {
  label: string;
  /** config_workflow.json's stable row identifier ("film", "bleach_bypass", "color_splash"...).
  Added 2026-09-03 (i18n phase 1) -- every per-row behaviour keys off THIS, never off `label`,
  which is a display string and becomes locale-dependent. */
  identifier: string;
  short_description: string;
  vignette_labels: string[];
  selected_vignette_identifier: string | null;
  vignette_states: Record<string, VignetteState>;
  has_zoom: boolean;
};

export type SourceInfo = {
  filename: string;
  width: number;
  height: number;
  image_format: string;
};

export type SessionInfo = {
  id: string;
  active_step_index: number;
  source: SourceInfo | null;
};

export type Preferences = {
  menu_position: "left" | "top";
  menu_collapsed: boolean;
  row_spacing_px: number;
  vignette_margin_px: number;
  attenuated_opacity_percent: number;
  row_horizontal_margin_px: number;
  zoom_min_percent: number;
  zoom_max_percent: number;
  export_jpeg_quality: number;
  guide_limit_color: string;
  guide_overlay_color: string;
  accent_color: string;
  /** Langue de l'IHM (i18n phase 6, 2026-09-03) : "fr" | "en". Typée `string` et non `Locale`
  parce que c'est ce que le serveur renvoie -- `setLocale` valide et retombe sur le français pour
  toute valeur inconnue, plutôt que de faire échouer le typage sur un fichier écrit par une
  version ultérieure. */
  ui_language: string;
  presets_directory: string | null;
  open_image_directory: string | null;
  export_image_directory: string | null;
  /** Which workflow config file is currently "loaded" (default path, or a file opened via
  Préférences > Workflow's "Ouvrir…") -- round-tripped through this object purely so PUT
  /preferences persists it (survives an app restart); PreferencesDialog is the only place that
  actually changes it, by mirroring WorkflowConfigData.source_path here right before Valider. */
  workflow_config_source_path: string | null;
};

export function createSession(): Promise<{ id: string }> {
  return request("/sessions", { method: "POST" });
}

/** Pops a real native OS "Open" dialog (server-side, via tkinter -- see
lumaflow/api/app.py) filtered to image files. Returns null if the user
cancelled. This is a strictly local app (browser + API on the same
machine), so a native dialog on the server is honestly "native" -- a
browser <input type="file"> can never expose an absolute filesystem path,
which /sessions/{id}/open needs. */
export function openImageDialog(): Promise<{ path: string | null }> {
  return request("/dialogs/open-image");
}

/** Pops a real native OS "Save As" dialog (server-side, via tkinter -- see
lumaflow/api/app.py), same rationale as openImageDialog above. Returns null
if the user cancelled. */
export function saveRecipeDialog(): Promise<{ path: string | null }> {
  return request("/dialogs/save-recipe");
}

/** Same pattern, filtered to image files -- backs the "Exporter" button. */
export function exportImageDialog(): Promise<{ path: string | null }> {
  return request("/dialogs/export-image");
}

/** Same pattern, an "Open" dialog filtered to recipe JSON files -- backs the
"Ouvrir" (recipe) entry point. */
export function loadRecipeDialog(): Promise<{ path: string | null }> {
  return request("/dialogs/load-recipe");
}

/** Same pattern, a folder picker (tkinter's askdirectory, no file filter) -- backs
Préférences > Général's "Parcourir…" button for the presets directory. */
export function selectPresetsDirectoryDialog(): Promise<{ path: string | null }> {
  return request("/dialogs/select-presets-directory");
}

/** Same pattern, for Préférences > Général's photo-opening/export directory rows. */
export function selectOpenImageDirectoryDialog(): Promise<{ path: string | null }> {
  return request("/dialogs/select-open-image-directory");
}

export function selectExportImageDirectoryDialog(): Promise<{ path: string | null }> {
  return request("/dialogs/select-export-image-directory");
}

export function getSessionInfo(sessionId: string): Promise<SessionInfo> {
  return request(`/sessions/${sessionId}`);
}

export function openImage(sessionId: string, path: string): Promise<RowSpec[]> {
  return request(`/sessions/${sessionId}/open`, {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export function getWorkflow(sessionId: string): Promise<RowSpec[]> {
  return request(`/sessions/${sessionId}/workflow`);
}

export function activateStep(sessionId: string, stepIndex: number): Promise<RowSpec[]> {
  return request(`/sessions/${sessionId}/steps/${stepIndex}/activate`, { method: "POST" });
}

export function selectVignette(sessionId: string, stepIndex: number, identifier: string): Promise<RowSpec[]> {
  return request(`/sessions/${sessionId}/steps/${stepIndex}/select`, {
    method: "POST",
    body: JSON.stringify({ identifier }),
  });
}

export function thumbnailUrl(sessionId: string, stepIndex: number, identifier: string): string {
  return `${BASE_URL}/sessions/${sessionId}/thumbnails/${stepIndex}/${encodeURIComponent(identifier)}`;
}

export function previewUrl(sessionId: string): string {
  return `${BASE_URL}/sessions/${sessionId}/preview`;
}

export function exportImage(
  sessionId: string,
  destPath: string,
  imageFormat: string,
  options?: { jpegQuality?: number; force?: boolean },
): Promise<{ ok: boolean }> {
  return request(`/sessions/${sessionId}/export`, {
    method: "POST",
    body: JSON.stringify({
      dest_path: destPath,
      image_format: imageFormat,
      jpeg_quality: options?.jpegQuality ?? null,
      force: options?.force ?? false,
    }),
  });
}

export function getPreferences(): Promise<Preferences> {
  return request("/preferences");
}

export function putPreferences(prefs: Preferences): Promise<Preferences> {
  return request("/preferences", { method: "PUT", body: JSON.stringify(prefs) });
}

/** Header preset combobox (2026-08-05): presets found in Préférences > Général's configured
`presets_directory`, sorted alphabetically -- empty when unset/missing, never an error. */
export type PresetEntry = { name: string; path: string };

export async function listPresets(): Promise<PresetEntry[]> {
  const result = await request<{ presets: PresetEntry[] }>("/presets");
  return result.presets;
}

/** Clears every row's preset selection back to neutral without reloading the image -- the
combobox's "Nouveau" entry. */
export function resetSession(sessionId: string): Promise<RowSpec[]> {
  return request(`/sessions/${sessionId}/reset`, { method: "POST" });
}

export function saveRecipe(sessionId: string, destPath: string, force = false): Promise<{ ok: boolean }> {
  return request(`/sessions/${sessionId}/recipe/save`, {
    method: "POST",
    body: JSON.stringify({ dest_path: destPath, force }),
  });
}

export type ParameterCorrection = {
  step_identifier: string;
  parameter: string;
  requested: number;
  applied: number;
};

/* Préférences > Workflow (2026-08-06): a recipe step whose chosen vignette is no longer enabled
for its row -- the backend substitutes that row's neutral vignette instead of ever applying a
disabled vignette's rendering (lumaflow/api/session.py's _is_vignette_enabled). */
export type DisabledVignetteCorrection = {
  step_identifier: string;
  requested_identifier: string;
};

export type LoadRecipeResult = {
  rows: RowSpec[];
  parameter_corrections: ParameterCorrection[];
  disabled_vignette_corrections: DisabledVignetteCorrection[];
};

export function loadRecipe(sessionId: string, path: string): Promise<LoadRecipeResult> {
  return request(`/sessions/${sessionId}/recipe/load`, {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

/* Zoom overlay (before/after split-compare + "Réglages manuels" sliders) --
mirrors lumaflow/api/app.py's /sessions/{id}/zoom/* endpoints. Only rows
whose addon actually declares zoom parameters (RowSpec.has_zoom) return a
non-empty `sliders`/`hue_ranges` list -- ZoomOverlay renders an empty panel
otherwise. */

export type ZoomSlider = {
  identifier: string;
  label: string;
  minimum: number;
  maximum: number;
  step: number;
  value: number;
  default: number;
};

/** A circular hue-selection control (kind="hue_range", feature 046) -- groups a hue center and
a feather/adoucissement into one HueRing handle instead of two independent sliders, since hue is
cyclic (see HueRing.tsx). */
export type ZoomHueRange = {
  identifier: string;
  label: string;
  hue_minimum: number;
  hue_maximum: number;
  hue_value: number;
  hue_default: number;
  feather_minimum: number;
  feather_maximum: number;
  feather_value: number;
  feather_default: number;
};

/** One composition-guide entry from an addon's overlay_descriptions catalog (e.g. Framing's
thirds/golden_section/... crop-frame guides). Purely a display aid -- `kind` selects a pure
geometry function in lib/cropGuides.ts, no backend round-trip involved. */
export type ZoomOverlay = {
  kind: string;
  label: string;
  default_active: boolean;
};

export type ZoomState = {
  step_index: number;
  identifier: string;
  sliders: ZoomSlider[];
  hue_ranges: ZoomHueRange[];
  overlays: ZoomOverlay[];
};

export function openZoom(sessionId: string, stepIndex: number, identifier: string): Promise<ZoomState> {
  return request(`/sessions/${sessionId}/zoom/${stepIndex}/open`, {
    method: "POST",
    body: JSON.stringify({ identifier }),
  });
}

export function zoomBeforeUrl(sessionId: string): string {
  return `${BASE_URL}/sessions/${sessionId}/zoom/before`;
}

export function zoomAfterUrl(sessionId: string): string {
  return `${BASE_URL}/sessions/${sessionId}/zoom/after`;
}

/** Writes one slider edit and returns the re-rendered "after" pane's PNG bytes directly (full
resolution by default, potentially several seconds for Film) -- callers debounce this while a
slider is being dragged, and use the returned Blob directly (via a fresh object URL) instead of a
redundant follow-up GET against zoomAfterUrl, which would render the same image a second time.

`maxDimension`, when given, requests a downscaled render instead (PERF-ZOOM-RENDER-PLAN.md étape
2) -- used for the fast reduced-resolution preview fired while a slider is actively being dragged;
omit it (or pass undefined) for the full-resolution render fired once dragging settles. */
export async function setZoomParameter(
  sessionId: string,
  identifier: string,
  value: number,
  maxDimension?: number,
): Promise<Blob> {
  const response = await fetch(`${BASE_URL}/sessions/${sessionId}/zoom/parameter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, value, max_dimension: maxDimension ?? null }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }
  return response.blob();
}

/** Batched sibling of setZoomParameter -- writes N slider edits in one call, triggering exactly
one render server-side instead of one per value. Required for "Réinitialiser" and polygon-vertex
mask commits, both of which otherwise fan out one setZoomParameter call per value. Same
`maxDimension` meaning as setZoomParameter's own. */
export async function setZoomParameters(
  sessionId: string,
  updates: Array<{ identifier: string; value: number }>,
  maxDimension?: number,
): Promise<Blob> {
  const response = await fetch(`${BASE_URL}/sessions/${sessionId}/zoom/parameters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ updates, max_dimension: maxDimension ?? null }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }
  return response.blob();
}

export function confirmZoom(sessionId: string): Promise<RowSpec[]> {
  return request(`/sessions/${sessionId}/zoom/confirm`, { method: "POST" });
}

export function cancelZoom(sessionId: string): Promise<RowSpec[]> {
  return request(`/sessions/${sessionId}/zoom/cancel`, { method: "POST" });
}

/* Auxiliary zoom parameters -- Geometry/Cadrage integrated into Film/Color Splash's own Zoom
(cross-row corrections). Unlike the functions above, `rowIdentifier` ("geometry"/"framing") names
a row OTHER than whichever one the Zoom session is actually open on -- see
lumaflow/api/session.py's own "Auxiliary zoom parameters" section for the backend half. */

export type AuxiliaryZoomState = {
  row_identifier: string;
  sliders: ZoomSlider[];
  overlays: ZoomOverlay[];
};

export function getAuxiliaryZoomState(sessionId: string, rowIdentifier: string): Promise<AuxiliaryZoomState> {
  return request(`/sessions/${sessionId}/zoom/auxiliary/${rowIdentifier}`);
}

export function auxiliaryZoomBeforeUrl(sessionId: string, rowIdentifier: string): string {
  return `${BASE_URL}/sessions/${sessionId}/zoom/auxiliary/${rowIdentifier}/before`;
}

/** Unlike setZoomParameter, does not return a rendered blob -- the combined preview (reflecting
this edit composited with Film/Color Splash's own grade) is only recomputed on demand via the
"Appliquer" button (zoomAfterUrl), not on every corner/crop-frame drag. */
export async function setAuxiliaryZoomParameter(
  sessionId: string,
  rowIdentifier: string,
  identifier: string,
  value: number,
): Promise<void> {
  const response = await fetch(`${BASE_URL}/sessions/${sessionId}/zoom/auxiliary/${rowIdentifier}/parameter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, value }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }
}

/* Préférences > Workflow (2026-08-06) -- rows themselves are structurally fixed (identifier/
label/category/short_description are read-only, always echoed back unchanged); only each row's
vignette enabled flag/order is ever written. `vignettes` is a single UNIFIED list -- every
vignette the row's addon can show, each carrying its own `enabled` flag -- not a curated list plus
a separate "available" list, so the whole catalog is visible with its state during administration. */
export type WorkflowVignetteConfig = {
  identifier: string;
  label: string;
  enabled: boolean;
};

export type WorkflowRowConfig = {
  identifier: string | null;
  label: string | null;
  category: string | null;
  short_description: string | null;
  vignettes: WorkflowVignetteConfig[];
};

export type WorkflowConfigData = {
  rows: WorkflowRowConfig[];
  /** Display-only: which file this payload reflects (default config path on GET/after PUT, the
  imported file's own path after an Ouvrir). Never meaningfully read back by PUT (it always
  (re)writes to the default path) -- kept here purely so the UI can show it. */
  source_path: string;
};

export function getWorkflowConfig(): Promise<WorkflowConfigData> {
  return request("/workflow-config");
}

export function putWorkflowConfig(config: WorkflowConfigData): Promise<WorkflowConfigData> {
  return request("/workflow-config", { method: "PUT", body: JSON.stringify(config) });
}

/** Same native-dialog pattern as loadRecipeDialog/saveRecipeDialog, defaulting to
config/config_workflow.json's own directory (not a Préférences-configured one). */
export function openWorkflowConfigDialog(): Promise<{ path: string | null }> {
  return request("/dialogs/open-workflow-config");
}

export function exportWorkflowConfigDialog(): Promise<{ path: string | null }> {
  return request("/dialogs/export-workflow-config");
}

/** Loads an arbitrary workflow JSON file into a DRAFT (never persisted/reloaded on its own) --
the caller still needs to submit it via putWorkflowConfig (Préférences dialog's "Valider") for it
to actually take effect. Rejected (ApiError, category "row_set_mismatch") if the file's row set/
order doesn't match the live configuration -- only vignette curation can ever differ. */
export function importWorkflowConfig(path: string): Promise<WorkflowConfigData> {
  return request("/workflow-config/import", { method: "POST", body: JSON.stringify({ path }) });
}

/** Pure file write of the given draft to an arbitrary path -- never touches the live/running
configuration (unlike putWorkflowConfig). */
export function exportWorkflowConfig(path: string, config: WorkflowConfigData): Promise<{ ok: boolean }> {
  return request("/workflow-config/export", {
    method: "POST",
    body: JSON.stringify({ path, rows: config.rows }),
  });
}

/* Traitement par lot (2026-08-25) -- mirrors lumaflow/api/app.py's /batch/* endpoints. Process-
wide, NOT session-scoped: a run is independent of whichever photo is open in the editor, and
outlives the request that started it (the batch window can be closed and reopened while it keeps
going) -- which is why progress is polled through getBatchRun rather than returned by startBatchRun. */

/** One batch as the backend expects it: N source files, one preset, one output directory. */
export type BatchSpecInput = {
  files: string[];
  preset_path: string;
  output_dir: string;
};

export type BatchProgress = {
  total: number;
  done: number;
  percent: number;
};

/** One journal line -- always one per source file attempted, success or failure, so the journal
accounts for every file the gauges claim to have processed. `message` is already a plain French
sentence written by the backend (lumaflow/engine/batch.py), never raw OS/parser text, so it is
displayed as-is rather than passed through errorMessages.ts. */
export type BatchLogEntry = {
  index: number;
  total: number;
  batch_index: number;
  file_name: string;
  output_name: string;
  ok: boolean;
  message: string;
};

export type BatchRun = {
  run_id: string;
  /** "running" until the run settles; "stopped" if the user asked it to end early, else "finished". */
  state: "running" | "stopped" | "finished";
  total: number;
  done: number;
  success_count: number;
  error_count: number;
  global_percent: number;
  /** Positional -- batches[i] is the progress of the i-th batch submitted to startBatchRun. */
  batches: BatchProgress[];
  log: BatchLogEntry[];
};

/** Multi-selection native dialog, same image filters (JPEG/PNG/RAW) as opening a single photo.
Returns an empty list if the user cancelled. */
export async function selectBatchFilesDialog(): Promise<string[]> {
  const result = await request<{ paths: string[] }>("/dialogs/select-batch-files");
  return result.paths;
}

/** Native folder picker for a batch's output directory. */
export function selectBatchOutputDirectoryDialog(): Promise<{ path: string | null }> {
  return request("/dialogs/select-batch-output-directory");
}

/** Schedules the run and returns its initial state immediately -- the work itself happens on a
backend thread. Rejects with ApiError 400 (a batch that cannot possibly succeed: no file, missing
preset, missing output directory) or 409 (another run is still going). */
export function startBatchRun(batches: BatchSpecInput[]): Promise<BatchRun> {
  return request("/batch/runs", { method: "POST", body: JSON.stringify({ batches }) });
}

export function getBatchRun(runId: string): Promise<BatchRun> {
  return request(`/batch/runs/${runId}`);
}

/** Asks the run to end after the image currently being processed -- so the returned state may
still be "running"; keep polling until it settles. */
export function stopBatchRun(runId: string): Promise<BatchRun> {
  return request(`/batch/runs/${runId}/stop`, { method: "POST" });
}
