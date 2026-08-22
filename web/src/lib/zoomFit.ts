// LumaFlow v1.0 (2026-08-07)
// Calcul pur du pourcentage de zoom "fit-to-viewport" pour une image, source unique de vérité
// partagée par ZoomOverlay.tsx et useFittedImageBox.
export type ZoomBounds = { min: number; max: number };

/** Fit-to-viewport zoom percent for an image of `natural` size inside `viewport`, preserving
aspect ratio, clamped to `bounds`. Floored, not rounded -- rounding up even fractionally can size
the scaled image 1px past the viewport, flipping on a spurious scrollbar for what should be a
clean, scrollbar-free fit (mirrors the old Qt UI's zoom_canvas.py's fit_to_screen).

Single source of truth for every "fit image to available space, allow zooming beyond 100% with
pan" surface in the Zoom overlay -- extracted 2026-07-31 so ZoomOverlay.tsx's main compare pane and
useFittedImageBox (Geometry/Cadrage) always agree on the same computation instead of two
independently-maintained copies that could drift. */
export function computeFitPercent(
  natural: { width: number; height: number },
  viewport: { width: number; height: number },
  bounds: ZoomBounds,
): number {
  if (viewport.width <= 0 || viewport.height <= 0 || natural.width <= 0 || natural.height <= 0) {
    return Math.max(bounds.min, Math.min(bounds.max, 100));
  }
  const ratio = Math.min(viewport.width / natural.width, viewport.height / natural.height);
  const percent = Math.floor(ratio * 100);
  return Math.max(bounds.min, Math.min(bounds.max, percent));
}
