// LumaFlow v1.0 (2026-08-07)
// Composant racine de l'IHM : orchestre la session backend (ouverture d'image, recettes,
// export), les préférences globales et assemble HeaderBar/Filmstrip/StatusBar/ZoomOverlay.

import { useEffect, useRef, useState } from "react";
import "./AppShell.css";
import * as api from "../lib/api";
import type { Preferences, RowSpec, SourceInfo } from "../lib/api";
import { Filmstrip } from "./Filmstrip";
import { HeaderBar } from "./HeaderBar";
import { InfoIcon } from "./icons";
import { contrastTextColor, hexToHsl, hexToRgbTriplet, hslToHex } from "../lib/color";
import { describeError } from "../lib/errorMessages";
import { HIDDEN_ROW_LABELS } from "../lib/filmstrip";
import { PreferencesDialog } from "./PreferencesDialog";
// Sidebar removed from the UI 2026-07-29 -- see Sidebar.tsx's own header comment.
import { StatusBar } from "./StatusBar";
import { ZoomOverlay } from "./ZoomOverlay";

// Mirrors lumaflow/persistence/preferences.py's DEFAULT_* constants -- used
// only until the real GET /preferences resolves, so the filmstrip has a
// sane layout on first paint instead of collapsing to 0px gaps.
// RowSpec only carries `label` (display text), not the backend's row `identifier` -- needed here
// to name a step in a dimension_warning (only geometry/framing are dimension-sensitive) or a
// parameter_corrections entry (any addon, feature 048) -- a small fixed map (mirroring
// lumaflow/config/config_workflow.json's identifier/label pairs) is simpler than plumbing
// identifiers through RowSpec just for this.
const STEP_IDENTIFIER_LABELS: Record<string, string> = {
  geometry: "Geometry",
  framing: "Framing",
  film: "Film",
  bleach_bypass: "Bleach Bypass",
  color_splash: "Color Splash",
  monochrome: "Monochrome",
  bw: "B&W",
  light: "Light",
  vignette: "Vignettage",
};

const DEFAULT_LAYOUT_PREFS: Preferences = {
  menu_position: "left",
  menu_collapsed: false,
  row_spacing_px: 8,
  vignette_margin_px: 8,
  attenuated_opacity_percent: 80,
  row_horizontal_margin_px: 8,
  zoom_min_percent: 20,
  zoom_max_percent: 400,
  export_jpeg_quality: 90,
  guide_limit_color: "#E3A75E",
  guide_overlay_color: "#FFFFFF",
  accent_color: "#E3A75E",
  presets_directory: null,
  open_image_directory: null,
  export_image_directory: null,
  workflow_config_source_path: null,
};

export function AppShell() {
  const [showPreferences, setShowPreferences] = useState(false);
  const [layoutPrefs, setLayoutPrefs] = useState<Preferences>(DEFAULT_LAYOUT_PREFS);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [rows, setRows] = useState<RowSpec[]>([]);
  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const [source, setSource] = useState<SourceInfo | null>(null);
  // Header preset combobox (2026-08-05, user request): the absolute path of whichever preset
  // (recipe) is currently active, whether it got there via the combobox itself or the header
  // menu's "Presets" group (Ouvrir = loadRecipe, Exporter = saveRecipe). null = "Nouveau"/no
  // active preset. PresetSelector derives the displayed label from this + `presets` itself, so
  // there's no separate display-text state to keep in sync. Deliberately NOT tied to the photo
  // itself (handleOpen) -- only preset load/save/select, per the user's explicit scope.
  const [activePresetPath, setActivePresetPath] = useState<string | null>(null);
  // Presets listed in Préférences > Général's configured directory, alphabetically sorted by the
  // backend -- powers the header combobox. Empty until a directory is configured.
  const [presets, setPresets] = useState<api.PresetEntry[]>([]);
  const [previewNonce, setPreviewNonce] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [zoomTarget, setZoomTarget] = useState<{ stepIndex: number; identifier: string } | null>(null);
  const [dimensionWarning, setDimensionWarning] = useState<api.DimensionWarning | null>(null);
  const [parameterCorrections, setParameterCorrections] = useState<api.ParameterCorrection[]>([]);
  // Préférences > Workflow (2026-08-06): a loaded recipe's vignette selection was disabled since
  // it was saved -- the backend already fell back to that row's neutral vignette (never applies a
  // disabled vignette's rendering), this just surfaces the substitution non-blockingly, same
  // pattern as parameterCorrections above.
  const [disabledVignetteCorrections, setDisabledVignetteCorrections] = useState<api.DisabledVignetteCorrection[]>([]);
  // Minimal busy indicator (FR-005) -- a label, not a determinate progress bar (no endpoint
  // below exposes granular progress, faking one would be misleading). Only wraps the
  // real work after a native dialog resolves -- the OS dialog itself is already its own visual
  // "busy" state while open, nothing to add there.
  const [busy, setBusy] = useState<string | null>(null);

  // Tracks the most recent in-flight session-mutating request (select_vignette, activate_step) --
  // mirrors ZoomOverlay.tsx's own pendingCommit/trackCommit pattern, for the same reason: these
  // calls updated local state only after their own promise resolved, but nothing stopped a
  // subsequent action (Export, Enregistrer la recette) from firing its own request in the
  // meantime and reading/exporting session state from BEFORE the edit landed server-side. Far more
  // likely to be hit on a RAW-origin session (multi-second full-resolution decode/develop per
  // request) than on JPEG/PNG, where the same race window is too short to ever notice (bug report,
  // 2026-08-04: a Light/High Key preset click followed promptly by Export produced a file that
  // still looked like the pre-edit, darker RAW render). Never rejects itself, so awaiting this
  // never throws.
  const pendingMutation = useRef<Promise<unknown>>(Promise.resolve());
  function trackMutation<T>(promise: Promise<T>): Promise<T> {
    pendingMutation.current = promise.then(
      () => undefined,
      () => undefined,
    );
    return promise;
  }

  useEffect(() => {
    api.getPreferences().then(setLayoutPrefs).catch(() => {});
    api.listPresets().then(setPresets).catch(() => {});
  }, []);

  // Guide colors (Geometry/Cadrage/Masque Sujet/Vignette aide dynamique, Préférences > Vignettes,
  // 2026-08-06) apply globally via CSS custom properties overridden on the root element -- this
  // inline override on <html> wins over tokens.css's :root fallback, and every guide-drawing
  // component inherits it since none of them render through a portal outside this document tree.
  // Re-runs on initial load AND after Préférences > Valider (handlePreferencesSaved below).
  useEffect(() => {
    document.documentElement.style.setProperty("--guide-limit-color", layoutPrefs.guide_limit_color);
    document.documentElement.style.setProperty("--guide-overlay-color", layoutPrefs.guide_overlay_color);
  }, [layoutPrefs.guide_limit_color, layoutPrefs.guide_overlay_color]);

  // Couleur d'accentuation globale (Préférences > Général, 2026-08-07) -- même mécanisme que les
  // couleurs de guidage ci-dessus (override CSS custom property sur <html>), mais dérive en plus
  // deux teintes (--amber2, hover/actif) et deux valeurs dépendantes (--amber-rgb pour les rgba()
  // qui ne peuvent pas décomposer une hex custom property, --accent-text pour un contraste
  // clair/sombre automatique sur les fonds pleins accent). Indépendant de --guide-limit-color/
  // --guide-overlay-color ci-dessus -- aucune des deux préférences ne modifie l'autre.
  useEffect(() => {
    const accent = layoutPrefs.accent_color;
    const parsed = hexToHsl(accent);
    const amber2 = parsed ? hslToHex(parsed.hue, parsed.saturation, Math.max(0, parsed.lightness - 5)) : accent;
    const amberRgb = hexToRgbTriplet(accent);
    document.documentElement.style.setProperty("--amber", accent);
    document.documentElement.style.setProperty("--amber2", amber2);
    document.documentElement.style.setProperty("--amber-rgb", amberRgb);
    document.documentElement.style.setProperty("--halo", `rgba(${amberRgb}, 0.28)`);
    document.documentElement.style.setProperty("--accent-text", contrastTextColor(accent));
  }, [layoutPrefs.accent_color]);

  async function withBusy<T>(label: string, fn: () => Promise<T>): Promise<T> {
    setBusy(label);
    try {
      return await fn();
    } finally {
      // Always resolves, success or error (Edge Case: never left indefinitely visible) -- the
      // catch block around each call site below still runs afterward to set/clear `error`.
      setBusy(null);
    }
  }

  async function ensureSession(): Promise<string> {
    if (sessionId) return sessionId;
    const created = await api.createSession();
    setSessionId(created.id);
    return created.id;
  }

  async function handleOpen() {
    setError(null);
    setDimensionWarning(null);
    setParameterCorrections([]);
    setDisabledVignetteCorrections([]);
    let path: string | null;
    try {
      path = (await api.openImageDialog()).path;
    } catch (err) {
      setError(describeError(err));
      return;
    }
    if (!path) return;
    const resolvedPath = path;
    try {
      await withBusy("Ouverture de l'image…", async () => {
        const id = await ensureSession();
        const openedRows = await api.openImage(id, resolvedPath);
        const info = await api.getSessionInfo(id);
        setRows(openedRows);
        // Geometry/Framing (indices 0/1) are no longer shown as filmstrip rows (2026-07-24) --
        // land on the first VISIBLE row instead of the hardcoded 0, or the newly opened image
        // would default to a row nothing in the UI can reach anymore.
        const firstVisible = openedRows.findIndex((row) => !HIDDEN_ROW_LABELS.has(row.label));
        setActiveStepIndex(firstVisible === -1 ? 0 : firstVisible);
        setSource(info.source);
        setPreviewNonce((n) => n + 1);
      });
    } catch (err) {
      setError(describeError(err));
    }
  }

  async function handleSave() {
    if (!sessionId) return;
    setError(null);
    let path: string | null;
    try {
      path = (await api.saveRecipeDialog()).path;
    } catch (err) {
      setError(describeError(err));
      return;
    }
    if (!path) return;
    const resolvedPath = path;
    try {
      // Wait for any preset selection / row activation still in flight to actually land on the
      // backend session before saving the recipe -- otherwise a save fired right after a click
      // could persist the PREVIOUS parameters, not the one just clicked (see pendingMutation).
      await pendingMutation.current;
      await withBusy("Sauvegarde de la recette…", () => api.saveRecipe(sessionId, resolvedPath, true));
      setActivePresetPath(resolvedPath);
    } catch (err) {
      setError(describeError(err));
    }
  }

  /** Applies the recipe at `path` onto the current session -- shared by handleLoadRecipe (path
  from the native dialog) and handleSelectPreset (path already known, from the header combobox). */
  async function applyRecipeAtPath(path: string) {
    if (!sessionId) return;
    setError(null);
    setDimensionWarning(null);
    setParameterCorrections([]);
    setDisabledVignetteCorrections([]);
    try {
      await withBusy("Chargement de la recette…", async () => {
        const {
          rows: updatedRows,
          dimension_warning,
          parameter_corrections,
          disabled_vignette_corrections,
        } = await api.loadRecipe(sessionId, path);
        setRows(updatedRows);
        // Mirrors handleOpen: land on the first VISIBLE row (Geometry/Framing are hidden), matching
        // apply_recipe's own active_step_index reset to 0 server-side.
        const firstVisible = updatedRows.findIndex((row) => !HIDDEN_ROW_LABELS.has(row.label));
        setActiveStepIndex(firstVisible === -1 ? 0 : firstVisible);
        setPreviewNonce((n) => n + 1);
        // Non-blocking (FR-004's Edge Case): never prevents the recipe from being applied above, or
        // subsequent editing/export -- purely informational.
        setDimensionWarning(dimension_warning);
        setParameterCorrections(parameter_corrections);
        setDisabledVignetteCorrections(disabled_vignette_corrections);
        setActivePresetPath(path);
      });
    } catch (err) {
      // A blocking failure here (missing addon, unsupported schema version, unreadable file,
      // application error -- FR-001/002/003) MUST leave the active session untouched (FR-006/
      // FR-008) -- this catch deliberately never touches rows/activeStepIndex/previewNonce, only
      // surfaces the categorized message (FR-007: the user can dismiss it and resume immediately).
      setError(describeError(err));
    }
  }

  async function handleLoadRecipe() {
    if (!sessionId) return;
    let path: string | null;
    try {
      path = (await api.loadRecipeDialog()).path;
    } catch (err) {
      setError(describeError(err));
      return;
    }
    if (!path) return;
    await applyRecipeAtPath(path);
  }

  /** Header combobox selection (2026-08-05): `path === null` is "Nouveau" -- resets every row's
  selection to its neutral default on the currently open image, without reloading the image file
  or a native dialog round-trip. A real preset `path` reuses the exact same apply path as the
  Presets > Ouvrir menu item. */
  async function handleSelectPreset(path: string | null) {
    if (!sessionId) return;
    if (path !== null) {
      await applyRecipeAtPath(path);
      return;
    }
    setError(null);
    try {
      await withBusy("Réinitialisation…", async () => {
        const updatedRows = await trackMutation(api.resetSession(sessionId));
        setRows(updatedRows);
        const firstVisible = updatedRows.findIndex((row) => !HIDDEN_ROW_LABELS.has(row.label));
        setActiveStepIndex(firstVisible === -1 ? 0 : firstVisible);
        setPreviewNonce((n) => n + 1);
        setDimensionWarning(null);
        setParameterCorrections([]);
        setDisabledVignetteCorrections([]);
      });
    } catch (err) {
      setError(describeError(err));
      return;
    }
    setActivePresetPath(null);
  }

  async function handleExport() {
    if (!sessionId) return;
    setError(null);
    let path: string | null;
    try {
      path = (await api.exportImageDialog()).path;
    } catch (err) {
      setError(describeError(err));
      return;
    }
    if (!path) return;
    const resolvedPath = path;
    try {
      // Wait for any preset selection / row activation still in flight to actually land on the
      // backend session before rendering the export -- otherwise an export fired right after a
      // click (e.g. Light/High Key) could render the PREVIOUS, pre-edit pixels instead of what was
      // just applied (see pendingMutation's own comment for the bug this closes).
      await pendingMutation.current;
      await withBusy("Export en cours…", () =>
        api.exportImage(sessionId, resolvedPath, resolvedPath.toLowerCase().endsWith(".png") ? "PNG" : "JPEG", {
          force: true,
          jpegQuality: layoutPrefs.export_jpeg_quality,
        }),
      );
    } catch (err) {
      setError(describeError(err));
    }
  }

  async function handleActivateStep(index: number) {
    if (!sessionId || index < 0 || index >= rows.length) return;
    setError(null);
    try {
      const updatedRows = await trackMutation(api.activateStep(sessionId, index));
      setRows(updatedRows);
      setActiveStepIndex(index);
      setPreviewNonce((n) => n + 1);
    } catch (err) {
      setError(describeError(err));
    }
  }

  async function handleSelectVignette(index: number, identifier: string) {
    if (!sessionId) return;
    setError(null);
    try {
      const updatedRows = await trackMutation(api.selectVignette(sessionId, index, identifier));
      setRows(updatedRows);
      setActiveStepIndex(index);
      setPreviewNonce((n) => n + 1);
    } catch (err) {
      setError(describeError(err));
    }
  }

  function handleZoomVignette(index: number, identifier: string) {
    setZoomTarget({ stepIndex: index, identifier });
  }

  function handleZoomConfirm(updatedRows: api.RowSpec[]) {
    setRows(updatedRows);
    setPreviewNonce((n) => n + 1);
    setZoomTarget(null);
  }

  function handleZoomCancel(updatedRows: api.RowSpec[]) {
    setRows(updatedRows);
    setPreviewNonce((n) => n + 1);
    setZoomTarget(null);
  }

  function handlePreferencesSaved(saved: Preferences) {
    setLayoutPrefs(saved);
    // Presets directory may have just changed -- re-populate the header combobox immediately
    // rather than waiting for the next full page load.
    api.listPresets().then(setPresets).catch(() => {});
    // Préférences > Workflow (2026-08-06 follow-up): the backend already reloads
    // WORKFLOW_CONFIG/WORKFLOW_ROWS synchronously on Valider (session.py's
    // reload_workflow_config) and self-heals any now-disabled selection on the currently open
    // session (refresh_workflow) -- but nothing previously told THIS tab to re-fetch, so an
    // already-open photo's filmstrip kept showing the pre-Valider vignette list until the next
    // Ouvrir. Re-fetch now, tracked like every other session-touching call so a rapid
    // Export/Enregistrer right after closing Préférences can't race ahead of it.
    if (sessionId) {
      trackMutation(api.getWorkflow(sessionId).then(setRows)).catch(() => {});
    }
  }

  const hasImage = Boolean(source && rows.length > 0 && sessionId);

  return (
    <div id="appShell" className="app-shell">
      <HeaderBar
        presets={presets}
        activePresetPath={activePresetPath}
        onSelectPreset={handleSelectPreset}
        onOpen={handleOpen}
        onSave={handleSave}
        onExport={handleExport}
        onLoadRecipe={handleLoadRecipe}
        onOpenPreferences={() => setShowPreferences(true)}
      />
      <div className="app-body">
        <div id="centralWorkArea" className="central-work-area">
          {busy && <div className="central-work-area__busy">{busy}</div>}
          {error && <div className="central-work-area__error">{error}</div>}
          {dimensionWarning?.incompatible && (
            <div className="central-work-area__warning">
              Cette recette a été créée pour des proportions d'image différentes. Réglages
              potentiellement affectés :{" "}
              {dimensionWarning.steps
                .map((step) => {
                  const label = STEP_IDENTIFIER_LABELS[step.step_identifier] ?? step.step_identifier;
                  const statusLabel = step.status === "adapted" ? "adapté" : "appliqué tel quel";
                  return `${label} (${statusLabel})`;
                })
                .join(", ")}
              .
            </div>
          )}
          {parameterCorrections.length > 0 && (
            <div className="central-work-area__warning">
              Certains réglages hors bornes ont été automatiquement corrigés :{" "}
              {parameterCorrections
                .map((correction) => {
                  const label = STEP_IDENTIFIER_LABELS[correction.step_identifier] ?? correction.step_identifier;
                  return `${label} · ${correction.parameter} (${correction.requested} → ${correction.applied})`;
                })
                .join(", ")}
              .
            </div>
          )}
          {disabledVignetteCorrections.length > 0 && (
            <div className="central-work-area__warning">
              Certaines vignettes ont été désactivées depuis l'enregistrement de cette recette et
              ont été remplacées par le réglage neutre de leur ligne :{" "}
              {disabledVignetteCorrections
                .map((correction) => {
                  const label = STEP_IDENTIFIER_LABELS[correction.step_identifier] ?? correction.step_identifier;
                  return `${label} · ${correction.requested_identifier}`;
                })
                .join(", ")}
              .
            </div>
          )}
          {hasImage && sessionId ? (
            <Filmstrip
              rows={rows}
              activeStepIndex={activeStepIndex}
              sessionId={sessionId}
              previewNonce={previewNonce}
              layoutPrefs={layoutPrefs}
              onActivateStep={handleActivateStep}
              onSelectVignette={handleSelectVignette}
              onZoomVignette={handleZoomVignette}
            />
          ) : (
            !error && (
              <div className="work-placeholder">Ouvrez une image (bouton «Ouvrir») pour commencer.</div>
            )
          )}
          {hasImage && sessionId && source && (
            <StatusBar
              source={source}
              previewSrc={`${api.previewUrl(sessionId)}?t=${previewNonce}`}
              rows={rows}
              activeStepIndex={activeStepIndex}
              onActivateStep={handleActivateStep}
            />
          )}
          {zoomTarget && sessionId && (
            <ZoomOverlay
              sessionId={sessionId}
              stepIndex={zoomTarget.stepIndex}
              rowLabel={rows[zoomTarget.stepIndex]?.label ?? ""}
              identifier={zoomTarget.identifier}
              onConfirm={handleZoomConfirm}
              onCancel={handleZoomCancel}
            />
          )}
        </div>
      </div>
      <div className="app-footer">
        <InfoIcon />
        {/* FR-003/SC-003: the main keyboard shortcuts (Espace/flèches/Échap), consultable
        directly in the interface without external documentation -- this footer is the existing
        always-visible "aide minimale intégrée", extended rather than replaced with
        a new UI surface (YAGNI). The full text is also on `title` so it stays fully
        discoverable (native tooltip) even if the single line truncates on a narrow window. */}
        <span
          title="Flèches Haut/Bas : changer d'étape · Flèches Gauche/Droite : changer de vignette · Espace, double-clic ou l'icône loupe sur une vignette : ouvrir le Zoom · Échap : fermer un menu ou le Zoom · Cliquez une ligne assombrie pour y revenir"
        >
          Flèches : naviguer · Espace, double-clic ou l'icône loupe : Zoom · Échap : fermer · Cliquez une
          ligne assombrie pour y revenir
        </span>
      </div>
      {showPreferences && <PreferencesDialog onClose={() => setShowPreferences(false)} onSaved={handlePreferencesSaved} />}
    </div>
  );
}
