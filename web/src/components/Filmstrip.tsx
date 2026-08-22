// LumaFlow v1.0 (2026-08-07)
// Pellicule principale : fenêtre glissante de 3 lignes visibles, navigation clavier (flèches/
// Espace) et déclenchement du Zoom sur la vignette sélectionnée.

import { useEffect, useRef, type KeyboardEvent } from "react";
import "./Filmstrip.css";
import type { RowSpec } from "../lib/api";
import { visibleRowIndices, visibleRowRealIndices } from "../lib/filmstrip";
import { FilmstripRow } from "./FilmstripRow";

export type LayoutPreferences = {
  row_spacing_px: number;
  vignette_margin_px: number;
  attenuated_opacity_percent: number;
  row_horizontal_margin_px: number;
};

type FilmstripProps = {
  rows: RowSpec[];
  activeStepIndex: number;
  sessionId: string;
  previewNonce: number;
  layoutPrefs: LayoutPreferences;
  onActivateStep: (index: number) => void;
  onSelectVignette: (index: number, identifier: string) => void;
  onZoomVignette?: (index: number, identifier: string) => void;
};

/* The pellicule: a 3-row sliding window (visibleRowIndices), not a full
scrollable list of every step -- matches both the mockup's framesA.prev/
active/next and the Qt app's actual _build_rows behavior. Container padding/
gap come straight from the live UIPreferences (row_spacing_px doubles as
both inter-row gap AND top/bottom outer margin, row_horizontal_margin_px is
the left/right outer margin only) -- same formula as FilmstripView's own
QVBoxLayout.setContentsMargins/setSpacing.

Keyboard nav: Up/Down change the active row, Left/Right change the active
row's selected vignette. Scoped to this subtree only (a plain onKeyDown on
a focusable container) -- React's bubbling naturally keeps this from firing
while focus is elsewhere (e.g. inside PreferencesDialog's number inputs,
which live outside this DOM subtree). Auto-focused on mount so arrows work
immediately after opening an image, mirroring app.py's own
window.filmstrip.setFocus() calls. */
export function Filmstrip({
  rows,
  activeStepIndex,
  sessionId,
  previewNonce,
  layoutPrefs,
  onActivateStep,
  onSelectVignette,
  onZoomVignette,
}: FilmstripProps) {
  // Geometry/Framing are real pipeline steps but no longer shown as filmstrip rows (2026-07-24,
  // now edited exclusively via Film/Color Splash's own Zoom) -- `visibleReal` keeps each
  // remaining row's REAL index (positional, matches the backend) while excluding those two, so
  // the 3-row window and Up/Down nav below operate on POSITIONS within this filtered list, never
  // landing on a hidden row, while everything downstream (activateStep, thumbnailUrl, zoomTarget)
  // still gets the real index it expects.
  const visibleReal = visibleRowRealIndices(rows);
  const activePos = visibleReal.indexOf(activeStepIndex);
  const visible = visibleRowIndices(activePos === -1 ? 0 : activePos, visibleReal.length).map((pos) => visibleReal[pos]);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    containerRef.current?.focus();
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (activePos > 0) onActivateStep(visibleReal[activePos - 1]);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      if (activePos !== -1 && activePos < visibleReal.length - 1) onActivateStep(visibleReal[activePos + 1]);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const row = rows[activeStepIndex];
      if (!row || row.vignette_labels.length === 0) return;
      const labels = row.vignette_labels;
      const currentIdentifier = row.selected_vignette_identifier ?? labels[0];
      const currentIndex = labels.indexOf(currentIdentifier);
      if (currentIndex === -1) return;
      const delta = event.key === "ArrowLeft" ? -1 : 1;
      const nextIndex = Math.max(0, Math.min(labels.length - 1, currentIndex + delta));
      if (nextIndex !== currentIndex) {
        onSelectVignette(activeStepIndex, labels[nextIndex]);
      }
    } else if (event.key === " " || event.key === "Spacebar") {
      // Third of the three equivalent Zoom triggers (FR-005: icône/double-clic/Espace) -- opens
      // Zoom on the active row's currently selected vignette, mirroring the icon/double-click
      // gating (only rows whose addon declares zoom parameters, RowSpec.has_zoom).
      const row = rows[activeStepIndex];
      if (!row || !row.has_zoom || !onZoomVignette) return;
      event.preventDefault();
      const identifier = row.selected_vignette_identifier ?? row.vignette_labels[0];
      if (identifier) onZoomVignette(activeStepIndex, identifier);
    }
  }

  return (
    <div
      ref={containerRef}
      className="filmstrip"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      style={{
        padding: `${layoutPrefs.row_spacing_px}px ${layoutPrefs.row_horizontal_margin_px}px`,
        gap: `${layoutPrefs.row_spacing_px}px`,
      }}
    >
      {visible.map((index) => (
        <FilmstripRow
          key={index}
          row={rows[index]}
          rowIndex={index}
          isActive={index === activeStepIndex}
          sessionId={sessionId}
          previewNonce={previewNonce}
          vignetteMarginPx={layoutPrefs.vignette_margin_px}
          attenuatedOpacityPercent={layoutPrefs.attenuated_opacity_percent}
          onActivate={() => onActivateStep(index)}
          onSelectVignette={(identifier) => onSelectVignette(index, identifier)}
          // Zoom overlay is available for any row whose addon actually declares manual
          // parameters (feature 046) -- derived server-side from the real addon resolution
          // (RowSpec.has_zoom), not a hardcoded row label. Was scoped to "Film" only
          // (2026-07-22) back when it was the sole row with an addon; Color Splash is the
          // first of what won't be the last.
          onZoomVignette={
            onZoomVignette && rows[index]?.has_zoom
              ? (identifier) => onZoomVignette(index, identifier)
              : undefined
          }
        />
      ))}
    </div>
  );
}
