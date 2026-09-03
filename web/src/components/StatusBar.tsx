// LumaFlow v1.0 (2026-08-07)
// Barre de statut basse : miniature et métadonnées de la source, pastilles de navigation entre
// les étapes visibles et boutons précédent/suivant.

import "./StatusBar.css";
import type { RowSpec, SourceInfo } from "../lib/api";
import { visibleRowRealIndices } from "../lib/filmstrip";
import { t } from "../i18n";
import { rowDisplayLabel } from "../i18n/backend";

type StatusBarProps = {
  source: SourceInfo;
  previewSrc: string;
  rows: RowSpec[];
  activeStepIndex: number;
  onActivateStep: (index: number) => void;
};

export function StatusBar({ source, previewSrc, rows, activeStepIndex, onActivateStep }: StatusBarProps) {
  // Geometry/Framing are real pipeline steps but no longer shown here (2026-07-24, see
  // Filmstrip.tsx's identical comment) -- second navigation surface that would otherwise still
  // expose them via their own pill even once the filmstrip itself was fixed.
  const visibleReal = visibleRowRealIndices(rows);
  const activePos = visibleReal.indexOf(activeStepIndex);
  const canGoBack = activePos > 0;
  const canAdvance = activePos !== -1 && activePos < visibleReal.length - 1;

  return (
    <div id="statusBar" className="status-bar">
      <div className="status-bar-side status-bar-side--left">
        <div className="status-thumb">
          <img src={previewSrc} alt="" />
        </div>
        <div className="status-meta">
          <span className="status-filename">{source.filename}</span>
          {/* Real dimensions/format only -- the mockup's "24 MP · ISO 400 · 35
          mm · ƒ/8" is illustrative EXIF the engine does not extract today. */}
          <span className="status-details">
            {source.width} × {source.height} · {source.image_format}
          </span>
        </div>
        <span className="status-separator" />
      </div>
      <div className="status-bar-center">
        <button
          type="button"
          className="status-round-btn"
          title={t("ui.status.previous_step")}
          disabled={!canGoBack}
          style={{ opacity: canGoBack ? 1 : 0.3 }}
          onClick={() => canGoBack && onActivateStep(visibleReal[activePos - 1])}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
        <div className="status-pills">
          {visibleReal.map((index, pos) => {
            const row = rows[index];
            const done = index < activeStepIndex;
            const active = index === activeStepIndex;
            return (
              <button
                key={row.identifier}
                type="button"
                className={`status-pill${active ? " status-pill--active" : done ? " status-pill--done" : ""}`}
                onClick={() => onActivateStep(index)}
              >
                {/* Numbered by POSITION in the visible list (pos), not the real backend index --
                keeps a clean contiguous 01-05, no gap where Geometry/Framing used to be 01/02. */}
                <span className="status-pill-dot">{String(pos + 1).padStart(2, "0")}</span>
                <span className="status-pill-label">{rowDisplayLabel(row)}</span>
              </button>
            );
          })}
        </div>
        <button
          type="button"
          className="status-round-btn"
          title={t("ui.status.next_step")}
          disabled={!canAdvance}
          onClick={() => canAdvance && onActivateStep(visibleReal[activePos + 1])}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
      </div>
      <div className="status-bar-side status-bar-side--right" />
    </div>
  );
}
