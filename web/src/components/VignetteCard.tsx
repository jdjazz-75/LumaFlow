// LumaFlow v1.0 (2026-08-07)
// Vignette individuelle d'une ligne de la pellicule : miniature, légende, bouton Zoom (loupe) et
// badge de sélection.

import { forwardRef, type MouseEvent } from "react";
import "./VignetteCard.css";
import type { VignetteState } from "../lib/api";
import { ZoomIcon } from "./icons";
import { t } from "../i18n";
import { presetLabel } from "../i18n/backend";

type VignetteCardProps = {
  /** The owning row's RowSpec.identifier -- scopes the preset-name lookup so two rows may name
  the same identifier differently (i18n phase 3). */
  rowIdentifier: string;
  identifier: string;
  state: VignetteState | undefined;
  selected: boolean;
  imageSrc: string;
  onClick: () => void;
  onZoom?: () => void;
};

// forwardRef exposes the root <button> so FilmstripRow can scrollIntoView() it when it becomes
// the selected vignette (keyboard arrow nav previously moved the selection without ever
// scrolling the horizontal strip to reveal it).
export const VignetteCard = forwardRef<HTMLButtonElement, VignetteCardProps>(function VignetteCard(
  { rowIdentifier, identifier, state, selected, imageSrc, onClick, onZoom },
  ref,
) {
  const status = state?.status ?? "pending";
  const isError = status === "error";

  function handleClick(event: MouseEvent) {
    event.stopPropagation();
    onClick();
  }

  function handleDoubleClick(event: MouseEvent) {
    event.stopPropagation();
    if (onZoom && status === "ready") onZoom();
  }

  function handleZoomButtonClick(event: MouseEvent) {
    event.stopPropagation();
    if (onZoom && status === "ready") onZoom();
  }

  return (
    <button
      ref={ref}
      type="button"
      className={`vignette-card${selected ? " vignette-card--selected" : ""}${isError ? " vignette-card--error" : ""}`}
      // Raw, locale-independent identifier -- distinct from the (now possibly translated,
      // i18n phase 3) caption text below. Exists purely for tooling/tests: a persisted recipe's
      // `thumbnail_identifier` never changes with locale (D5), so a test that wants to compare a
      // selection against the saved recipe must read THIS, not the caption's innerText.
      data-identifier={identifier}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
    >
      <span className="vignette-card__image">
        {status === "ready" && <img src={imageSrc} alt="" />}
        {status === "error" && <span className="vignette-card__error">{t("ui.vignette.error")}</span>}
      </span>
      <span className="vignette-card__caption">
        <span className="vignette-card__caption-text">{presetLabel(rowIdentifier, identifier)}</span>
        {onZoom && status === "ready" && (
          <span
            role="button"
            tabIndex={-1}
            className="vignette-card__zoom"
            title={t("ui.vignette.zoom")}
            onClick={handleZoomButtonClick}
          >
            <ZoomIcon />
          </span>
        )}
      </span>
      {selected && !isError && (
        <span className="vignette-card__badge">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent-text)" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 6L9 17l-5-5" />
          </svg>
        </span>
      )}
    </button>
  );
});
