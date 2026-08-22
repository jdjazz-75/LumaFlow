// LumaFlow v1.0 (2026-08-07)
// Barre d'outils de zoom optique réutilisable (slider + saisie numérique + bouton "Ajuster"),
// utilisée par les stages Geometry/Cadrage.

import { useEffect, useState } from "react";
import type { ZoomBounds } from "../lib/zoomFit";

type ZoomToolbarProps = {
  zoomPercent: number;
  zoomBounds: ZoomBounds;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomChange: (percent: number) => void;
  onFit: () => void;
};

/** Zoom slider + numeric input + "Ajuster" button, reusing ZoomOverlay.css's
`.zoom-overlay__optical-zoom` styling verbatim. Extracted 2026-07-31 for Geometry/Cadrage's newly
zoomable stages (see useFittedImageBox) -- ZoomOverlay.tsx's main compare pane keeps its own inline
JSX rather than being migrated to this component, to avoid touching already-working code while
fixing this bug class. */
export function ZoomToolbar({ zoomPercent, zoomBounds, onZoomIn, onZoomOut, onZoomChange, onFit }: ZoomToolbarProps) {
  const [inputText, setInputText] = useState(String(zoomPercent));

  useEffect(() => setInputText(String(zoomPercent)), [zoomPercent]);

  function commit() {
    const value = Number(inputText);
    if (Number.isFinite(value)) onZoomChange(value);
    else setInputText(String(zoomPercent));
  }

  return (
    <div className="zoom-overlay__optical-zoom">
      <span className="zoom-overlay__optical-zoom-label">Zoom</span>
      <button type="button" className="zoom-overlay__optical-zoom-button" onClick={onZoomOut} aria-label="Zoom arrière">
        −
      </button>
      <input
        type="range"
        className="zoom-overlay__optical-zoom-slider"
        min={zoomBounds.min}
        max={zoomBounds.max}
        step={1}
        value={zoomPercent}
        onChange={(event) => onZoomChange(Number(event.target.value))}
      />
      <button type="button" className="zoom-overlay__optical-zoom-button" onClick={onZoomIn} aria-label="Zoom avant">
        +
      </button>
      <input
        type="text"
        inputMode="numeric"
        className="zoom-overlay__optical-zoom-input"
        value={inputText}
        onChange={(event) => setInputText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
        aria-label="Pourcentage de zoom"
      />
      <span className="zoom-overlay__optical-zoom-percent-sign">%</span>
      <button type="button" className="zoom-overlay__optical-zoom-fit" onClick={onFit}>
        Ajuster
      </button>
    </div>
  );
}
