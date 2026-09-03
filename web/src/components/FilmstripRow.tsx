// LumaFlow v1.0 (2026-08-07)
// Ligne individuelle de la pellicule : libellé de ligne, assombrissement si inactive et bandeau
// défilant des VignetteCard, avec remise en vue automatique de la vignette sélectionnée.

import { useEffect, useRef } from "react";
import "./FilmstripRow.css";
import * as api from "../lib/api";
import type { RowSpec } from "../lib/api";
import { VignetteCard } from "./VignetteCard";
import { rowDescription, rowDisplayLabel } from "../i18n/backend";

// Ported from filmstrip_view.py: DEFAULT_VIGNETTE_SPACING_PX (gap between
// cards) and FIRST_VIGNETTE_OFFSET_PX (the strip's left inset before the
// first card).
// ancien : la marge de fin (après la dernière vignette) réutilisait
// DEFAULT_VIGNETTE_SPACING_PX (6px, comme Qt) -- documentée à l'époque comme
// une asymétrie voulue, pas un oubli. Signalée par l'utilisateur comme un
// vrai défaut visuel côté web (la dernière vignette touche presque la bordure
// arrondie de la ligne) : LAST_VIGNETTE_OFFSET_PX reprend la même valeur que
// FIRST_VIGNETTE_OFFSET_PX pour une marge de fin symétrique et clairement
// visible.
const VIGNETTE_SPACING_PX = 6;
const FIRST_VIGNETTE_OFFSET_PX = 23;
const LAST_VIGNETTE_OFFSET_PX = 23;

type FilmstripRowProps = {
  row: RowSpec;
  rowIndex: number;
  isActive: boolean;
  sessionId: string;
  previewNonce: number;
  vignetteMarginPx: number;
  attenuatedOpacityPercent: number;
  onActivate: () => void;
  onSelectVignette: (identifier: string) => void;
  onZoomVignette?: (identifier: string) => void;
};

export function FilmstripRow({
  row,
  rowIndex,
  isActive,
  sessionId,
  previewNonce,
  vignetteMarginPx,
  attenuatedOpacityPercent,
  onActivate,
  onSelectVignette,
  onZoomVignette,
}: FilmstripRowProps) {
  // Keyboard arrow nav (Filmstrip.tsx's handleKeyDown) only updates row.selected_vignette_identifier
  // -- it never touches the DOM, so a selection change (keyboard, click on a partially-visible
  // card, or a fresh mount of this row via the sliding row window) must scroll the newly-selected
  // card into view itself, or it can end up selected but never actually visible/clickable.
  const cardRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => {
    const selected = row.selected_vignette_identifier;
    if (!selected) return;
    cardRefs.current[selected]?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [row.selected_vignette_identifier]);

  return (
    <div className="filmstrip-row" onClick={onActivate}>
      {!isActive && (
        <div
          className="filmstrip-row__dim"
          style={{ background: `rgba(0, 0, 0, ${1 - attenuatedOpacityPercent / 100})` }}
        />
      )}
      <div className={`filmstrip-row__label${isActive ? " filmstrip-row__label--active" : ""}`}>
        <span className="filmstrip-row__name">{rowDisplayLabel(row)}</span>
        {row.short_description && <span className="filmstrip-row__hint">{rowDescription(row)}</span>}
      </div>
      <div
        className="filmstrip-row__strip"
        style={{
          padding: `${vignetteMarginPx}px ${LAST_VIGNETTE_OFFSET_PX}px ${vignetteMarginPx}px ${FIRST_VIGNETTE_OFFSET_PX}px`,
          gap: `${VIGNETTE_SPACING_PX}px`,
          // Without this, scrollIntoView({ inline: "nearest" }) below stops as soon as the card
          // itself is visible -- it has no notion of the trailing padding being a margin worth
          // preserving, so keyboard nav onto the very first/last card left it flush against the
          // strip's edge (padding scrolled out of view) even though the CSS padding above is
          // correct. scroll-padding reserves that space for scrollIntoView's own calculation.
          scrollPaddingInline: `${FIRST_VIGNETTE_OFFSET_PX}px ${LAST_VIGNETTE_OFFSET_PX}px`,
        }}
      >
        {row.vignette_labels.map((identifier) => (
          <VignetteCard
            key={identifier}
            ref={(el) => {
              cardRefs.current[identifier] = el;
            }}
            rowIdentifier={row.identifier}
            identifier={identifier}
            state={row.vignette_states[identifier]}
            selected={row.selected_vignette_identifier === identifier}
            imageSrc={`${api.thumbnailUrl(sessionId, rowIndex, identifier)}?t=${previewNonce}`}
            onClick={() => onSelectVignette(identifier)}
            onZoom={onZoomVignette ? () => onZoomVignette(identifier) : undefined}
          />
        ))}
      </div>
    </div>
  );
}
