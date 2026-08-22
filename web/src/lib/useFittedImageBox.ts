// LumaFlow v1.0 (2026-08-07)
// Hook React calculant en pixels explicites la taille d'une image ajustée (fit) à un viewport,
// avec zoom/pan -- garantit l'égalité pixel-parfaite wrapper/image nécessaire aux calculs de
// coordonnées de Geometry/Cadrage/Masque Sujet.
import { useCallback, useEffect, useRef, useState, type RefObject, type SyntheticEvent } from "react";
import { computeFitPercent, type ZoomBounds } from "./zoomFit";

const ZOOM_STEP_PERCENT = 25; // mirrors ZoomOverlay.tsx's own ZOOM_STEP_PERCENT

export type FittedImageBox = {
  /** Attach to the scrollable viewport div (the available space to fit/zoom the image into). */
  viewportRef: (node: HTMLDivElement | null) => void;
  /** Same node as viewportRef, kept as a stable RefObject for imperative scroll access (panning). */
  viewportElRef: RefObject<HTMLDivElement | null>;
  viewportSize: { width: number; height: number } | null;
  /** Attach to the fitted <img>'s onLoad. */
  handleImageLoad: (event: SyntheticEvent<HTMLImageElement>) => void;
  zoomPercent: number;
  /** Explicit pixel size for the photo-bounds wrapper (and its <img>, at width/height:100%) --
  null until both the image's natural size and the viewport's size are known, in which case the
  caller should fall back to CSS 100%/100% (see GeometryCanvas.css/CropCanvas.css). */
  contentSize: { width: number; height: number } | null;
  overflowsX: boolean;
  overflowsY: boolean;
  zoomIn: () => void;
  zoomOut: () => void;
  setZoomPercent: (percent: number) => void;
  fit: () => void;
};

/**
 * Sizes an image to exactly fit (or zoom beyond, for panning) an available viewport, preserving
 * aspect ratio -- in explicit pixels, never CSS percentages.
 *
 * Why: a pure-CSS wrapper (inline-block, flex, or grid were all tried in this exact codebase, see
 * memory geometry-cadrage-photo-overflow-grid-fix) cannot simultaneously guarantee (a) the wrapper
 * box is pixel-identical to the image's own rendered box -- required because Geometry/Cadrage/
 * Masque Sujet all convert pointer coordinates to normalized image-space fractions via
 * `photoRef.current.getBoundingClientRect()` on that same wrapper (GeometryToolStage.tsx,
 * CropToolStage.tsx, ZoomOverlay.tsx's maskFractionFromPointer) -- and (b) the image stays capped
 * to available space, and (c) zooming past 100% for precision work. Computing the size in JS from
 * naturalWidth/naturalHeight + a ResizeObserver-tracked viewport, exactly mirroring the mechanism
 * ZoomOverlay.tsx already uses for its main compare pane (naturalSize/viewportSize/
 * computeFitPercent), removes the ambiguity instead of guessing at another CSS combination.
 */
export function useFittedImageBox(zoomBounds: ZoomBounds): FittedImageBox {
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [viewportSize, setViewportSize] = useState<{ width: number; height: number } | null>(null);
  const [zoomPercent, setZoomPercentState] = useState<number | null>(null);
  const viewportElRef = useRef<HTMLDivElement | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  const viewportRef = useCallback((node: HTMLDivElement | null) => {
    viewportElRef.current = node;
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    if (node) {
      const observer = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (entry) setViewportSize({ width: entry.contentRect.width, height: entry.contentRect.height });
      });
      observer.observe(node);
      resizeObserverRef.current = observer;
    }
  }, []);

  useEffect(() => {
    if (zoomPercent !== null || !naturalSize || !viewportSize) return;
    setZoomPercentState(computeFitPercent(naturalSize, viewportSize, zoomBounds));
  }, [zoomPercent, naturalSize, viewportSize, zoomBounds]);

  function handleImageLoad(event: SyntheticEvent<HTMLImageElement>) {
    const img = event.currentTarget;
    setNaturalSize((current) => {
      if (current && current.width === img.naturalWidth && current.height === img.naturalHeight) return current;
      return { width: img.naturalWidth, height: img.naturalHeight };
    });
  }

  function clamp(percent: number) {
    return Math.max(zoomBounds.min, Math.min(zoomBounds.max, Math.round(percent)));
  }

  function zoomIn() {
    setZoomPercentState((p) => clamp((p ?? 100) + ZOOM_STEP_PERCENT));
  }

  function zoomOut() {
    setZoomPercentState((p) => clamp((p ?? 100) - ZOOM_STEP_PERCENT));
  }

  function setZoomPercent(percent: number) {
    setZoomPercentState(clamp(percent));
  }

  function fit() {
    if (naturalSize && viewportSize) setZoomPercentState(computeFitPercent(naturalSize, viewportSize, zoomBounds));
  }

  const contentSize =
    naturalSize && zoomPercent !== null
      ? {
          width: Math.round((naturalSize.width * zoomPercent) / 100),
          height: Math.round((naturalSize.height * zoomPercent) / 100),
        }
      : null;

  const overflowsX = Boolean(contentSize && viewportSize && contentSize.width > viewportSize.width + 0.5);
  const overflowsY = Boolean(contentSize && viewportSize && contentSize.height > viewportSize.height + 0.5);

  return {
    viewportRef,
    viewportElRef,
    viewportSize,
    handleImageLoad,
    zoomPercent: zoomPercent ?? 100,
    contentSize,
    overflowsX,
    overflowsY,
    zoomIn,
    zoomOut,
    setZoomPercent,
    fit,
  };
}
